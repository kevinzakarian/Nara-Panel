import copy
import json
import tempfile
import unittest
from pathlib import Path
from nara import native
from nara.config import build_config, client_config, initial_state, validate
from nara.store import Store
from tests.helpers import example_state


def row(config, ident='native'):
    return {'id':ident,'mode':'native','enabled':True,'type':config.get('type',''),
            'tag':config.get('tag',''),'config':config}


class NativeTests(unittest.TestCase):
    def test_remote_dns_domains_require_bootstrap_and_separate_url_fields(self):
        for kind in ('udp', 'tcp', 'tls', 'https', 'quic', 'h3'):
            with self.subTest(type=kind):
                state = initial_state()
                config = {'type':kind, 'tag':'remote', 'server':'dns.google'}
                state['dns_servers'].append(row(config))
                with self.assertRaisesRegex(ValueError, 'bootstrap resolver'):
                    validate(state)
                config['domain_resolver'] = {'server':'bootstrap', 'strategy':'prefer_ipv4'}
                validate(state)
                config['server'] = 'https://dns.google/dns-query'
                with self.assertRaisesRegex(ValueError, 'without a scheme'):
                    validate(state)
                config['server'] = '8.8.8.8'
                config.pop('domain_resolver')
                validate(state)

    def test_dns_bootstrap_cycles_still_fail_and_detoured_domains_are_supported(self):
        state = initial_state()
        state['dns_servers'].append(row({'type':'https', 'tag':'remote', 'server':'dns.google', 'domain_resolver':'remote'}))
        with self.assertRaisesRegex(ValueError, 'separate configured'):
            validate(state)
        state['dns_servers'][1]['config']['domain_resolver'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'separate configured'):
            validate(state)
        state['dns_servers'][1]['config'].pop('domain_resolver')
        state['dns_servers'][1]['config']['detour'] = 'proxy'
        validate(state)

    def test_exact_protocols_and_all_top_level_sections_are_exposed(self):
        expected={'anytls','cloudflared','direct','http','hysteria','hysteria2','mixed','naive','redirect','shadowsocks','shadowtls','snell','socks','tproxy','trojan','tuic','tun','vless','vmess'}
        self.assertEqual(set(native.types('Inbound')), expected)
        self.assertEqual(len(native.types('DNSServer')),15)
        for key in ('log','dns','ntp','certificate','certificate_providers','http_clients','network_namespaces','endpoints','inbounds','outbounds','route','services','experimental'):
            self.assertIn(key,native.SCHEMA['properties'])
        self.assertEqual(native.LABELS['vmess'],'VMess')
        self.assertEqual(native.LABELS['shadowtls'],'ShadowTLS')

    def test_standalone_listener_starts_without_panel_clients_and_keeps_all_fields(self):
        state=initial_state()
        conf={'type':'shadowsocks','tag':'ss','listen':'127.0.0.1','listen_port':18445,
              'method':'aes-128-gcm','password':'fixture-key','tcp_fast_open':True}
        state['inbounds']=[row(conf)]
        result=build_config(state,{},Path('/tmp'))
        self.assertEqual(result['inbounds'],[conf])
        state['inbounds'][0]['enabled']=False
        self.assertEqual(build_config(state,{},Path('/tmp'))['inbounds'],[])
        self.assertEqual(build_config(state,{},Path('/tmp'),check_all=True)['inbounds'],[conf])

    def test_standalone_does_not_claim_account_quotas_or_exports(self):
        state=example_state()
        state['inbounds']=[row({'type':'socks','tag':'socks','listen':'127.0.0.1','listen_port':18445},'in1')]
        with self.assertRaisesRegex(ValueError,'Standalone'):
            validate(state)
        with self.assertRaisesRegex(ValueError,'No enabled inbound'):
            client_config(state,state['clients'][0],{})

    def test_public_unauthenticated_proxy_requires_explicit_opt_in(self):
        for kind in ('socks','mixed','http','shadowsocks'):
            state=initial_state();state['inbounds']=[row({'type':kind,'tag':'public','listen':'::','listen_port':18445})]
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'authentication'):
                validate(state)
            state['inbounds'][0]['allow_unauthenticated']=True
            validate(state)

    def test_complete_dns_routing_and_other_sections_are_composed(self):
        state=initial_state()
        state['dns_servers'].append(row({'type':'hosts','tag':'hosts','predefined':{'example.com':['192.0.2.1']}}))
        rule={'type':'logical','mode':'or','rules':[{'domain_suffix':['example.com']},{'query_type':['A']}], 'action':'route','server':'hosts'}
        state['dns_rules']=[row(rule)]
        state['route_rules']=[row({'domain_suffix':['example.com'],'action':'route','outbound':'other'})]
        state['outbounds']=[row({'type':'direct','tag':'other','connect_timeout':'3s'})]
        state['core_options']={'dns':{'optimistic':{'enabled':True}},'route':{'auto_detect_interface':True},'ntp':{'enabled':False}}
        config=build_config(state,{},Path('/tmp'))
        self.assertEqual(config['dns']['rules'],[rule])
        self.assertEqual(config['dns']['servers'][1]['type'],'hosts')
        self.assertEqual(config['route']['rules'][0],{'ip_is_private':True,'action':'reject'})
        self.assertEqual(config['route']['rules'][1]['outbound'],'other')
        self.assertTrue(config['dns']['optimistic']['enabled'])
        self.assertEqual(config['outbounds'][1]['connect_timeout'],'3s')

    def test_managed_accounting_and_credentials_cannot_be_overridden(self):
        state=example_state();state['inbounds'][0]['extra_options']={'users':[]}
        with self.assertRaisesRegex(ValueError,'cannot be overridden'):
            build_config(state,{},Path('/tmp'))
        state=initial_state();state['core_options']={'experimental':{'v2ray_api':{'listen':'0.0.0.0:1234'}}}
        with self.assertRaisesRegex(ValueError,'accounting API'):
            build_config(state,{},Path('/tmp'))

    def test_private_keys_are_redacted_and_preserved_on_edit(self):
        before={'tls':{'enabled':True,'key':['private-value'],'certificate':['public-value']},'peers':[{'public_key':'A','preshared_key':'private-A'},{'public_key':'B','preshared_key':'private-B'}]}
        public=native.redact(before)
        self.assertNotIn('private-value',json.dumps(public))
        public['peers'].reverse()
        after=native.preserve_secrets(public,before)
        self.assertEqual(after['tls']['key'],['private-value'])
        self.assertEqual(after['peers'][0]['preshared_key'],'private-B')
        self.assertNotIn('tls',native.preserve_secrets({'peers':[]},before))
        self.assertEqual(native.preserve_secrets({'private_key':'replacement'},{'private_key':'old'})['private_key'],'replacement')

    def test_old_saved_and_active_models_receive_new_collections(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);old=initial_state()
            for key in native.EXTRA_COLLECTIONS:old.pop(key)
            old.pop('core_options')
            store.set('state',old);store.set('active',old)
            for key in ('state','active'):
                model=store.get(key)
                self.assertEqual(model['core_options'],{})
                self.assertTrue(all(name in model for name in native.EXTRA_COLLECTIONS))

    def test_nested_rule_references_and_outbound_cycles_are_rejected(self):
        state=initial_state()
        state['route_rules']=[row({'type':'logical','mode':'or','rules':[{'domain_suffix':['example.com']}], 'action':'route','outbound':'missing'})]
        with self.assertRaisesRegex(ValueError,'Unknown outbound'):
            build_config(state,{},Path('/tmp'))
        state['route_rules']=[]
        state['dns_rules']=[row({'type':'logical','mode':'and','rules':[{'query_type':['A']}], 'action':'route','server':'missing'})]
        with self.assertRaisesRegex(ValueError,'Unknown dns server'):
            build_config(state,{},Path('/tmp'))
        state['dns_rules']=[]
        state['outbounds']=[row({'type':'selector','tag':'a','outbounds':['b']},'a'),row({'type':'selector','tag':'b','outbounds':['a']},'b')]
        with self.assertRaisesRegex(ValueError,'dependency cycle'):
            build_config(state,{},Path('/tmp'))
        state['outbounds']=[]
        state['rule_sets']=[row({'type':'inline','tag':'loop','rules':[{'rule_set':['loop']}]})]
        with self.assertRaisesRegex(ValueError,'Rule set dependency cycle'):
            build_config(state,{},Path('/tmp'))

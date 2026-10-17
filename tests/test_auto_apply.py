"""Exercise saves through the HTTP API against the real local Sing-box core."""
import copy
import socket
import unittest
from unittest import mock
from nara.server import self_signed
from tests import test_api
from tests.test_core import CORE
from tests.helpers import example_state, free_port


@unittest.skipUnless(CORE, "Set SING_BOX_TEST_BINARY for auto-apply integration")
class AutoApplyTests(unittest.TestCase):
    real_core = True
    web_path = ""
    request = test_api.APITests.request
    login = test_api.APITests.login
    subscription_request = test_api.APITests.subscription_request

    def setUp(self):
        test_api.APITests.setUp(self)
        self.runtime.binary = CORE
        self.runtime.stats_port = free_port()
        self.login()

    def tearDown(self):
        self.runtime.shutdown.set()
        self.runtime.stop()
        test_api.APITests.tearDown(self)

    def seed(self):
        state = example_state("vless", self_signed({"server_name": "127.0.0.1", "days": 1}))
        self.runtime.apply(state, save=True)
        return state

    def test_complete_dns_and_routing_save_without_apply_and_invalid_route_rolls_back(self):
        state = self.seed()
        result = self.request('/api/core-options', {'revision': state['revision'], 'section': 'dns',
                              'options': {'timeout': '3s', 'cache_capacity': 2048}, 'default_resolver': 'bootstrap'})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        rule = {'action': 'reject', 'domain_suffix': ['blocked.example.com']}
        result = self.save(state, 'route_rules', {'config': rule})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        import json
        config = json.loads((self.runtime.generation/'config.json').read_text())
        self.assertEqual(config['dns']['cache_capacity'], 2048)
        self.assertEqual(config['route']['rules'][-1], rule)
        result = self.save(state, 'route_rules', {'config': {'domain_suffix': ['example.com'], 'action': 'route', 'outbound': 'missing-outbound'}})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get('state'), state)
        self.assertEqual(self.runtime.active, state)
        self.assertTrue(self.runtime.running)

    def test_guided_routing_workflow_applies_order_toggle_sets_and_defaults_to_real_core(self):
        import json
        state = self.seed()
        inbound = state['inbounds'][0]['tag']
        steps = [
            ('outbounds', {'type':'socks', 'tag':'upstream', 'server':'127.0.0.1', 'server_port':19080}),
            ('rule_sets', {'type':'inline', 'tag':'domains', 'rules':[{'domain_suffix':['example.org']}]}),
            ('route_rules', {'rule_set':['domains'], 'inbound':[inbound], 'network':['tcp'], 'action':'route', 'outbound':'upstream'}),
            ('route_rules', {'port':[53], 'action':'hijack-dns'}),
            ('route_rules', {'action':'sniff'}),
            ('route_rules', {'source_ip_cidr':['127.0.0.0/8'], 'port_range':['8000:9000'], 'action':'reject'}),
        ]
        for collection, config in steps:
            result = self.save(state, collection, {'mode':'native', 'config':config})
            self.assertEqual(result[0], 200, result[1])
            state = self.store.get('state')
            self.assertEqual(self.runtime.active, state)
            self.assertTrue(self.runtime.running)
        rules = state['route_rules']
        result = self.request('/api/reorder-rules', {'revision':state['revision'], 'collection':'route_rules',
                              'id':rules[0]['id'], 'direction':'down'})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        self.assertEqual(state['route_rules'][0]['id'], rules[1]['id'])
        result = self.save(state, 'route_rules', {**state['route_rules'][1], 'enabled':False})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        result = self.request('/api/core-options', {'revision':state['revision'], 'section':'route',
                              'options':{'final':'upstream', 'default_domain_resolver':{'server':'bootstrap', 'strategy':'ipv4_only'}}})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        config = json.loads((self.runtime.generation/'config.json').read_text())
        self.assertEqual(config['route']['rules'][0]['action'], 'hijack-dns')
        self.assertEqual(config['route']['rules'][1], {'ip_is_private':True, 'action':'reject'})
        self.assertEqual(config['route']['rules'][2:], [steps[i][1] for i in (3,4,5)])
        self.assertEqual(config['route']['final'], 'upstream')
        self.assertEqual(self.runtime.active, state)
        self.assertTrue(self.runtime.running)
        # Deleting the default destination must not disrupt active traffic.
        result = self.request('/api/delete', {'revision':state['revision'], 'collection':'outbounds', 'id':state['outbounds'][0]['id']})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get('state'), state)
        self.assertEqual(self.runtime.active, state)

    def test_warp_registration_applies_and_is_used_by_dns_and_traffic_rules(self):
        import json
        from nara import warp
        from tests.test_warp import registration
        state=self.seed()
        endpoint=warp.endpoint
        def local_endpoint(response,private):
            config=endpoint(response,private)
            config['peers'][0].update(address='127.0.0.1',port=free_port())
            return config
        with mock.patch('nara.warp.register',return_value=registration()) as register, mock.patch('nara.warp.endpoint',side_effect=local_endpoint):
            result=self.request('/api/warp',{'revision':state['revision'],'accept_terms':True})
        self.assertEqual(result[0],200,result[1]);register.assert_called_once()
        state=self.store.get('state');tag=result[1]['tag']
        self.assertTrue(self.runtime.running)
        self.assertEqual(state['endpoints'][0]['config']['peers'][0]['reserved'],[1,2,255])
        result=self.save(state,'route_rules',{'mode':'native','config':{'domain_suffix':['example.com'],'action':'route','outbound':tag}})
        self.assertEqual(result[0],200,result[1]);state=self.store.get('state')
        result=self.save(state,'dns_servers',{'mode':'native','config':{'type':'udp','tag':'via-warp','server':'1.1.1.1','server_port':53,'detour':tag}})
        self.assertEqual(result[0],200,result[1]);state=self.store.get('state')
        result=self.save(state,'dns_rules',{'mode':'native','config':{'domain_suffix':['example.com'],'action':'route','server':'via-warp','disable_cache':True}})
        self.assertEqual(result[0],200,result[1]);state=self.store.get('state')
        config=json.loads((self.runtime.generation/'config.json').read_text())
        self.assertEqual(config['route']['rules'][-1]['outbound'],tag)
        self.assertEqual(config['dns']['servers'][-1]['detour'],tag)
        self.assertEqual(config['dns']['rules'][-1]['server'],'via-warp')
        self.assertNotIn('private_key',self.request('/api/state')[1]['endpoints'][0]['config'])
        # Referenced endpoints cannot be removed and disrupt live traffic.
        result=self.request('/api/delete',{'revision':state['revision'],'collection':'endpoints','id':state['endpoints'][0]['id']})
        self.assertEqual(result[0],400);self.assertEqual(self.store.get('state'),state)
        self.assertTrue(self.runtime.running)

    def test_bulk_client_changes_reset_counters_once_and_invalid_batch_rolls_back(self):
        import json
        state=self.seed()
        status,result,_=self.request('/api/clients-bulk-create',{'revision':state['revision'],'count':3,
            'pattern':'Team-{n:03}','defaults':{'inbound_ids':[state['inbounds'][0]['id']],'quota_bytes':1073741824}})
        self.assertEqual(status,200,result);state=self.store.get('state');ids=result['ids']
        config=json.loads((self.runtime.generation/'config.json').read_text())
        self.assertEqual(len(config['inbounds'][0]['users']),4)
        for ident in ids:self.store.add_traffic([(ident,'download',500)])
        status,result,_=self.request('/api/clients-bulk-action',{'revision':state['revision'],'ids':ids,'operation':'reset_traffic'})
        self.assertEqual(status,200,result);state=self.store.get('state')
        self.assertTrue(all(ident not in self.store.totals() for ident in ids));self.assertTrue(self.runtime.running)
        status,result,_=self.request('/api/clients-bulk-action',{'revision':state['revision'],'ids':ids,'operation':'inbounds_set','value':['missing']})
        self.assertEqual(status,400,result);self.assertEqual(self.store.get('state'),state)
        status,result,_=self.request('/api/clients-bulk-action',{'revision':state['revision'],'ids':ids,'operation':'disable'})
        self.assertEqual(status,200,result)
        config=json.loads((self.runtime.generation/'config.json').read_text());self.assertEqual(len(config['inbounds'][0]['users']),1)
        self.assertTrue(self.runtime.running)

    def test_rest_client_create_and_invalid_dns_update_use_real_core_validation(self):
        import http.client
        from nara import api_keys
        state=self.seed();key=api_keys.create(self.store,{'name':'Fixture','scopes':['read','clients:write','config:write'],'days':1})['key']
        def call(path,body):
            import json
            connection=http.client.HTTPConnection(*self.server.server_address,timeout=15)
            connection.request('POST','/api/v1/'+path,json.dumps(body),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            response=connection.getresponse();status=response.status;data=json.loads(response.read());connection.close();return status,data
        status,result=call('clients',{'revision':state['revision'],'inbound_ids':[state['inbounds'][0]['id']]})
        self.assertEqual(status,201,result);state=self.store.get('state');self.assertTrue(self.runtime.running)
        status,result=call('dns/servers',{'revision':state['revision'],'config':{'type':'udp','tag':'invalid','server':'8.8.8.8','server_port':70000}})
        self.assertEqual(status,400,result);self.assertEqual(self.store.get('state'),state);self.assertTrue(self.runtime.running)

    def save(self, state, collection, record):
        return self.request("/api/save", {"revision": state["revision"], "collection": collection, "record": record})

    def test_new_hostname_dns_resolver_saves_with_bootstrap_and_explains_missing_fields(self):
        state = self.seed()
        config = {'type':'https', 'tag':'google', 'server':'dns.google'}
        result = self.save(state, 'dns_servers', {'mode':'native', 'tag':'google', 'config':config})
        self.assertEqual(result[0], 400, result[1])
        self.assertIn('bootstrap resolver', result[1]['error'])
        self.assertEqual(self.store.get('state'), state)
        self.assertTrue(self.runtime.running)
        config['domain_resolver'] = 'bootstrap'
        result = self.save(state, 'dns_servers', {'mode':'native', 'tag':'google', 'config':config})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        self.assertEqual(self.runtime.active, state)
        self.assertTrue(self.runtime.running)
        resolver = next(row for row in state['dns_servers'] if row['tag'] == 'google')
        config['server'] = 'https://dns.google/dns-query'
        result = self.save(state, 'dns_servers', {**resolver, 'config':config})
        self.assertEqual(result[0], 400, result[1])
        self.assertIn('without a scheme', result[1]['error'])
        self.assertEqual(self.store.get('state'), state)
        self.assertEqual(self.runtime.active, state)

    def test_delete_old_bootstrap_with_ip_dns_keeps_core_running_but_hostname_dependency_blocks(self):
        state = self.seed()
        for mode in ('native', 'legacy'):
            config = {'type':'https', 'tag':'google-'+mode, 'server':'8.8.8.8',
                      'domain_resolver':'bootstrap', 'tls':{'enabled':True,'server_name':'dns.google'}}
            record = {'id':'google-'+mode, 'mode':'native', 'type':'https', 'tag':config['tag'], 'config':config} if mode == 'native' else {'id':'google-'+mode, **config}
            state['dns_servers'].append(record)
        state['settings']['dns_final'] = 'google-native'
        # Simulate data saved by a version that auto-filled unused references.
        self.store.set('state', state)
        result = self.request('/api/delete', {'revision':state['revision'], 'collection':'dns_servers', 'id':'bootstrap'})
        self.assertEqual(result[0], 200, result[1])
        saved = self.store.get('state')
        self.assertEqual(len(saved['dns_servers']), 2)
        for record in saved['dns_servers']:
            self.assertNotIn('domain_resolver', record.get('config', record))
        self.assertEqual(self.runtime.active, saved)
        self.assertTrue(self.runtime.running)
        # A genuine hostname dependency must still prevent removal atomically.
        saved['dns_servers'].append({'id':'hostname', 'tag':'hostname', 'mode':'native', 'type':'https',
                                    'config':{'type':'https','tag':'hostname','server':'dns.google','domain_resolver':'google-native'}})
        self.runtime.apply(saved, save=True)
        result = self.request('/api/delete', {'revision':saved['revision'], 'collection':'dns_servers', 'id':'google-native'})
        self.assertEqual(result[0], 400, result[1])
        self.assertIn('separate configured', result[1]['error'])
        self.assertEqual(self.store.get('state'), saved)
        self.assertTrue(self.runtime.running)

    def test_google_udp_pasted_address_saves_without_bootstrap_in_native_and_legacy_forms(self):
        state = self.seed()
        for mode in ('native', 'legacy'):
            with self.subTest(mode=mode):
                tag = 'google-' + mode
                config = {'type':'udp', 'tag':tag, 'server':' \t8.8.8.8\r\n', 'server_port':53}
                record = {'mode':'native', 'config':config} if mode == 'native' else {'type':'udp', 'tag':tag, 'server':config['server'], 'port':53}
                result = self.save(state, 'dns_servers', record)
                self.assertEqual(result[0], 200, result[1])
                state = self.store.get('state')
                row = next(row for row in state['dns_servers'] if row['tag'] == tag)
                saved = row['config'] if mode == 'native' else row
                self.assertEqual(saved['server'], '8.8.8.8')
                self.assertNotIn('domain_resolver', saved)
                self.assertEqual(self.runtime.active, state)
                self.assertTrue(self.runtime.running)

    def test_saving_client_starts_listener_without_apply_request(self):
        state = self.seed()
        record = {**state["clients"][0], "enabled": False}
        result = self.save(state, "clients", record)
        self.assertEqual(result[0], 200, result[1])
        self.assertEqual(self.runtime.active, self.store.get("state"))
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1)
        state = self.store.get("state")
        result = self.save(state, "clients", {**record, "enabled": True})
        self.assertEqual(result[0], 200, result[1])
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass

    def test_failed_bind_keeps_saved_and_active_state(self):
        state = self.seed()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            result = self.save(state, "inbounds", {**state["inbounds"][0], "port": occupied.getsockname()[1]})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertEqual(self.runtime.active, state)
        self.assertEqual(self.store.get("active"), state)
        self.assertTrue(self.runtime.running)

    def test_metadata_and_token_changes_do_not_restart_core(self):
        state = self.seed()
        process = self.runtime.process.pid
        for path, payload in (("rotate-token", {"id": "user1"}),
                              ("settings", {"settings": {**state["settings"], "public_url": "https://panel.example.com/AbCdEfGh/"}})):
            current = self.store.get("state")
            result = self.request("/api/" + path, {"revision": current["revision"], **payload})
            self.assertEqual(result[0], 200, result[1])
            self.assertFalse(result[1]["restarted"])
            self.assertEqual(self.runtime.process.pid, process)
            self.assertEqual(self.runtime.active, self.store.get("state"))
        old_token = state["clients"][0]["token"]
        self.assertEqual(self.subscription_request(old_token)[0], 404)

    def test_invalid_unassigned_inbound_is_not_saved(self):
        state = self.store.get("state")
        result = self.save(state, "inbounds", {"tag": "bad", "type": "vless", "port": free_port(),
            "listen": "127.0.0.1", "enabled": False, "transport": "ws", "path": "/",
            "transport_options": {"early_data_header_name": "\r\nInjected"}})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertFalse(self.runtime.running)

    def test_failed_usage_reset_preserves_usage_and_account_limits(self):
        state = self.seed()
        self.store.add_traffic([("user1", "download", 1234)])
        with mock.patch.object(self.runtime, "launch", side_effect=ValueError("Simulated startup failure")):
            result = self.request("/api/reset-traffic", {"revision": state["revision"], "id": "user1"})
        self.assertEqual(result[0], 400)
        self.assertEqual(self.store.totals()["user1"]["download"], 1234)
        self.assertEqual(self.store.get("state"), state)

    def test_usage_reset_reactivates_exhausted_account_automatically(self):
        state = self.seed()
        state["clients"][0]["quota_bytes"] = 100
        self.store.add_traffic([("user1", "download", 200)])
        self.runtime.apply(state, save=True)
        self.assertEqual(self.runtime.active["clients"][0]["quota_bytes"], 100)
        result = self.request("/api/reset-traffic", {"revision": state["revision"], "id": "user1"})
        self.assertEqual(result[0], 200, result[1])
        self.assertEqual(self.store.totals().get("user1", {}).get("download", 0), 0)
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass

    def test_certificate_generation_applies_insecure_to_exports_only(self):
        state = self.seed()
        profile = copy.deepcopy(state["tls"][0])
        profile["insecure"] = True
        result = self.save(state, "tls", profile)
        self.assertEqual(result[0], 200, result[1])
        token = state["clients"][0]["token"]
        result = self.subscription_request(token)
        self.assertEqual(result[0], 200, result[1])
        self.assertTrue(result[1]["outbounds"][1]["tls"]["insecure"])
        import json
        server = json.loads((self.runtime.generation / "config.json").read_text())
        self.assertNotIn("insecure", server["inbounds"][0]["tls"])

    def test_missing_core_does_not_save_a_draft(self):
        state = self.store.get("state")
        self.runtime.binary = "/nonexistent"
        result = self.request("/api/settings", {"revision": 0, "settings": state["settings"]})
        self.assertEqual(result[0], 400)
        self.assertEqual(self.store.get("state"), state)

    def test_persistence_failure_restores_previous_core_and_model(self):
        state = self.seed()
        with mock.patch.object(self.store, "commit_configuration", side_effect=OSError("Simulated persistence failure")):
            result = self.save(state, "inbounds", {**state["inbounds"][0], "port": free_port()})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertEqual(self.store.get("active"), state)
        self.assertEqual(self.runtime.active, state)
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass

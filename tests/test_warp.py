import base64
import copy
import io
import json
import os
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from nara import warp, native
from tests import test_api

PRIVATE = base64.b64encode(bytes(range(32))).decode()
PUBLIC = base64.b64encode(bytes(range(1, 33))).decode()


def registration():
    return {'token': 'PRIVATE-API-TOKEN', 'account': {'license': 'PRIVATE-LICENSE'}, 'tunnel_type': 'wireguard',
            'config': {'client_id': base64.b64encode(b'\x01\x02\xff').decode(),
                       'interface': {'addresses': {'v4': '172.16.0.2', 'v6': '2606:4700:110::1234'}},
                       'peers': [{'public_key': PUBLIC, 'endpoint': {'v4': '162.159.192.1', 'ports': [2408]}}]}}


class WarpTests(unittest.TestCase):
    def test_response_converts_to_user_space_endpoint_without_tokens(self):
        config = warp.endpoint(registration(), PRIVATE)
        self.assertFalse(config['system'])
        self.assertEqual(config['address'], ['172.16.0.2/32', '2606:4700:110::1234/128'])
        self.assertEqual(config['peers'][0]['reserved'], [1, 2, 255])
        self.assertEqual(config['peers'][0]['allowed_ips'], ['0.0.0.0/0', '::/0'])
        self.assertEqual(config['peers'][0]['port'], 2408)
        self.assertNotIn('PRIVATE-API-TOKEN', json.dumps(config))
        self.assertNotIn('PRIVATE-LICENSE', json.dumps(config))
        self.assertNotIn('private_key', native.redact(config))

    def test_response_accepts_legacy_ip_port_and_ipv6_endpoint(self):
        for value, expected in [('162.159.192.1:500', ('162.159.192.1', 500)),
                                ('162.159.192.1:0', ('162.159.192.1', 2408)),
                                ('[2606:4700:d0::a29f:c001]:2408', ('2606:4700:d0::a29f:c001', 2408))]:
            response = registration()
            response['config']['peers'][0]['endpoint'] = {'v6': value}
            peer = warp.endpoint(response, PRIVATE)['peers'][0]
            self.assertEqual((peer['address'], peer['port']), expected)

    def test_unusable_registration_is_rejected_without_echoing_secrets(self):
        cases = [None, [], {}, {'config': {}}]
        for change in [lambda r: r['config'].update(client_id='bad'),
                       lambda r: r['config']['peers'][0].update(public_key='PRIVATE-API-TOKEN'),
                       lambda r: r['config']['interface'].update(addresses={'v4':'127.0.0.1'}),
                       lambda r: r['config']['peers'][0]['endpoint'].update(v4='127.0.0.1'),
                       lambda r: r['config']['peers'][0]['endpoint'].update(ports=[70000]),
                       lambda r: r['config']['peers'][0]['endpoint'].update(ports='2408'),
                       lambda r: r['config']['peers'][0]['endpoint'].update(ports=[2408.5]),
                       lambda r: r['config']['peers'][0]['endpoint'].update(ports=[True]),
                       lambda r: r.update(tunnel_type='masque')]:
            response = registration(); change(response); cases.append(response)
        for response in cases:
            with self.subTest(kind=type(response).__name__), self.assertRaisesRegex(ValueError, 'usable WireGuard'):
                warp.endpoint(response, PRIVATE)

    def test_registration_uses_fixed_https_public_key_only_and_no_redirects(self):
        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(registration()).encode()
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(warp.request, 'build_opener', return_value=opener) as build:
            self.assertEqual(warp.register(PUBLIC), registration())
        req = opener.open.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, warp.API_URL)
        self.assertEqual(body['key'], PUBLIC)
        self.assertEqual(body['tunnel_type'], 'wireguard')
        self.assertNotIn(PRIVATE, req.data.decode())
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 20)
        self.assertTrue(any(isinstance(x, warp.NoRedirect) for x in build.call_args.args))
        self.assertIsNone(warp.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_registration_failure_is_bounded_and_actionable(self):
        for code in (403,429,500):
            opener = mock.Mock()
            opener.open.side_effect = HTTPError(warp.API_URL, code, 'SECRET-BODY', {}, io.BytesIO(b'SECRET-BODY'))
            with mock.patch.object(warp.request, 'build_opener', return_value=opener):
                with self.assertRaises(ValueError) as raised: warp.register(PUBLIC)
            self.assertNotIn('SECRET-BODY', str(raised.exception))
            self.assertEqual(opener.open.call_count, 1)
        response = mock.MagicMock(status=200); response.__enter__.return_value=response
        for raw in (b'no json', b'x'*(warp.MAX_RESPONSE+1)):
            response.read.return_value = raw
            opener = mock.Mock(); opener.open.return_value=response
            with mock.patch.object(warp.request, 'build_opener', return_value=opener), self.assertRaises(ValueError):
                warp.register(PUBLIC)
        opener.open.side_effect=URLError('secret detail')
        with mock.patch.object(warp.request, 'build_opener', return_value=opener), self.assertRaisesRegex(ValueError, 'outbound HTTPS'):
            warp.register(PUBLIC)

    @unittest.skipUnless(os.environ.get('SING_BOX_TEST_BINARY'), 'real core required')
    def test_real_core_generates_wireguard_keys(self):
        private, public = warp.keypair(os.environ['SING_BOX_TEST_BINARY'])
        self.assertEqual(len(warp.decode_key(private)), 32)
        self.assertEqual(len(warp.decode_key(public)), 32)
        self.assertNotEqual(private, public)


class WarpAPITests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    tearDown = test_api.APITests.tearDown
    request = test_api.APITests.request
    login = test_api.APITests.login
    web_path = ''

    def test_auth_consent_revision_and_capability_precede_registration(self):
        with mock.patch('nara.warp.create') as create:
            self.assertEqual(self.request('/api/warp', {'accept_terms':True,'revision':0})[0],401)
            self.login()
            self.assertEqual(self.request('/api/warp', {'accept_terms':True,'revision':0},{'X-CSRF-Token':'wrong'})[0],403)
            for body in ({'revision':0},{'accept_terms':'yes','revision':0},{'accept_terms':True,'revision':900},{'accept_terms':True,'revision':0}):
                self.assertEqual(self.request('/api/warp',body)[0],400)
            create.assert_not_called()

    def test_registration_is_applied_as_destination_and_keys_stay_private(self):
        self.login(); before=self.store.get('state')
        config=warp.endpoint(registration(),PRIVATE)
        with mock.patch.object(self.runtime,'build_info',return_value={'tags':['with_wireguard']}), mock.patch('nara.warp.create',return_value=config) as create:
            status,result,_=self.request('/api/warp',{'accept_terms':True,'revision':0})
            self.assertEqual(status,200,result)
            self.assertEqual(result['tag'],'warp')
            current=self.store.get('state'); row=current['endpoints'][0]
            self.assertEqual(row['config']['private_key'],PRIVATE)
            self.assertEqual(current['core_options'],before['core_options'])
            self.assertEqual(current['route_rules'],before['route_rules'])
            self.assertEqual(current['settings'],before['settings'])
            visible=self.request('/api/state')[1]
            self.assertNotIn(PRIVATE,json.dumps(visible))
            self.assertIsNone(self.store.get('warp_pending'))
            self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':0})[0],400)
            self.assertEqual(create.call_count,1)
            self.assertNotIn(PRIVATE,json.dumps(self.store.events()))

    def test_failed_apply_keeps_state_and_reuses_registration_on_retry(self):
        self.login(); before=self.store.get('state'); config=warp.endpoint(registration(),PRIVATE)
        apply=self.runtime.apply
        with mock.patch.object(self.runtime,'build_info',return_value={'tags':['with_wireguard']}), mock.patch('nara.warp.create',return_value=config) as create:
            with mock.patch.object(self.runtime,'apply',side_effect=ValueError('Core validation failed')):
                self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':0})[0],400)
            self.assertEqual(self.store.get('state'),before)
            self.assertEqual(self.store.get('warp_pending')['config'],config)
            self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':0})[0],200)
            self.assertEqual(create.call_count,1)

    def test_destination_tag_avoids_conflicts_and_references_work(self):
        from nara.config import validate, build_config
        state=self.store.get('state')
        state['outbounds']=[{'id':'existing','mode':'native','tag':'warp','config':{'type':'direct','tag':'warp'}}]
        row=warp.record(warp.endpoint(registration(),PRIVATE),state)
        self.assertEqual(row['tag'],'warp-2'); state['endpoints']=[row]
        state['route_rules']=[{'id':'route','mode':'native','config':{'domain_suffix':['example.com'],'action':'route','outbound':'warp-2'}}]
        validate(state)
        config=build_config(state,{},self.runtime.run_dir,self.runtime.stats_port)
        self.assertEqual(config['route']['rules'][-1]['outbound'],'warp-2')

    def test_concurrent_edit_keeps_registration_for_a_revision_checked_retry(self):
        self.login(); config=warp.endpoint(registration(),PRIVATE)
        def register(binary):
            # A second creation cannot race or register another device.
            self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':0})[0],400)
            state=self.store.get('state');state['revision']=1;self.store.set('state',state)
            return config
        with mock.patch.object(self.runtime,'build_info',return_value={'tags':['with_wireguard']}), mock.patch('nara.warp.create',side_effect=register) as create:
            status,result,_=self.request('/api/warp',{'accept_terms':True,'revision':0})
            self.assertEqual(status,400);self.assertIn('refresh and retry',result['error'])
            self.assertEqual(self.store.get('state')['endpoints'],[])
            self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':1})[0],200)
            self.assertEqual(create.call_count,1)

    def test_completed_pending_record_is_not_duplicated_after_interrupted_cleanup(self):
        self.login();state=self.store.get('state');config=warp.endpoint(registration(),PRIVATE)
        row=warp.record(config,state);state['endpoints']=[row];state['revision']=1
        self.store.set('state',state);self.store.set('warp_pending',{'id':row['id'],'config':config})
        with mock.patch.object(self.runtime,'build_info',return_value={'tags':['with_wireguard']}), mock.patch('nara.warp.create') as create:
            self.assertEqual(self.request('/api/warp',{'accept_terms':True,'revision':1})[0],200)
            self.assertEqual(len(self.store.get('state')['endpoints']),1);create.assert_not_called()

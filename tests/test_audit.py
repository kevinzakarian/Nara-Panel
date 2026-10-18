"""Regression coverage for findings from the cross-panel security/resource review."""
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from nara import api_keys, notifications
from nara.http import BoundedHTTPServer
from nara.network import HTTPSRedirect, open_https
from nara.runtime import Runtime, atomic_write
from nara.server import make_handler
from nara.store import Store
from tests import test_api, test_rest
from tests.helpers import example_state


class ReviewAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;request=test_api.APITests.request;login=test_api.APITests.login;subscription_request=test_api.APITests.subscription_request;web_path=''

    def test_bot_connection_checks_require_current_password_and_do_not_save_or_send(self):
        self.login();token='123456:FIXTURE_TELEGRAM_TOKEN_ONLY';before=notifications.settings(self.store)
        for route in ('check','chats'):
            with mock.patch('nara.notifications.call') as call:
                status,value,_=self.request('/api/telegram/'+route,{'bot_token':token})
                self.assertEqual(status,400);call.assert_not_called()
        with mock.patch('nara.notifications.call',return_value={'is_bot':True,'username':'fixture_bot','first_name':'Fixture','token':'PRIVATE'}) as call:
            status,value,_=self.request('/api/telegram/check',{'current':'test-password-123','bot_token':token})
            self.assertEqual(status,200,value);self.assertEqual(value,{'bot':{'username':'fixture_bot','name':'Fixture'}})
            self.assertEqual(call.call_args.args,(token,'getMe',{}))
        self.assertEqual(notifications.settings(self.store),before)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)
        with mock.patch('nara.notifications.chats',return_value=[{'id':'123','name':'Fixture'}]) as chats:
            status,value,_=self.request('/api/telegram/chats',{'current':'test-password-123','bot_token':token})
            self.assertEqual(status,200,value);chats.assert_called_once_with(token)

    def test_bot_check_can_use_saved_token_without_changing_enabled_state(self):
        self.login();value=notifications.settings(self.store);value['bot_token']='123456:SAVED_FIXTURE_TELEGRAM_TOKEN';self.store.set('telegram',value)
        with mock.patch('nara.notifications.bot_info',return_value={'username':'saved_bot','name':'Saved'}) as check:
            self.assertEqual(self.request('/api/telegram/check',{'current':'test-password-123','bot_token':''})[0],200)
            check.assert_called_once_with(value['bot_token'])
        self.assertFalse(notifications.settings(self.store)['enabled'])

    def test_subscription_accepts_existing_long_tokens_and_rejects_malformed_paths(self):
        import copy
        state=example_state();state['clients'][0]['token']='A'*128
        self.store.set('state',state);self.runtime.active=copy.deepcopy(state)
        self.assertEqual(self.subscription_request('A'*128)[0],200)
        self.assertEqual(self.subscription_request('A'*129)[0],404)
        self.assertEqual(self.subscription_request('invalid-token')[0],404)

    def test_nonfinite_json_and_duplicate_length_are_rejected_before_mutation(self):
        self.login();before=self.store.get('state')
        self.assertEqual(self.request('/api/settings',{'revision':float('nan')})[0],400)
        c=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        payload=b'{}';c.putrequest('POST','/api/settings');c.putheader('Cookie',self.cookie);c.putheader('X-CSRF-Token',self.csrf);c.putheader('Content-Type','application/json');c.putheader('Content-Length','2');c.putheader('Content-Length','2');c.endheaders(payload)
        response=c.getresponse();self.assertEqual(response.status,400);response.read();c.close()
        self.assertEqual(self.store.get('state'),before)


class OperationAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;login=test_api.APITests.login;request=test_api.APITests.request;key=test_rest.RestTests.key;call=test_rest.RestTests.call;web_path=''
    # Only the new regression runs here; existing REST coverage remains in its module.
    def test_read_only_keys_cannot_read_native_service_credentials(self):
        from nara import rest
        secret_names=('account_key','auth_key','client_key','client_key_password','private_key_passphrase','mca_key','mca_key_password','origin_ca_key','static_key','submission_key','userkey','security_token','zone_token')
        state=example_state();state['endpoints']=[{'id':'fixture','tag':'tailscale','mode':'native','config':{'type':'tailscale','tag':'tailscale','auth_key':'PRIVATE_FIXTURE'}}]
        state['core_options']={'certificate':{name:'PRIVATE_FIXTURE' for name in secret_names}}
        self.store.set('state',state)
        status,value,_=self.call('GET','state',key=self.key(['read']));self.assertEqual(status,200,value);self.assertNotIn('PRIVATE_FIXTURE',json.dumps(value))
        status,value,_=self.call('GET','state',key=self.key(['read','secrets:read']));self.assertEqual(status,200,value);self.assertIn('PRIVATE_FIXTURE',json.dumps(value))
        public={'public_key':'PUBLIC','host_key':'PUBLIC','key_id':'identifier','certificate_authority':['PUBLIC']}
        self.assertEqual(rest.visible(public),public)

    def test_operation_status_accepts_the_actual_urlsafe_job_id_format(self):
        key=self.key(['read']);ident='ABcd_ef-GHijkLmnoPqrStuVwxyz0123'
        self.assertEqual(len(ident),32)
        self.runtime.active=None
        (self.store.directory/'access-result.json').write_text(json.dumps({'id':ident,'status':'complete'}))
        status,result,_=self.call('GET','operations/'+ident,key=key)
        self.assertEqual(status,200,result);self.assertEqual(result['data']['status'],'complete')



class ReviewResourceTests(unittest.TestCase):
    def test_atomic_write_ignores_predictable_symlinks_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);victim=root/'other';victim.write_text('keep');target=root/'config.json';(root/'config.json.tmp').symlink_to(victim)
            atomic_write(target,'private');self.assertEqual(target.read_text(),'private');self.assertEqual(victim.read_text(),'keep');self.assertEqual(target.stat().st_mode&0o777,0o600)
            self.assertFalse(list(root.glob('.config.json-*')))

    def test_api_key_last_used_writes_at_most_once_a_minute(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);raw=api_keys.create(store,{'name':'Fixture','scopes':['read']})['key']
            with mock.patch('nara.api_keys.time.time',return_value=time.time()+1):api_keys.authenticate(store,'Bearer '+raw)
            before=api_keys.listing(store)[0]['last_used']
            with mock.patch('nara.api_keys.time.time',return_value=before+10):api_keys.authenticate(store,'Bearer '+raw)
            self.assertEqual(api_keys.listing(store)[0]['last_used'],before)
            with mock.patch('nara.api_keys.time.time',return_value=before+61):api_keys.authenticate(store,'Bearer '+raw)
            self.assertEqual(api_keys.listing(store)[0]['last_used'],before+61)

    def test_idle_limit_checks_do_not_build_or_read_core_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);state=example_state();runtime=Runtime(store);runtime.active=state;runtime.generation=Path(temp)/'no-read';runtime._eligible_clients=frozenset(['client-user1'])
            with mock.patch('nara.runtime.build_config') as build,mock.patch.object(runtime,'apply') as apply:
                runtime.enforce_limits();build.assert_not_called();apply.assert_not_called()
                store.add_traffic([('user1','download',state['clients'][0]['quota_bytes'] or 1000)])
                state['clients'][0]['quota_bytes']=1000;runtime.enforce_limits();apply.assert_called_once_with(state)

    def test_unexpected_limit_check_failure_stops_core_instead_of_killing_the_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);runtime=Runtime(store);runtime.process=mock.Mock();runtime.process.poll.return_value=None
            with mock.patch.object(runtime.shutdown,'wait',side_effect=[False,True]),mock.patch.object(runtime,'collect'),mock.patch.object(runtime,'enforce_limits',side_effect=OSError('fixture storage failure')),mock.patch.object(runtime,'stop') as stop:
                runtime.worker();stop.assert_called_once_with(collect=False)
            self.assertIn('account limits could not be verified',runtime.error)

    def test_idle_notification_worker_waits_and_new_events_wake_it(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);runtime=mock.Mock(shutdown=threading.Event());worker=notifications.Worker(store,runtime)
            wake=store.notification_wakeup
            with mock.patch.object(wake,'wait',side_effect=lambda delay:runtime.shutdown.set()) as wait,mock.patch.object(worker,'deliver') as deliver:
                worker.run();wait.assert_called_once_with(30);deliver.assert_not_called()
            value=notifications.settings(store);value.update(enabled=True,bot_token='123456:FIXTURE_TOKEN_ONLY',chat_id='123');store.set('telegram',value)
            self.assertTrue(notifications.enqueue(store,'login','Fixture'));self.assertTrue(wake.is_set())

    def test_release_downloads_refuse_non_https_and_redirect_downgrades(self):
        from urllib.request import Request
        for url in ('file:///etc/passwd','http://example.com/release'):
            with self.assertRaises(ValueError):open_https(url,1)
        with self.assertRaises(ValueError):HTTPSRedirect().redirect_request(Request('https://example.com'),None,302,'Found',{},'http://example.com/release')

    def test_http_listener_caps_connections_and_times_out_idle_sockets(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);runtime=Runtime(store);handler=make_handler(store,runtime,Path('web'))
            server=BoundedHTTPServer(('127.0.0.1',0),handler);server.slots=threading.BoundedSemaphore(1);server.socket_timeout=.2
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            first=socket.create_connection(server.server_address,timeout=2)
            try:
                deadline=time.monotonic()+2
                while server.slots.acquire(blocking=False):
                    server.slots.release()
                    if time.monotonic()>deadline:self.fail('No first handler')
                    time.sleep(.005)
                second=socket.create_connection(server.server_address,timeout=2);second.settimeout(2)
                response=second.recv(4096);second.close()
                self.assertIn(b'503 Service Unavailable',response)
                self.assertEqual(json.loads(response.split(b'\r\n\r\n',1)[1])['error'],'The panel is busy. Wait a moment and try again.')
                first.settimeout(2);self.assertEqual(first.recv(1),b'')
                time.sleep(.03)
                c=http.client.HTTPConnection(*server.server_address,timeout=2);c.request('GET','/api/health');r=c.getresponse();self.assertEqual(r.status,200);r.read();c.close()
            finally:first.close();server.shutdown();server.server_close()


class DisconnectTests(unittest.TestCase):
    def test_listener_ignores_expected_disconnects_but_reports_other_handler_errors(self):
        server=BoundedHTTPServer(('127.0.0.1',0),lambda *args:None)
        try:
            with mock.patch('http.server.ThreadingHTTPServer.handle_error') as fallback:
                for error in (ConnectionResetError(),BrokenPipeError(),TimeoutError()):
                    with mock.patch('nara.http.sys.exc_info',return_value=(type(error),error,None)):
                        server.handle_error(None,('127.0.0.1',1))
                fallback.assert_not_called()
                error=RuntimeError('Fixture bug')
                with mock.patch('nara.http.sys.exc_info',return_value=(type(error),error,None)):
                    server.handle_error(None,('127.0.0.1',1))
                fallback.assert_called_once()
        finally:server.server_close()

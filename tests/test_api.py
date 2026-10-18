import copy
import http.client
import json
import tempfile
import threading
import time
import unittest
import ssl
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path
from nara.runtime import Runtime
from nara.config import validate
from nara.server import make_handler
from nara.store import Store, password_hash
from tests.helpers import example_state


class APITests(unittest.TestCase):
    web_path = ""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.set("admin", {"username": "admin", "password": password_hash("test-password-123")})
        self.runtime = Runtime(self.store, binary="/nonexistent")
        if not getattr(self, "real_core", False):
            def apply(state, persist=True, save=False, reset_client=None):
                validate(state)
                self.store.commit_configuration(state, save=save, reset_client=reset_client)
                self.runtime.active = copy.deepcopy(state)
                return {"running": True, "restarted": False}
            self.runtime.apply = mock.Mock(side_effect=apply)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, self.runtime, Path("web"), web_path=self.web_path))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.subserver = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.store, self.runtime, Path('web'), web_path='/Downloads', role='subscription'))
        self.subthread = threading.Thread(target=self.subserver.serve_forever, daemon=True)
        self.subthread.start()
        self.cookie = self.csrf = ""

    def tearDown(self):
        self.subserver.shutdown()
        self.subserver.server_close()
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=20)
        hdr = {"Cookie": self.cookie, "X-CSRF-Token": self.csrf}
        if body is not None:
            hdr["Content-Type"] = "application/json"
        hdr.update(headers or {})
        conn.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, hdr)
        resp = conn.getresponse()
        data = resp.read()
        status, response_headers = resp.status, dict(resp.getheaders())
        conn.close()
        try:
            data = json.loads(data)
        except ValueError:
            pass
        return status, data, response_headers

    def subscription_request(self, token, method='GET'):
        connection = http.client.HTTPConnection(*self.subserver.server_address, timeout=10)
        connection.request(method, '/Downloads/' + token, headers={'Cookie': self.cookie})
        response = connection.getresponse()
        data = response.read()
        result = response.status, json.loads(data), dict(response.getheaders())
        connection.close()
        return result

    def login(self):
        status, data, headers = self.request("/api/login", {"username": "admin", "password": "test-password-123"})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.csrf = data["csrf"]

    def test_api_requires_login(self):
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.request("/api/health")[0], 200)

    def test_login_cookie_and_csrf(self):
        self.login()
        self.assertEqual(self.request("/api/state")[0], 200)
        self.assertEqual(self.request("/api/stop", {}, {"X-CSRF-Token": "wrong"})[0], 403)

    def test_custom_administrator_username_is_used_for_sign_in_and_session(self):
        admin = self.store.get('admin')
        self.store.set('admin', {**admin, 'username':'PanelOwner_42'})
        self.assertEqual(self.request('/api/login', {'username':'admin', 'password':'test-password-123'})[0], 401)
        status, data, headers = self.request('/api/login', {'username':'PanelOwner_42', 'password':'test-password-123'})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/session')[1]['username'], 'PanelOwner_42')

    def test_cross_origin_login_rejected(self):
        self.assertEqual(self.request("/api/login", {"username": "admin", "password": "test-password-123"}, {"Origin": "https://evil.example"})[0], 400)

    def test_revision_conflict(self):
        self.login()
        state = self.store.get("state")
        self.assertEqual(self.request("/api/settings", {"revision": 0, "settings": state["settings"]})[0], 200)
        self.assertEqual(self.request("/api/settings", {"revision": 0, "settings": state["settings"]})[0], 400)

    def test_http_public_url_can_be_saved(self):
        self.login()
        state = self.store.get("state")
        state["settings"]["public_url"] = "http://203.0.113.42:10000" + self.web_path + "/"
        response = self.request("/api/settings", {"revision": 0, "settings": state["settings"]})
        self.assertEqual(response[0], 200, response[1])
        self.assertEqual(self.store.get("state")["settings"]["public_url"], state["settings"]["public_url"])

    def test_logout_revokes_session(self):
        self.login()
        self.assertEqual(self.request("/api/logout", {})[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_client_credentials_generated_on_server(self):
        self.login()
        record = dict(tag="test", type="vless", port=12345, listen="127.0.0.1", enabled=True)
        self.assertEqual(self.request("/api/save", {"revision": 0, "collection": "inbounds", "record": record})[0], 200)
        inbound = self.store.get("state")["inbounds"][0]
        record = dict(name="Alice", quota_bytes=1000, expires_at="", inbound_ids=[inbound["id"]], enabled=True)
        self.assertEqual(self.request("/api/save", {"revision": 1, "collection": "clients", "record": record})[0], 200)
        client = self.store.get("state")["clients"][0]
        self.assertGreaterEqual(len(client["token"]), 32)
        self.assertGreaterEqual(len(client["password"]), 12)
        # Deleting a referenced inbound must not corrupt saved state.
        self.assertEqual(self.request("/api/delete", {"revision": 2, "collection": "inbounds", "id": inbound["id"]})[0], 400)
        self.assertEqual(len(self.store.get("state")["inbounds"]), 1)

    def test_subscription_port_never_serves_panel_or_admin_api(self):
        for path in ('', 'api/state', 'api/login', 'app.js', 'index.html'):
            with self.subTest(path=path):
                self.assertEqual(self.subscription_request(path)[0], 404)
                self.assertEqual(self.subscription_request(path, 'POST')[0], 404)
        self.assertEqual(self.request('/sub/some-token')[0], 404)
        self.assertEqual(self.request('/Downloads/some-token')[0], 404)

    def test_access_settings_require_authentication(self):
        self.assertEqual(self.request('/api/access')[0], 401)
        self.login()
        status, info, _ = self.request('/api/access')
        self.assertEqual(status, 200)
        self.assertEqual(info['subscription_port'], 10001)
        self.assertNotEqual(info['sub_path'], info['web_path'])

    def test_private_key_not_exposed_in_state(self):
        self.login()
        response = self.request("/api/self-signed", {"revision": 0, "server_name": "127.0.0.1", "days": 1})
        self.assertEqual(response[0], 200, response[1])
        result = self.request("/api/state")[1]
        self.assertNotIn("private_key", result["tls"][0])

    def test_generate_certificate_for_domain_and_ip_on_modern_python(self):
        self.login()
        with mock.patch.object(ssl, "match_hostname", None, create=True):
            for revision, address in enumerate(("example.com", "127.0.0.1", "2001:db8::1")):
                with self.subTest(address=address):
                    response = self.request("/api/self-signed", {"revision": revision, "server_name": address, "days": 1})
                    self.assertEqual(response[0], 200, response[1])
        self.assertEqual(len(self.store.get("state")["tls"]), 3)

    def test_default_language_and_assets(self):
        status, data, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b'lang="en" dir="ltr"', data)
        self.assertIn("Content-Security-Policy", headers)
        for asset in ("/vendor/qrcodegen.js", "/subscription-qr.js", "/options.js"):
            self.assertIn(('src="' + asset.lstrip("/") + '"').encode(), data)
            status, script, asset_headers = self.request(asset)
            self.assertEqual(status, 200)
            self.assertIn("javascript", asset_headers["Content-Type"])
            self.assertTrue(script)
        self.assertEqual(self.request("/../../nara/store.py")[0], 404)

    def test_subscription_headers_and_immediate_revocation(self):
        state = example_state()
        self.store.set("state", state)
        self.runtime.active = copy.deepcopy(state)
        token = state["clients"][0]["token"]
        self.store.add_traffic([("user1", "upload", 100), ("user1", "download", 200)])
        status, config, headers = self.subscription_request(token)
        self.assertEqual(status, 200)
        self.assertIn("upload=100; download=200", headers["Subscription-Userinfo"])
        self.assertTrue(any(i["type"] == "tun" for i in config["inbounds"]))
        self.assertEqual(config["dns"]["final"], "remote")
        self.assertNotIn("private_key", str(config))
        state["clients"][0]["enabled"] = False
        self.store.set("state", state)
        self.assertEqual(self.subscription_request(token)[0], 404)

    def test_download_and_subscription_serve_the_same_vpn_profile(self):
        self.login()
        state = example_state()
        self.store.set("state", state)
        self.runtime.active = copy.deepcopy(state)
        client = state["clients"][0]
        export_status, exported, _ = self.request("/api/export/" + client["id"])
        sub_status, subscribed, _ = self.subscription_request(client["token"])
        self.assertEqual((export_status, sub_status), (200, 200))
        self.assertEqual(exported, subscribed)
        self.assertTrue(any(i["type"] == "tun" for i in exported["inbounds"]))
        self.assertEqual(exported["route"]["rules"][0]["action"], "hijack-dns")


    def test_complete_schema_requires_authentication_and_is_versioned(self):
        self.assertEqual(self.request('/api/core-schema')[0],401)
        self.login()
        status, data, _=self.request('/api/core-schema')
        self.assertEqual(status,200)
        self.assertEqual(data['version'],'1.14.3')
        self.assertIn('snell',data['types']['inbounds'])
        self.assertIn('DNSRuleAction',data['schema']['$defs'])
        self.assertEqual(self.request('/core-editor.js')[0],200)
        self.assertEqual(self.request('/dns-presets.js')[0],200)
        self.assertEqual(self.request('/routing.js')[0],200)

    def test_full_dns_save_and_default_resolver_apply_together(self):
        self.login()
        conf={'type':'hosts','tag':'hosts','predefined':{'example.com':['192.0.2.1']}}
        status,data,_=self.request('/api/save',{'revision':0,'collection':'dns_servers','record':{'mode':'native','config':conf}})
        self.assertEqual(status,200,data)
        status,data,_=self.request('/api/core-options',{'revision':1,'section':'dns','options':{'timeout':'5s','optimistic':{'enabled':True}},'default_resolver':'hosts'})
        self.assertEqual(status,200,data)
        model=self.store.get('state')
        self.assertEqual(model['settings']['dns_final'],'hosts')
        self.assertEqual(model['dns_servers'][-1]['config'],conf)
        self.assertEqual(model['core_options']['dns']['timeout'],'5s')
        status,config,_=self.request('/api/config')
        self.assertEqual(status,200)
        self.assertEqual(config['dns']['servers'][-1],conf)
        self.assertEqual(config['dns']['final'],'hosts')

    def test_routing_rules_save_reorder_and_revision_guard(self):
        self.login()
        ids=[]
        for revision,domain in enumerate(['one.example','two.example']):
            result=self.request('/api/save',{'revision':revision,'collection':'route_rules','record':{'config':{'action':'reject','domain_suffix':[domain]}}})
            self.assertEqual(result[0],200,result[1])
            ids.append(self.store.get('state')['route_rules'][-1]['id'])
        result=self.request('/api/reorder-rules',{'revision':2,'collection':'route_rules','id':ids[1]})
        self.assertEqual(result[0],200,result[1])
        self.assertEqual(self.store.get('state')['route_rules'][0]['id'],ids[1])
        self.assertEqual(self.request('/api/core-options',{'revision':2,'section':'log','options':{'level':'info'}})[0],400)

    def test_ordered_rules_move_both_directions_and_reject_invalid_moves_atomically(self):
        self.login()
        for revision, domain in enumerate(['one.example', 'two.example', 'three.example']):
            result = self.request('/api/save', {'revision':revision, 'collection':'route_rules',
                'record':{'config':{'domain_suffix':[domain], 'action':'reject'}}})
            self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        ids = [row['id'] for row in state['route_rules']]
        result = self.request('/api/reorder-rules', {'revision':3, 'collection':'route_rules', 'id':ids[0], 'direction':'down'})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        self.assertEqual([row['id'] for row in state['route_rules']], [ids[1], ids[0], ids[2]])
        for record in ({'id':ids[1], 'direction':'up'}, {'id':ids[2], 'direction':'down'},
                       {'id':'missing', 'direction':'up'}, {'id':ids[0], 'direction':'sideways'}):
            result = self.request('/api/reorder-rules', {'revision':4, 'collection':'route_rules', **record})
            self.assertEqual(result[0], 400, result[1])
            self.assertEqual(self.store.get('state'), state)
        result = self.request('/api/reorder-rules', {'revision':3, 'collection':'route_rules', 'id':ids[0], 'direction':'down'})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get('state'), state)

    def test_native_private_key_survives_redacted_edit(self):
        self.login()
        conf={'type':'wireguard','tag':'wg','private_key':'fixture-private-key','address':['10.0.0.1/32']}
        result=self.request('/api/save',{'revision':0,'collection':'endpoints','record':{'config':conf}})
        self.assertEqual(result[0],200,result[1])
        public=self.request('/api/state')[1]
        self.assertNotIn('fixture-private-key',json.dumps(public))
        record=public['endpoints'][0]
        record['config']['address']=['10.0.0.2/32']
        result=self.request('/api/save',{'revision':1,'collection':'endpoints','record':record})
        self.assertEqual(result[0],200,result[1])
        self.assertEqual(self.store.get('state')['endpoints'][0]['config']['private_key'],'fixture-private-key')

    def test_dashboard_has_versions_and_cached_update_results(self):
        self.login()
        self.store.set('updates',{'attempted_at':100000,'panel':{'latest':'9.0.0','checked_at':100000,'error':''},'core':{'latest':'9.0.1','checked_at':100000,'error':''}})
        with mock.patch.object(self.runtime,'version',return_value='sing-box version 1.14.3'):
            status,data,_=self.request('/api/dashboard')
        self.assertEqual(status,200)
        self.assertTrue(data['updates']['panel']['available'])
        self.assertTrue(data['updates']['core']['available'])
        self.assertEqual(data['updates']['trigger'],'panel_entry')
        self.assertNotIn('interval_hours',data['updates'])
        self.assertIn('panel_version',data)
        self.assertTrue({'cpu_model','ipv4','ipv6'} <= data['metrics'].keys())

    def test_update_checks_only_run_for_authenticated_panel_entries_and_do_not_block(self):
        entered, release = threading.Event(), threading.Event()
        def fetch(url):
            entered.set()
            release.wait(5)
            return {'tag_name':'v9.0.0'} if 'Nara-Panel' in url else {'tag_name':'v9.0.1'}
        with mock.patch('nara.updates.fetch',side_effect=fetch) as network:
            self.assertEqual(self.request('/api/check-updates',{})[0],401)
            self.login()
            self.request('/api/dashboard');self.request('/api/dashboard')
            network.assert_not_called()
            self.assertEqual(self.request('/api/check-updates',{}, {'X-CSRF-Token':'wrong'})[0],403)
            network.assert_not_called()
            try:
                status,data,_=self.request('/api/check-updates',{})
                self.assertEqual(status,200,data)
                self.assertTrue(data['started'])
                self.assertTrue(data['updates']['checking'])
                self.assertTrue(entered.wait(1))
                self.assertFalse(self.request('/api/check-updates',{})[1]['started'])
                self.assertEqual(network.call_count,1)
                self.assertTrue(self.request('/api/dashboard')[1]['updates']['checking'])
            finally:
                release.set()
            for _ in range(100):
                if not self.request('/api/dashboard')[1]['updates']['checking']:break
                time.sleep(.01)
            self.assertEqual(network.call_count,2)
            self.assertTrue(self.request('/api/check-updates',{})[1]['started'])
            for _ in range(100):
                if not self.request('/api/dashboard')[1]['updates']['checking']:break
                time.sleep(.01)
            self.assertEqual(network.call_count,4)

    def test_panel_update_requires_authentication_csrf_and_managed_install_and_queues_only_a_version(self):
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0'})[0],401)
        self.login()
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0'},{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0'})[0],400)
        from nara.access import Access
        self.server.RequestHandlerClass=make_handler(self.store,self.runtime,Path('web'),web_path=self.web_path,access=Access(self.store.directory,{'NARA_ACCESS_MANAGED':'1'}))
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0;id'})[0],400)
        before=self.store.get('state')
        proof=self.request('/api/backup/create',{'current':'test-password-123'})[1]['proof']
        status,data,_=self.request('/api/update-panel',{'version':'9.0.0','confirmed':True,'backup_proof':proof})
        self.assertEqual(status,200,data)
        job=json.loads((self.store.directory/'access-request.json').read_text())
        self.assertEqual(set(job),{'id','operation','version','created_at'})
        self.assertEqual(job['operation'],'update-panel');self.assertEqual(job['version'],'9.0.0')
        self.assertEqual(self.store.get('state'),before)
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.1'})[0],400)


class WebPathTests(APITests):
    web_path = "/AbCdEfGh"

    def request(self, path, body=None, headers=None):
        return super().request(self.web_path + path, body, headers)

    def test_root_and_unprefixed_api_are_unavailable(self):
        self.assertEqual(super().request("/")[0], 404)
        self.assertEqual(super().request("/api/health")[0], 404)
        self.assertEqual(super().request("/api/login", {"username": "admin", "password": "test-password-123"})[0], 404)
        self.assertEqual(super().request("/abcdefgh/")[0], 404)

    def test_no_trailing_slash_redirects_and_assets_load(self):
        status, _, headers = super().request(self.web_path)
        self.assertEqual(status, 308)
        self.assertEqual(headers["Location"], self.web_path + "/")
        for asset in ("/routing.js", "/app.js", "/style.css", "/favicon.svg", "/vendor/qrcodegen.js", "/subscription-qr.js", "/options.js"):
            self.assertEqual(self.request(asset)[0], 200)

    def test_cookie_is_scoped_to_web_path(self):
        status, data, headers = self.request("/api/login", {"username": "admin", "password": "test-password-123"})
        self.assertEqual(status, 200)
        self.assertIn("Path=/AbCdEfGh/;", headers["Set-Cookie"])
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.csrf = data["csrf"]
        status, _, headers = self.request("/api/logout", {})
        self.assertEqual(status, 200)
        self.assertIn("Path=/AbCdEfGh/", headers["Set-Cookie"])

class AccessChangeAPITests(unittest.TestCase):
    setUp = APITests.setUp
    tearDown = APITests.tearDown
    request = APITests.request
    login = APITests.login
    web_path = ""
    def test_entry_change_checks_csrf_revision_and_host_before_queueing(self):
        from nara.access import Access
        config={'NARA_PORT':str(self.server.server_port),'NARA_SUB_PORT':str(self.subserver.server_port),'NARA_WEB_PATH':'/PanelOnly','NARA_SUB_PATH':'/Downloads','NARA_ACCESS_MANAGED':'1'}
        access=Access(self.store.directory,config)
        # Keep this fixture's actual panel at / while the entry metadata describes
        # the next Linux deployment's configured webPath.
        self.server.RequestHandlerClass=make_handler(self.store,self.runtime,Path('web'),access=access)
        self.login()
        payload={'values':{'panel_port':15000,'subscription_port':15001,'web_path':'/NewPanel','sub_path':'/NewDownloads'},'revision':access.info()['revision'],'current_url':'http://127.0.0.1:'+str(self.server.server_port)+'/'}
        self.assertEqual(self.request('/api/access',payload,{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request('/api/access',{**payload,'revision':'stale'})[0],400)
        self.assertEqual(self.request('/api/access',{**payload,'current_url':'https://unrelated.example/'})[0],400)
        result=self.request('/api/access',payload)
        self.assertEqual(result[0],202,result[1])
        self.assertEqual(result[1]['url'],'http://127.0.0.1:15000/NewPanel/')
        self.assertTrue((self.store.directory/'access-request.json').exists())
        self.assertEqual(self.request('/api/access-status/'+result[1]['id'])[1]['status'],'pending')

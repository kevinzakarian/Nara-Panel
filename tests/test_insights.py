import copy
import csv
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from nara import traffic, portable, client_links, migration, notifications
from nara.access import Access
from nara.store import Store
from tests.helpers import example_state


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def sample(self,up,down,at=100000,boot='boot',interface='eth0'):
        traffic.sample_host(self.store,at,{'upload':up,'download':down,'boot':boot,'interface':interface})
    def test_hardware_deltas_survive_panel_restart_and_never_count_first_sample_or_reboots(self):
        self.sample(500,900);self.sample(700,1200,100005)
        self.assertEqual(traffic.summary(self.store,100005)['cycle']['used'],500)
        restarted=Store(self.temp.name)
        traffic.sample_host(restarted,100010,{'upload':800,'download':1300,'boot':'boot','interface':'eth0'})
        self.assertEqual(traffic.summary(restarted,100010)['cycle']['used'],700)
        self.sample(20,30,100015,boot='reboot');self.sample(40,50,100020,boot='reboot')
        self.assertEqual(traffic.summary(self.store,100020)['cycle']['used'],740)
    def test_independent_resets_retain_client_quotas_and_history(self):
        self.sample(100,100);self.sample(200,300,100005)
        self.store.add_traffic([('u','upload',45),('u','download',55)],[('in','upload',45)])
        traffic.reset(self.store,'cycle',100005);self.assertEqual(traffic.summary(self.store,100005)['cycle']['used'],0)
        self.assertEqual(traffic.summary(self.store,100005)['panel_bytes'],100)
        traffic.reset(self.store,'panel',100005)
        self.assertEqual(traffic.summary(self.store,100005)['panel_bytes'],0)
        self.assertEqual(self.store.totals()['u'],{'upload':45,'download':55})
        self.store.add_traffic([('u','upload',7)])
        self.assertEqual(traffic.summary(self.store,100005)['panel_bytes'],7)
        with self.store.connect() as db:self.assertGreater(db.execute('SELECT COUNT(*) FROM traffic_history').fetchone()[0],0)
        self.store.commit_configuration(self.store.get('state'),save=True,reset_client='u')
        self.assertEqual(traffic.summary(self.store,100005)['panel_bytes'],7)
    def test_clamped_reset_days_and_timezone_boundaries(self):
        now=dt.datetime(2026,2,28,22,tzinfo=dt.timezone.utc).timestamp()
        beginning,ending=traffic.period(now,31,'Asia/Tehran')
        self.assertEqual(dt.datetime.fromtimestamp(beginning,dt.timezone.utc).isoformat(),'2026-02-27T20:30:00+00:00')
        self.assertEqual(dt.datetime.fromtimestamp(ending,dt.timezone.utc).isoformat(),'2026-03-30T20:30:00+00:00')
    def test_cycle_rollover_and_direction(self):
        conf=traffic.settings(self.store);conf.update(count='upload');self.store.set('traffic_settings',conf)
        jan=dt.datetime(2026,1,31,23,59,50,tzinfo=dt.timezone.utc).timestamp()
        self.sample(100,100,jan);self.sample(200,300,jan+5)
        self.assertEqual(traffic.summary(self.store,jan+5)['cycle']['used'],100)
        self.sample(210,310,jan+15)
        self.assertEqual(traffic.summary(self.store,jan+15)['cycle']['used'],10)
    def test_downtime_across_a_billing_boundary_is_not_all_attributed_to_the_new_month(self):
        jan=dt.datetime(2026,1,31,23,tzinfo=dt.timezone.utc).timestamp()
        self.sample(100,100,jan);self.sample(1000,2000,jan+7200)
        info=traffic.summary(self.store,jan+7200)
        self.assertEqual(info['cycle']['used'],0)
        self.assertEqual(info['total'],{'upload':900,'download':1900})
    def test_rollups_not_affected_by_quota_resets_and_queries_bounded(self):
        self.store.add_traffic([('u','upload',100),('u','download',200)],[('i','download',200)])
        self.store.commit_configuration(self.store.get('state'),reset_client='u')
        for window in ('6h','24h','week','month','3months'):
            data=traffic.history(self.store,'client','u',window)
            self.assertLessEqual(len(data['points']),169)
            self.assertEqual(sum(p['upload']+p['download'] for p in data['points']),300)
        self.assertEqual(sum(p['download'] for p in traffic.history(self.store,'inbound','i','24h')['points']),200)
        for change in ({'reset_day':0},{'duration_minutes':0},{'cpu_percent':101},{'interface':'eth0;id'},{'bandwidth_mbps':float('nan')}):
            with self.assertRaises(ValueError):traffic.validate({**traffic.DEFAULTS,**change})
    def test_portable_backup_omits_source_addresses_and_restores_destination_identity(self):
        state=example_state();state['settings'].update(public_url='https://old.example/Old',subscription_url='https://oldsub.example/Sub')
        self.store.set('state',state);self.store.add_traffic([('user1','upload',56)])
        self.store.set('admin',{'username':'not-in-backup','password':'private-hash'})
        value=portable.document(self.store)
        encoded=json.dumps(value)
        self.assertNotIn('old.example',encoded);self.assertNotIn('oldsub.example',encoded);self.assertNotIn('private-hash',encoded)
        target=example_state();target['settings'].update(server_address='203.0.113.7',public_url='https://new.example/New',subscription_url='https://sub.new.example/Sub')
        model,totals,conf,bot=portable.prepare(value,target)
        self.assertEqual(model['settings']['server_address'],'203.0.113.7');self.assertEqual(model['settings']['public_url'],'https://new.example/New')
        self.assertEqual(totals['user1']['upload'],56);self.assertEqual(model['clients'][0]['password'],state['clients'][0]['password']);self.assertEqual(conf['interface'],'')
        result=portable.snapshot(self.store);self.assertEqual(Path(result['path']).stat().st_mode&0o777,0o600)
    def test_portable_rejects_invalid_data_before_restore(self):
        document=portable.document(self.store)
        for update in ({'schema':True},{'traffic':{'u':{'upload':-1,'download':0}}},{'telegram':'invalid'}):
            candidate={**document,**update}
            if 'traffic' in update:
                candidate['state']=example_state();candidate['traffic']={'user1':{'upload':-1,'download':0}}
            with self.assertRaises(ValueError):portable.prepare(candidate,self.store.get('state'))
    def test_csv_comma_quoting_formulas_and_complete_json_subscription(self):
        state=example_state();state['clients'][0]['name']='=BAD, "test"';state['settings']['server_address']='203.0.113.9';self.store.set('state',state)
        data=client_links.export(self.store,Access(self.store.directory,{'NARA_SUB_PATH':'/Links','NARA_SUB_PORT':'10001'}),'http://panel.example/Panel/')
        rows=list(csv.reader(io.StringIO(data)));self.assertEqual(len(rows),2);self.assertEqual(len(rows[1]),6)
        self.assertTrue(rows[1][0].startswith("'="));self.assertIn('sing-box://import-remote-profile?',rows[1][1]);self.assertIn('http://panel.example:10001/Links/',rows[1][2]);self.assertIn('vless://',rows[1][3])
    def test_csv_includes_exhausted_disabled_and_unassigned_accounts(self):
        state=example_state();state['clients'][0].update(enabled=False,quota_bytes=1,expires_at='2020-01-01T00:00:00Z');self.store.set('state',state)
        self.store.add_traffic([('user1','upload',999)])
        rows=list(csv.reader(io.StringIO(client_links.export(self.store,Access(self.store.directory,{}),'http://panel.example/'))))
        self.assertIn('vless://',rows[1][3]);self.assertFalse(self.store.get('state')['clients'][0]['enabled'])
        state['clients'][0]['inbound_ids']=[];self.store.set('state',state)
        rows=list(csv.reader(io.StringIO(client_links.export(self.store,Access(self.store.directory,{}),'http://panel.example/'))))
        self.assertEqual(rows[1][3],'')
    def test_hysteria_links_preserve_obfuscation_tls_and_ipv6(self):
        state=example_state('hysteria2');state['settings']['server_address']='2001:db8::9'
        state['inbounds'][0]['server_options']={'obfs':{'type':'salamander','password':'x & y'}}
        # TLS validation belongs to config tests; use an exact rendered outbound here.
        outbound={'type':'hysteria2','tag':'Test','server':'2001:db8::9','server_port':443,'password':'x/y','obfs':{'type':'salamander','password':'x & y'},'tls':{'enabled':True,'insecure':True,'server_name':'example.com'}}
        with mock.patch('nara.client_links.client_config',return_value={'outbounds':[outbound]}):result=client_links.links(state,state['clients'][0],{})[0]['url']
        self.assertIn('@[2001:db8::9]:443',result);self.assertIn('obfs-password=x+%26+y',result);self.assertIn('insecure=1',result);self.assertIn('sni=example.com',result)
    def test_migration_destination_injection_and_localhost_rejected(self):
        base={'host':'203.0.113.15','web_path':'/Panel','sub_path':'/Sub'}
        self.assertEqual(migration.destination(base)['panel_port'],10000)
        for update in ({'host':'127.0.0.1'},{'host':'x;id'},{'panel_domain':'example.com;id'},{'web_path':'/x/y'},{'panel_port':443},{'subscription_domain':'sub.example.com'}):
            with self.assertRaises(ValueError):migration.destination({**base,**update})
    def test_separate_https_subscription_domain_uses_its_own_proxy_site(self):
        from nara.maintenance import proxy_config
        config={'NARA_PORT':'10000','NARA_WEB_PATH':'/Panel','NARA_SUB_PORT':'10001','NARA_SUB_PATH':'/Sub','NARA_PUBLIC_SUB_HOST':'sub.example.com','NARA_PUBLIC_PANEL_PORT':'443','NARA_PUBLIC_SUB_PORT':'8443'}
        value=proxy_config('panel.example.com',config,'automatic',Path('/private/certs'))
        self.assertIn('https://panel.example.com {',value);self.assertIn('https://sub.example.com:8443 {',value)
        self.assertIn('reverse_proxy 127.0.0.1:10001',value)
    def test_migration_probe_does_not_authenticate_and_returns_sha256_pin(self):
        import base64
        key=base64.b64encode(b'fixture-key').decode()
        with mock.patch('nara.migration.shutil.which',return_value='/usr/bin/ssh'),mock.patch('nara.migration.subprocess.run',return_value=mock.Mock(stdout=('203.0.113.15 ssh-ed25519 '+key+'\n').encode())) as run:
            result=migration.probe(self.store,{'host':'203.0.113.15','ssh_port':2222})
        self.assertTrue(result['fingerprint'].startswith('SHA256:'));self.assertEqual(run.call_args.args[0][0],'ssh-keyscan');self.assertNotIn('password',str(run.call_args))
        manager=migration.Manager(self.store,mock.Mock())
        with self.assertRaises(ValueError):manager.start({'host':'203.0.113.15','ssh_port':2222,'web_path':'/Panel','sub_path':'/Sub','probe_id':result['id'],'fingerprint':'wrong','auth_mode':'password','ssh_password':'PRIVATE'})
        self.assertNotIn('PRIVATE',json.dumps(manager.status()))


if __name__=='__main__':unittest.main()

from tests import test_api


class InsightsAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;request=test_api.APITests.request;login=test_api.APITests.login;web_path=''
    def test_backups_and_csv_require_session_csrf_and_current_password(self):
        self.assertEqual(self.request('/api/backup/create',{})[0],401)
        self.login()
        for path in ('/api/backup/create','/api/clients-csv'):
            self.assertEqual(self.request(path,{'current':'test-password-123'},{'X-CSRF-Token':'bad'})[0],403)
            self.assertEqual(self.request(path,{'current':'wrong'})[0],400)
            self.assertEqual(self.request(path,{'current':'test-password-123'})[0],200)
        self.assertEqual(self.request('/api/backup/create')[0],404)
        self.assertEqual(self.subscription_request('api/backup/create')[0],404)
    subscription_request=test_api.APITests.subscription_request
    def test_traffic_settings_validate_and_leave_the_core_and_client_limits_unchanged(self):
        self.login();before=self.store.get('state');calls=self.runtime.apply.call_count
        conf={**traffic.DEFAULTS,'monthly_bytes':1024**4,'reset_day':18,'cpu_percent':85,'duration_minutes':8}
        self.assertEqual(self.request('/api/traffic/settings',{'settings':conf})[0],200)
        self.assertEqual(self.request('/api/dashboard')[1]['traffic']['settings']['reset_day'],18)
        self.assertEqual(self.store.get('state'),before);self.assertEqual(self.runtime.apply.call_count,calls)
        self.assertEqual(self.request('/api/traffic/settings',{'settings':{**conf,'reset_day':0}})[0],400)
        self.assertEqual(traffic.settings(self.store),conf)
        self.assertEqual(self.request('/api/traffic?kind=client&id=u&range=24h')[0],200)
        self.assertEqual(self.request('/api/traffic?kind=client&id=u&range=100years')[0],400)
    def test_update_requires_fresh_backup_confirmation_and_same_session(self):
        self.login()
        self.server.RequestHandlerClass=__import__('nara.server',fromlist=['make_handler']).make_handler(self.store,self.runtime,Path('web'),access=Access(self.store.directory,{'NARA_ACCESS_MANAGED':'1'}))
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0'})[0],400)
        proof=self.request('/api/backup/create',{'current':'test-password-123'})[1]['proof']
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0','backup_proof':proof})[0],400)
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.0','backup_proof':proof,'confirmed':True})[0],200)
        self.assertEqual(self.request('/api/update-panel',{'version':'9.0.1','backup_proof':proof,'confirmed':True})[0],400)


class PortableCoreTests(unittest.TestCase):
    def setUp(self):
        import os
        from nara.runtime import Runtime
        self.binary=Path(os.environ.get('SING_BOX_TEST_BINARY','dist/sing-box-full')).resolve()
        if not self.binary.exists():self.skipTest('Set SING_BOX_TEST_BINARY to exercise a real core')
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.store.set('state',example_state());self.store.set('admin',{'username':'destination','password':'retained'})
        self.runtime=Runtime(self.store,str(self.binary),stats_port=__import__('tests.helpers',fromlist=['free_port']).free_port())
        self.runtime.apply(self.store.get('state'),save=True)
    def tearDown(self):
        if hasattr(self,'runtime'):self.runtime.stop(collect=False);self.temp.cleanup()
    def test_restore_with_real_core_retains_destination_urls_and_administrator(self):
        self.store.add_traffic([('user1','download',1234)])
        backup=portable.document(self.store)
        changed=self.store.get('state');changed['clients'][0]['name']='New destination';changed['settings'].update(public_url='https://target.example/Panel',server_address='203.0.113.88');changed['revision']+=1
        self.runtime.apply(changed,save=True);self.store.add_traffic([('user1','download',5678)])
        result=portable.restore(self.store,self.runtime,backup)
        self.assertTrue(self.runtime.running);self.assertTrue(Path(result['backup_path']).exists())
        self.assertEqual(self.store.get('state')['clients'][0]['name'],'Test client')
        self.assertEqual(self.store.get('state')['settings']['server_address'],'203.0.113.88');self.assertEqual(self.store.get('admin')['username'],'destination')
        self.assertEqual(self.store.totals()['user1']['download'],1234)
    def test_failed_destination_start_rolls_back_model_usage_and_running_core(self):
        backup=portable.document(self.store);backup['state']['clients'][0]['name']='Should roll back'
        self.store.add_traffic([('user1','upload',999)])
        original=self.runtime.launch;calls=[]
        def launch(generation):
            calls.append(True)
            if len(calls)==1:raise ValueError('Fixture target startup failed')
            return original(generation)
        with mock.patch.object(self.runtime,'launch',side_effect=launch),self.assertRaises(ValueError):portable.restore(self.store,self.runtime,backup)
        self.assertTrue(self.runtime.running);self.assertEqual(self.store.get('state')['clients'][0]['name'],'Test client');self.assertEqual(self.store.totals()['user1']['upload'],999)

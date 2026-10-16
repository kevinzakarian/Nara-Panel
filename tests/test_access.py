import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from nara import access as a, maintenance as m
from nara.store import Store


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = m.Layout(Path(self.temp.name))
        self.paths.env.parent.mkdir(parents=True)
        self.config = {'NARA_PORT':'12000','NARA_SUB_PORT':'12001','NARA_WEB_PATH':'/PanelOnly', 'NARA_SUB_PATH':'/DownloadOnly', 'NARA_BIND':'0.0.0.0','NARA_STATS_PORT':'10085','NARA_ACCESS_MANAGED':'1'}
        m.write_env(self.paths.env, self.config)
        self.store = Store(self.paths.data)
        state = self.store.get('state')
        state['settings'].update(public_url='http://panel.example.com:12000/PanelOnly/', subscription_url='http://panel.example.com:12001/DownloadOnly/')
        self.store.set('state', state); self.store.set('active', state)
        self.values = {'panel_port':13000,'subscription_port':13001,'web_path':'/NewPanel','sub_path':'/NewDownloads'}

    def tearDown(self):
        self.temp.cleanup()

    def job(self):
        return {'id':'fixture-job', 'created_at':time.time(),'expected':a.signature(a.from_env(self.config)), 'values':self.values}

    def mocks(self):
        stack = contextlib.ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(a, 'port_available', return_value=True))
        stack.enter_context(mock.patch.object(m, 'active', return_value=True))
        stack.enter_context(mock.patch.object(m, 'run'))
        stack.enter_context(mock.patch.object(m, 'panel_health'))
        stack.enter_context(mock.patch.object(m, 'subscription_health'))
        stack.enter_context(mock.patch.object(m, 'verify_https'))
        stack.enter_context(mock.patch.object(m.shutil, 'chown'))
        stack.enter_context(mock.patch.object(m.subprocess, 'run'))

    def test_only_four_validated_fields_are_accepted(self):
        self.assertEqual(a.validate(self.values), self.values)
        for patch in ({'sub_path':'/NewPanel'},{'subscription_port':13000},{'panel_port':10085},{'panel_port':False},{'web_path':None},{'sub_path':'/x\nNARA_BIND=0.0.0.0'},{'sub_path':'../escape'},{'command':'id'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                a.validate({**self.values, **patch})

    def test_queue_is_private_atomic_and_rejects_overlapping_requests(self):
        manager = a.Access(self.paths.data, self.config)
        result = manager.request(self.values, manager.info()['revision'], 'http://panel.example.com:12000/PanelOnly/')
        request = self.paths.data / 'access-request.json'
        self.assertEqual(request.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(request.read_text())['id'], result['id'])
        self.assertEqual(result['url'],'http://panel.example.com:13000/NewPanel/')
        with self.assertRaisesRegex(ValueError, 'in progress'):
            manager.request(self.values, manager.info()['revision'], 'http://panel.example.com:12000/PanelOnly/')
        with self.assertRaisesRegex(ValueError, 'refresh'):
            manager.request(self.values, 'stale', 'http://panel.example.com:12000/PanelOnly/')

    def test_success_applies_both_entry_points_and_updates_both_url_models(self):
        self.mocks()
        a.apply_job(self.paths, self.job())
        env = m.settings(self.paths)
        self.assertEqual((env['NARA_PORT'],env['NARA_SUB_PORT']),('13000','13001'))
        self.assertEqual((env['NARA_WEB_PATH'],env['NARA_SUB_PATH']),('/NewPanel','/NewDownloads'))
        for name in ('state','active'):
            values = self.store.get(name)['settings']
            self.assertEqual(values['public_url'], 'http://panel.example.com:13000/NewPanel/')
            self.assertEqual(values['subscription_url'], 'http://panel.example.com:13001/NewDownloads/')

    def test_occupied_port_is_rejected_before_stopping_live_services(self):
        before = self.paths.env.read_text()
        self.mocks()
        with mock.patch.object(a, 'port_available', return_value=False), mock.patch.object(m, 'run') as command, self.assertRaisesRegex(ValueError, 'in use'):
            a.apply_job(self.paths, self.job())
        command.assert_not_called()
        self.assertEqual(self.paths.env.read_text(),before)

    def test_failed_readiness_restores_entry_points_and_subscription_urls(self):
        self.mocks()
        before = self.paths.env.read_text()
        with mock.patch.object(m, 'subscription_health', side_effect=ValueError('fixture subscription failed')), self.assertRaises(ValueError):
            a.apply_job(self.paths, self.job())
        self.assertEqual(self.paths.env.read_text(),before)
        self.assertEqual(self.store.get('state')['settings']['subscription_url'],'http://panel.example.com:12001/DownloadOnly/')

    def test_panel_subscription_port_swap_is_supported(self):
        self.mocks()
        self.values.update(panel_port=12001,subscription_port=12000)
        a.apply_job(self.paths, self.job())
        self.assertEqual(m.settings(self.paths)['NARA_PORT'],'12001')

    def test_stale_or_expired_job_does_not_apply(self):
        job = self.job(); job['created_at'] -= 1000
        (self.paths.data / 'access-request.json').write_text(json.dumps(job))
        with mock.patch.object(a,'apply_job') as apply:
            a.process_request(self.paths)
        apply.assert_not_called()
        self.assertFalse((self.paths.data / 'access-request.json').exists())
        self.assertEqual(json.loads((self.paths.data / 'access-result.json').read_text())['status'],'failed')

    def test_status_file_does_not_follow_service_owned_symlinks(self):
        outside = Path(self.temp.name) / 'protected'
        outside.write_text('preserve this file')
        (self.paths.data / 'access-result.json').symlink_to(outside)
        (self.paths.data / 'access-result.json.tmp').symlink_to(outside)
        (self.paths.data / 'access-request.json').write_text(json.dumps(self.job()))
        with mock.patch.object(a, 'apply_job', return_value=self.values):
            a.process_request(self.paths)
        self.assertEqual(outside.read_text(),'preserve this file')
        self.assertFalse((self.paths.data / 'access-result.json').is_symlink())
        self.assertEqual(json.loads((self.paths.data / 'access-result.json').read_text())['status'],'complete')

    def test_saved_inbound_port_is_reserved_even_with_core_stopped(self):
        state = self.store.get('state')
        state['inbounds'] = [{'enabled': True, 'mode': 'native', 'config': {'listen_port': 13001}}]
        self.store.set('state', state)
        self.mocks()
        with mock.patch.object(m, 'run') as command, self.assertRaisesRegex(ValueError, 'reserved'):
            a.apply_job(self.paths, self.job())
        command.assert_not_called()

    def test_maintenance_lock_rejection_is_reported_without_applying(self):
        (self.paths.data / 'access-request.json').write_text(json.dumps(self.job()))
        with mock.patch.object(a, 'apply_job') as apply:
            a.process_request(self.paths, 'Server maintenance is running')
        apply.assert_not_called()
        self.assertEqual(json.loads((self.paths.data / 'access-result.json').read_text())['error'], 'Server maintenance is running')

    def test_request_symlink_is_rejected_without_reading_target(self):
        outside = Path(self.temp.name) / 'protected-request'
        outside.write_text(json.dumps(self.job()))
        (self.paths.data / 'access-request.json').symlink_to(outside)
        with mock.patch.object(a, 'apply_job') as apply:
            a.process_request(self.paths)
        apply.assert_not_called()
        self.assertTrue(outside.exists())
        self.assertEqual(json.loads((self.paths.data / 'access-result.json').read_text())['status'], 'failed')

    def test_managed_https_keeps_backend_ports_and_updates_two_proxy_sites(self):
        self.config.update(NARA_BIND='127.0.0.1',NARA_PUBLIC_HOST='panel.example.com',NARA_PUBLIC_PANEL_PORT='443',NARA_PUBLIC_SUB_PORT='8443',NARA_SUB_SCHEME='https')
        m.write_env(self.paths.env,self.config)
        directory = self.paths.https / 'generation-fixture'; directory.mkdir(parents=True)
        (self.paths.https / 'current').symlink_to(directory.name)
        (directory / 'metadata.json').write_text(json.dumps({'host':'panel.example.com','mode':'automatic','legacy':False}))
        (directory / 'Caddyfile').write_text('old proxy')
        self.mocks()
        a.apply_job(self.paths,self.job())
        env = m.settings(self.paths)
        self.assertEqual((env['NARA_PORT'],env['NARA_SUB_PORT']),('12000','12001'))
        self.assertEqual((env['NARA_PUBLIC_PANEL_PORT'],env['NARA_PUBLIC_SUB_PORT']),('13000','13001'))
        proxy = (directory / 'Caddyfile').read_text()
        for part in ('https://panel.example.com:13000','https://panel.example.com:13001','127.0.0.1:12000','127.0.0.1:12001','/NewDownloads','/NewPanel'):
            self.assertIn(part,proxy)
        self.assertEqual(self.store.get('state')['settings']['subscription_url'],'https://panel.example.com:13001/NewDownloads/')

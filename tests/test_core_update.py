import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nara import access, core_update as core, maintenance, native
from nara.runtime import Runtime
from nara.store import Store
from tests.helpers import example_state, free_port
from tests.test_core import CORE


class CoreUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = maintenance.Layout(Path(temp.name))
        self.live = self.paths.app / 'bin'
        self.live.mkdir(parents=True)
        self.paths.data.mkdir(parents=True)
        self.paths.env.parent.mkdir()
        self.paths.env.write_text('NARA_ACCESS_MANAGED=1\n')
        self.binary = self.live / 'sing-box'
        self.binary.write_text('old binary')
        (self.live / 'libcronet.so').write_text('old library')
        self.job = {'id': 'fixture', 'operation': 'update-core', 'version': native.VERSION, 'created_at': 1}

    def test_only_manifest_version_can_be_queued(self):
        broker = access.Access(self.paths.data, {'NARA_ACCESS_MANAGED': '1'})
        with patch.object(core, 'compatible_release', return_value=native.VERSION):
            for target, installed, binary in [('99.0.0', '1.13.0', core.MANAGED_BINARY),
                                              (native.VERSION, native.VERSION, core.MANAGED_BINARY),
                                              (native.VERSION, '1.13.0', '/custom/sing-box')]:
                with self.subTest(target=target, installed=installed, binary=binary), self.assertRaises(ValueError):
                    broker.request_core_update(target, installed, binary)
            job = broker.request_core_update(native.VERSION, 'sing-box version 1.13.0', core.MANAGED_BINARY)
        queued = json.loads((self.paths.data / 'access-request.json').read_text())
        self.assertEqual(queued['id'], job['id'])
        self.assertEqual(queued['operation'], 'update-core')
        self.assertEqual(set(queued), {'id', 'operation', 'version', 'created_at'})

    def exercise(self, failure='', running=True):
        checked = ['original', running]
        calls = []

        def download(command, **kwargs):
            stage = Path(command[-1])
            stage.mkdir()
            (stage / 'sing-box').write_text('new binary')
            (stage / 'libcronet.so').write_text('new library')

        def version_info(binary):
            version = '1.13.0' if binary == self.binary else native.VERSION
            return core.version(version), {'with_quic', 'with_v2ray_api'}

        def check(*_):
            calls.append('check')
            self.assertEqual(self.binary.read_text(), 'old binary')
            if failure == 'preflight':
                raise ValueError('private fixture information')
            return checked

        def service(command, **kwargs):
            calls.append(command[1])
            if command[1] == 'start':
                self.assertEqual((self.live / 'libcronet.so').read_text(),
                                 self.binary.read_text().replace('binary', 'library'))

        def health(paths, expected):
            self.assertIs(expected, running)
            if failure == 'startup' and self.binary.read_text() == 'new binary':
                raise ValueError('startup failed')

        with (patch.object(core, 'compatible_release', return_value=native.VERSION),
              patch.object(maintenance, 'needs_database_owner', return_value=True),
              patch.object(maintenance, '_database_owner_worker', side_effect=lambda owner, operation, timeout: operation()),
              patch.object(core, 'core_info', side_effect=version_info),
              patch.object(core.subprocess, 'run', side_effect=download),
              patch.object(core, 'validate_models', side_effect=check),
              patch.object(core, 'snapshot', return_value=['changed', running] if failure == 'race' else checked),
              patch.object(maintenance, 'panel_health', return_value={'core_running': running}),
              patch.object(maintenance, 'backup', side_effect=lambda _: calls.append('backup')),
              patch.object(maintenance, 'run', side_effect=service),
              patch.object(core, 'verify_health', side_effect=health)):
            if failure:
                expected = {'preflight': 'configuration checks', 'startup': 'previous core was restored', 'race': 'Settings changed'}
                with self.assertRaisesRegex(ValueError, expected[failure]) as error:
                    core.apply(self.paths, self.job)
                self.assertNotIn('private fixture information', str(error.exception))
            else:
                self.assertEqual(core.apply(self.paths, self.job), {'version': native.VERSION, 'core_running': running})
        self.assertEqual(self.binary.read_text(), ('old' if failure else 'new') + ' binary')
        self.assertEqual((self.live / 'libcronet.so').read_text(), ('old' if failure else 'new') + ' library')
        self.assertFalse(list(self.paths.app.glob('.nara-core-update-*')))
        return calls

    def test_preflight_failure_never_stops_the_service(self):
        self.assertEqual(self.exercise('preflight'), ['check'])

    def test_startup_failure_restores_binary_and_library(self):
        self.assertEqual(self.exercise('startup'), ['check', 'backup', 'stop', 'start', 'stop', 'start'])

    def test_change_after_preflight_reopens_previous_core(self):
        self.assertEqual(self.exercise('race'), ['check', 'backup', 'stop', 'start'])

    def test_valid_update_can_keep_the_core_stopped(self):
        self.assertEqual(self.exercise(running=False), ['check', 'backup', 'stop', 'start'])

    @unittest.skipUnless(CORE, 'Set SING_BOX_TEST_BINARY for real-core preflight')
    def test_real_core_checks_saved_and_active_models_without_restarting(self):
        store = Store(self.paths.data)
        runtime = Runtime(store, CORE, free_port())
        self.addCleanup(runtime.stop)
        state = example_state()
        runtime.apply(state, save=True)
        pid = runtime.process.pid
        self.assertEqual(core.validate_models(self.paths, CORE, runtime.stats_port), core.snapshot(self.paths))
        changed = store.get('state')
        config = {'type': 'trojan', 'tag': 'missing-cert', 'listen': '127.0.0.1', 'listen_port': free_port(),
                  'users': [{'password': 'fixture-only'}], 'tls': {'enabled': True}}
        changed['inbounds'].append({'mode': 'native', 'id': 'invalid', 'tag': config['tag'], 'type': config['type'], 'config': config})
        store.set('state', changed)
        with self.assertRaisesRegex(ValueError, 'TLS Certificate is missing'):
            core.validate_models(self.paths, CORE, runtime.stats_port)
        self.assertEqual(runtime.process.pid, pid)
        self.assertTrue(runtime.running)

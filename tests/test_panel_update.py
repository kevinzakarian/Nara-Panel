import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from nara import panel_update as u, access as a, maintenance as m


class PanelUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = m.Layout(Path(self.temp.name))
        self.paths.app.mkdir(parents=True)
        self.paths.data.mkdir(parents=True)
        (self.paths.app / 'requirements.txt').write_text('fixture\n')
        self.job = {'id':'fixture-job','operation':'update-panel','version':'9.0.0','created_at':time.time()}

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, requirements=b'fixture\n'):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name, payload in {'release.json':b'{"version":"9.0.0"}', 'requirements.txt':requirements, 'update.sh':b'#!/bin/bash\nexit 0\n'}.items():
                entry=tarfile.TarInfo('nara-panel/'+name);entry.size=len(payload);archive.addfile(entry,io.BytesIO(payload))
        return data.getvalue()

    def responses(self, payload):
        return [b'{"tag_name":"v9.0.0","draft":false,"prerelease":false}',
                (hashlib.sha256(payload).hexdigest()+'  nara-panel_9.0.0_source.tar.gz\n').encode(),payload]

    def test_verified_release_is_backed_up_then_installed_and_health_checked(self):
        with mock.patch.object(u,'download',side_effect=self.responses(self.archive())) as fetch, mock.patch('nara.maintenance.backup') as backup, mock.patch.object(u,'run_installer') as install, mock.patch('nara.maintenance.panel_health',return_value={'version':'9.0.0'}), mock.patch.object(a,'write_result') as progress:
            result=u.apply(self.paths,self.job)
            self.assertEqual(result,{'version':'9.0.0','backup_created':True})
            self.assertEqual([call.args[1]['progress'] for call in progress.call_args_list],[10,25,40,55,70,90])
            self.assertTrue(all(call.args[1]['status']=='running' and call.args[1]['id']==self.job['id'] for call in progress.call_args_list))
            backup.assert_called_once_with(self.paths);install.assert_called_once()
            self.assertEqual(install.call_args.args[0].name,'nara-panel')
            self.assertTrue(all(call.args[0].startswith(('https://api.github.com/repos/kevinzakarian/Nara-Panel/','https://github.com/kevinzakarian/Nara-Panel/releases/')) for call in fetch.call_args_list))
            self.assertEqual((self.paths.root/'var/log/nara-panel-update.log').stat().st_mode & 0o777,0o600)

    def test_bad_hash_and_changed_dependencies_never_execute_code(self):
        for dependencies in (False,True):
            payload=self.archive(b'changed\n' if dependencies else b'fixture\n');replies=self.responses(payload)
            if not dependencies:replies[-1]=payload+b'changed'
            with self.subTest(dependencies=dependencies), mock.patch.object(u,'download',side_effect=replies), mock.patch.object(u,'run_installer') as install, self.assertRaisesRegex(ValueError,'checksum|Dependencies'):
                u.apply(self.paths,self.job)
            install.assert_not_called()

    def test_commands_urls_downgrades_and_symlink_archives_are_rejected(self):
        for value in (u.__version__,'https://example.com','9.0.0;id','9.0.0/../../x','9.0.0-rc.1'):
            with self.subTest(value=value),self.assertRaises(ValueError):u.target(value)
        with self.assertRaises(ValueError):u.apply(self.paths,{**self.job,'command':'id'})
        for name,link in (('../outside',False),('nara-panel/link',True)):
            data=io.BytesIO()
            with tarfile.open(fileobj=data,mode='w:gz') as archive:
                entry=tarfile.TarInfo(name)
                if link:entry.type=tarfile.SYMTYPE;entry.linkname='/etc/passwd'
                archive.addfile(entry)
            with self.assertRaisesRegex(ValueError,'Invalid panel archive'):u.unpack(data.getvalue(),Path(self.temp.name)/'extract')

    def test_broker_dispatches_only_the_fixed_update_operation_and_reports_failure(self):
        for fail in (False,True):
            (self.paths.data/'access-request.json').write_text(json.dumps(self.job))
            with mock.patch.object(u,'apply',side_effect=ValueError('fixture failure') if fail else None,return_value={'version':'9.0.0'}) as update, mock.patch.object(a,'apply_job') as entry:
                a.process_request(self.paths)
            update.assert_called_once();entry.assert_not_called()
            result=json.loads((self.paths.data/'access-result.json').read_text())
            self.assertEqual(result['status'],'failed' if fail else 'complete')
            self.assertFalse((self.paths.data/'access-request.json').exists())

    def test_installer_uses_fixed_argv_and_allows_the_existing_manager_lock(self):
        child=mock.Mock();child.wait.return_value=0
        with mock.patch.object(u.subprocess,'Popen',return_value=child) as launch:
            u.run_installer(Path('/private/verified-source'),io.StringIO())
        self.assertEqual(launch.call_args.args[0],['/bin/bash','/private/verified-source/update.sh','--source','/private/verified-source'])
        self.assertEqual(launch.call_args.kwargs['env']['NARA_MANAGER_LOCK_HELD'],'1')
        child.wait.return_value=1
        with mock.patch.object(u.subprocess,'Popen',return_value=child),self.assertRaisesRegex(ValueError,'rollback'):u.run_installer(Path('/private/source'),io.StringIO())

    def test_timeout_signals_the_installer_to_allow_rollback_before_force_kill(self):
        child=mock.Mock();child.pid=12345;child.wait.side_effect=[u.subprocess.TimeoutExpired('fixture',750),0]
        with mock.patch.object(u.subprocess,'Popen',return_value=child),mock.patch.object(u.os,'killpg') as kill,self.assertRaisesRegex(ValueError,'timed out'):
            u.run_installer(Path('/private/source'),io.StringIO())
        kill.assert_called_once_with(12345,u.signal.SIGTERM)

    def test_failed_backup_is_logged_privately_and_never_starts_the_installer(self):
        with mock.patch.object(u,'download',side_effect=self.responses(self.archive())),mock.patch('nara.maintenance.backup',side_effect=PermissionError('fixture private detail')),mock.patch.object(u,'run_installer') as install,self.assertRaisesRegex(ValueError,'Private backup failed; no update was installed') as error:
            u.apply(self.paths,self.job)
        install.assert_not_called();self.assertNotIn('fixture private detail',str(error.exception))
        log=self.paths.root/'var/log/nara-panel-update.log';self.assertIn('fixture private detail',log.read_text());self.assertEqual(log.stat().st_mode&0o777,0o600)

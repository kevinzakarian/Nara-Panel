import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from nara import maintenance as m
from nara.store import Store
from nara.terminal import input_label


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = m.Layout(Path(self.temp.name))
        self.paths.env.parent.mkdir(parents=True)
        self.paths.unit.parent.mkdir(parents=True)
        self.paths.env.write_text('NARA_PORT=12345\nNARA_WEB_PATH=/SecretPath\nNARA_BIND=0.0.0.0\nNARA_SECURE_COOKIE=0\n')
        self.store = Store(self.paths.data)
        state = self.store.get('state')
        state['settings']['public_url'] = 'http://old.example/SecretPath/'
        self.store.set('state', state)
        self.store.set('active', state)

    def tearDown(self):
        self.temp.cleanup()

    def test_private_backup_includes_committed_wal_and_tls_but_not_logs(self):
        # Keep a WAL connection open while backing up a live database.
        with self.store.connect() as connection:
            connection.execute("INSERT INTO kv VALUES ('backup-proof', '42')")
            connection.commit()
            self.paths.https.mkdir(parents=True)
            (self.paths.https / 'key.pem').write_text('fixture-private-key')
            (self.paths.data / 'core.log').write_text('do not copy logs')
            with contextlib.redirect_stdout(io.StringIO()):
                archive = m.backup(self.paths)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.paths.backups.stat().st_mode & 0o777, 0o700)
            with tarfile.open(archive) as bundle:
                names = bundle.getnames()
                self.assertIn('etc/nara-panel.env', names)
                self.assertIn('etc/nara-panel/https/key.pem', names)
                self.assertNotIn('var/lib/nara-panel/core.log', names)
                data = bundle.extractfile('var/lib/nara-panel/panel.sqlite3').read()
            snapshot = Path(self.temp.name) / 'snapshot.sqlite3'
            snapshot.write_bytes(data)
            with sqlite3.connect(snapshot) as db:
                self.assertEqual(db.execute("SELECT value FROM kv WHERE key='backup-proof'").fetchone()[0], '42')

    def test_root_database_snapshot_runs_as_database_owner(self):
        from types import SimpleNamespace
        source = self.paths.data / 'panel.sqlite3'
        target = Path(self.temp.name) / 'owner-snapshot.sqlite3'
        owner = SimpleNamespace(st_uid=12345, st_gid=12345, st_mode=0o100600)
        original_stat = Path.stat
        def stat(path, *args, **kwargs):
            if path in (source, source.parent):return owner
            return original_stat(path, *args, **kwargs)
        def child(identity, operation, timeout=None):
            self.assertEqual(identity.st_uid,12345);self.assertEqual(timeout,120)
            return operation()
        with mock.patch.object(Path, 'stat', stat), mock.patch.object(m.os, 'geteuid', return_value=0), mock.patch.object(m.os, 'chown'), mock.patch.object(m, '_database_owner_worker', side_effect=child) as worker, mock.patch.object(m, 'run', side_effect=AssertionError('runuser must not be invoked')):
            m.snapshot_database(source, target)
            worker.assert_called_once()
        with sqlite3.connect(target) as database:
            self.assertIsNotNone(database.execute("SELECT value FROM kv WHERE key='state'").fetchone())
        self.assertEqual(list(self.paths.data.glob('.nara-backup-*')), [])

    def test_database_snapshot_rejects_symlinks_and_does_not_create_a_missing_database(self):
        source=self.paths.data/'panel.sqlite3';link=self.paths.data/'linked.sqlite3';link.symlink_to(source)
        target=Path(self.temp.name)/'snapshot.sqlite3'
        with self.assertRaisesRegex(ValueError,'file type'):m.snapshot_database(link,target)
        with self.assertRaises(FileNotFoundError):m.snapshot_database(self.paths.data/'missing.sqlite3',target)
        self.assertFalse(target.exists())

    def test_owner_worker_timeout_reaps_the_child(self):
        identity=self.paths.data.stat()
        with mock.patch.object(m.os,'fork',return_value=12345),mock.patch.object(m.select,'select',return_value=([],[],[])),mock.patch.object(m.os,'kill') as kill,mock.patch.object(m.os,'waitpid') as wait,self.assertRaisesRegex(ValueError,'timed out'):
            m._database_owner_worker(identity,lambda:None,timeout=.01)
        kill.assert_called_once_with(12345,m.signal.SIGKILL);wait.assert_called_once_with(12345,0)

    def test_domain_input_rejects_urls_wildcards_and_configuration_injection(self):
        for value in ('https://a.example.com', 'a.example.com:443', 'a.example.com/foo', '*.example.com', 'x.example.com\n{\nadmin :2019', '-bad.example.com', 'example..com'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.hostname(value, automatic=True)
        for value in ('127.0.0.1', '::1', 'local.test', 'server.local'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.hostname(value, automatic=True)
        self.assertEqual(m.hostname('Panel.Example.COM'), 'panel.example.com')
        self.assertEqual(m.hostname('2001:db8::1'), '2001:db8::1')

    def test_proxy_preserves_full_path_and_has_no_admin_access_logs_or_udp(self):
        value = m.caddyfile('panel.example.com', 10000, '/AbCdEfGh', 'automatic', Path('/etc/nara-panel/https/generation-test'))
        self.assertIn('@panel path /AbCdEfGh /AbCdEfGh/*', value)
        self.assertIn('reverse_proxy 127.0.0.1:10000', value)
        self.assertIn('admin off', value)
        self.assertIn('protocols h1 h2\n', value)
        self.assertNotIn('handle_path', value)
        self.assertNotIn('log ', value)
        self.assertNotIn('tls ', value)
        self.assertIn('https://[2001:db8::1]', m.caddyfile('2001:db8::1', 10000, '', 'self-signed', Path('/tmp/example')))
        for port in (80, 443, 10085):
            with self.assertRaises(ValueError):
                m.caddyfile('panel.example.com', port, '/Entry', 'automatic', Path('/tmp/example'))

    def test_pem_import_rejects_devices_oversized_and_encrypted_files(self):
        pem = Path(self.temp.name) / 'import.pem'
        pem.write_text('-----BEGIN ENCRYPTED PRIVATE KEY-----')
        with self.assertRaisesRegex(ValueError, 'unencrypted'):
            m.read_pem(pem)
        pem.write_bytes(b'x' * 1_000_001)
        with self.assertRaisesRegex(ValueError, '1 MB'):
            m.read_pem(pem)
        with self.assertRaises(ValueError):
            m.read_pem(Path('/dev/zero'))
        with self.assertRaises(ValueError):
            m.read_pem(Path('relative.pem'))

    def test_environment_values_are_data_and_cannot_add_lines(self):
        m.write_env(self.paths.env, {'NARA_PORT': '12345', 'NARA_LITERAL': '$(touch /tmp/never-execute)'})
        self.assertEqual(m.settings(self.paths)['NARA_LITERAL'], '$(touch /tmp/never-execute)')
        with self.assertRaises(ValueError):
            m.write_env(self.paths.env, {'NARA_PORT': '10000\nNARA_BIND=0.0.0.0'})

    def test_public_url_changes_both_models_without_resetting_accounts(self):
        self.store.set('admin', {'username': 'fixture', 'password': 'fixture-hash'})
        m.set_public_url(self.paths, 'https://panel.example.com/SecretPath/')
        for name in ('state', 'active'):
            self.assertEqual(self.store.get(name)['settings']['public_url'], 'https://panel.example.com/SecretPath/')
        self.assertEqual(self.store.get('admin')['username'], 'fixture')

    def https_mocks(self, fail=False):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(m, 'ask', side_effect=lambda label: '' if 'port [' in label else 'panel.example.com'))
        stack.enter_context(mock.patch.object(m.socket, 'getaddrinfo', return_value=[('fixture',)]))
        stack.enter_context(mock.patch.object(m, 'active', return_value=True))
        stack.enter_context(mock.patch.object(m, 'assert_proxy_ports_free'))
        stack.enter_context(mock.patch.object(m, 'port_available', return_value=True))
        stack.enter_context(mock.patch.object(m, 'ensure_caddy'))
        stack.enter_context(mock.patch.object(m.shutil, 'chown'))
        stack.enter_context(mock.patch.object(m, 'panel_health', return_value={'ok': True}))
        stack.enter_context(mock.patch.object(m, 'subscription_health'))
        stack.enter_context(mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
        stack.enter_context(mock.patch.object(m, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='v2.6.2')))
        verifier = stack.enter_context(mock.patch.object(m, 'verify_https', side_effect=ValueError('fixture issuance failure') if fail else None))
        return verifier

    def test_https_success_sets_loopback_secure_cookie_and_public_url(self):
        self.https_mocks()
        with contextlib.redirect_stdout(io.StringIO()):
            m.configure_https(self.paths, 'automatic')
        config = m.settings(self.paths)
        self.assertEqual((config['NARA_BIND'], config['NARA_SECURE_COOKIE']), ('127.0.0.1', '1'))
        self.assertEqual((config['NARA_PORT'], config['NARA_WEB_PATH']), ('12345', '/SecretPath'))
        self.assertEqual(self.store.get('state')['settings']['public_url'], 'https://panel.example.com/SecretPath/')
        self.assertTrue((self.paths.https / 'current').is_symlink())
        self.assertEqual(self.paths.https.parent.stat().st_mode & 0o777, 0o755)
        self.assertIn('User=nara-https', self.paths.unit.read_text())

    def test_failed_certificate_restores_prior_env_proxy_and_public_url(self):
        self.paths.https.mkdir(parents=True)
        previous = self.paths.https / 'generation-prior'
        previous.mkdir()
        (previous / 'Caddyfile').write_text('previous proxy configuration')
        (self.paths.https / 'current').symlink_to(previous.name)
        self.paths.unit.write_text('previous service unit')
        before = self.paths.env.read_text()
        self.https_mocks(fail=True)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'fixture issuance failure'):
            m.configure_https(self.paths, 'automatic')
        self.assertEqual(self.paths.env.read_text(), before)
        self.assertEqual((self.paths.https / 'current').resolve(), previous.resolve())
        self.assertEqual(self.paths.unit.read_text(), 'previous service unit')
        self.assertEqual(self.store.get('state')['settings']['public_url'], 'http://old.example/SecretPath/')
        self.assertEqual(len(list(self.paths.https.glob('generation-*'))), 1)

    def test_busy_proxy_port_does_not_restart_existing_panel(self):
        self.https_mocks()
        with mock.patch.object(m, 'active', side_effect=lambda unit: unit == 'nara-panel'), mock.patch.object(m, 'assert_proxy_ports_free', side_effect=ValueError('port busy')), mock.patch.object(m, 'run') as command, contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'port busy'):
            m.configure_https(self.paths, 'automatic')
        self.assertNotIn(mock.call(['systemctl', 'restart', 'nara-panel']), command.call_args_list)
        self.assertEqual(m.settings(self.paths)['NARA_BIND'], '0.0.0.0')

    def test_failure_after_url_update_restores_urls_and_previous_entry(self):
        self.https_mocks()
        before = self.paths.env.read_text()
        with mock.patch.object(m, 'panel_health', side_effect=[{'ok': True}, ValueError('fixture restart failure')]), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'fixture restart failure'):
            m.configure_https(self.paths, 'automatic')
        self.assertEqual(self.paths.env.read_text(), before)
        for name in ('state', 'active'):
            self.assertEqual(self.store.get(name)['settings']['public_url'], 'http://old.example/SecretPath/')

    def test_reinstall_recreates_dedicated_https_service_from_retained_data(self):
        self.paths.https.mkdir(parents=True)
        previous = self.paths.https / 'generation-retained'
        previous.mkdir()
        (previous / 'Caddyfile').write_text('retained configuration')
        (previous / 'metadata.json').write_text(json.dumps({'host': 'panel.example.com', 'mode': 'automatic', 'url': 'https://panel.example.com/SecretPath/'}))
        (self.paths.https / 'current').symlink_to(previous.name)
        self.https_mocks()
        m.restore_https_service(self.paths)
        self.assertIn('User=nara-https', self.paths.unit.read_text())
        self.assertIn('https://panel.example.com', (self.paths.https / 'current/Caddyfile').read_text())
        self.assertIn(':8443', (self.paths.https / 'current/Caddyfile').read_text())

    def test_old_caddy_upgrade_persists_legacy_mode_for_later_entry_changes(self):
        self.paths.https.mkdir(parents=True)
        generation = self.paths.https / 'generation-old-caddy'
        generation.mkdir()
        (generation / 'Caddyfile').write_text('old single site')
        (generation / 'metadata.json').write_text(json.dumps({'host':'panel.example.com', 'mode':'automatic', 'url':'https://panel.example.com/SecretPath/'}))
        (self.paths.https / 'current').symlink_to(generation.name)
        self.https_mocks()
        with mock.patch.object(m, 'run', side_effect=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout='v2.4.6')):
            m.restore_https_service(self.paths)
        self.assertTrue(json.loads((generation / 'metadata.json').read_text())['legacy'])
        self.assertNotIn('protocols h1 h2', (generation / 'Caddyfile').read_text())
        self.assertIn(':8443', (generation / 'Caddyfile').read_text())

    def test_caddy_package_is_temporarily_masked_without_touching_existing_service(self):
        with mock.patch.object(m.shutil, 'which', return_value=None), mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), mock.patch.object(m, 'run') as command:
            m.ensure_caddy()
            self.assertEqual(command.call_args_list[0].args[0], ['systemctl', 'mask', '--runtime', 'caddy.service'])
            self.assertEqual(command.call_args_list[-1].args[0], ['systemctl', 'unmask', '--runtime', 'caddy.service'])
        with mock.patch.object(m.shutil, 'which', return_value=None), mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), mock.patch.object(m, 'run') as command:
            with self.assertRaises(ValueError):
                m.ensure_caddy()
            command.assert_not_called()

    def test_uninstall_keep_preserves_data_tls_settings_and_private_backup(self):
        self.paths.app.mkdir(parents=True)
        (self.paths.app / 'fixture').write_text('application')
        self.paths.https.mkdir(parents=True)
        (self.paths.https / 'key.pem').write_text('fixture-key')
        with mock.patch.object(m, 'active', return_value=False), mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='loaded', stderr='')), mock.patch.object(m, 'run'), contextlib.redirect_stdout(io.StringIO()):
            m.uninstall(self.paths, '1')
        self.assertFalse(self.paths.app.exists())
        self.assertTrue((self.paths.data / 'panel.sqlite3').exists())
        self.assertTrue(self.paths.env.exists())
        self.assertTrue((self.paths.https / 'key.pem').exists())
        self.assertEqual(len(list(self.paths.backups.glob('*.tar.gz'))), 1)

    def test_uninstall_purge_removes_own_data_but_preserves_existing_backups_and_other_sites(self):
        self.paths.app.mkdir(parents=True)
        self.paths.backups.mkdir(parents=True)
        (self.paths.backups / 'existing.tar.gz').write_text('fixture-backup')
        other = self.paths.root / 'etc/caddy/Caddyfile'
        other.parent.mkdir(parents=True)
        other.write_text('other website')
        with mock.patch.object(m, 'active', return_value=False), mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='loaded', stderr='')), mock.patch.object(m, 'run'), contextlib.redirect_stdout(io.StringIO()):
            m.uninstall(self.paths, '2')
        self.assertFalse(self.paths.data.exists())
        self.assertFalse(self.paths.env.exists())
        self.assertEqual(other.read_text(), 'other website')
        self.assertTrue((self.paths.backups / 'existing.tar.gz').exists())

    def test_uninstall_old_install_skips_missing_optional_units(self):
        self.paths.app.mkdir(parents=True)
        missing = {'nara-panel-access.path','nara-panel-access.service','nara-panel-https'}
        disabled = []
        def systemctl(command, **kwargs):
            if command[1] == 'show':
                return subprocess.CompletedProcess(command, 0, stdout='not-found' if command[-1] in missing else 'loaded', stderr='')
            self.assertEqual(command[1:3], ['disable','--now'])
            disabled.append(command[-1])
            self.assertNotIn(command[-1], missing)
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
        output=io.StringIO()
        with mock.patch.object(m,'active',return_value=False),mock.patch.object(m.subprocess,'run',side_effect=systemctl),mock.patch.object(m,'run'),contextlib.redirect_stdout(output):
            m.uninstall(self.paths,'2')
        self.assertEqual(disabled,['nara-panel'])
        self.assertFalse(self.paths.app.exists())
        self.assertIn('NARA removed',output.getvalue())

    def test_uninstall_real_systemctl_failure_preserves_application_files(self):
        self.paths.app.mkdir(parents=True)
        def systemctl(command, **kwargs):
            return subprocess.CompletedProcess(command, 1 if command[1]=='disable' else 0, stdout='loaded', stderr='Access denied')
        with mock.patch.object(m.subprocess,'run',side_effect=systemctl),self.assertRaisesRegex(ValueError,'Access denied'):
            m.uninstall(self.paths,'2')
        self.assertTrue(self.paths.app.exists())
        self.assertTrue(self.paths.env.exists())
        self.assertTrue(self.paths.data.exists())

    def test_uninstall_systemd_inspection_failure_is_not_treated_as_missing(self):
        self.paths.app.mkdir(parents=True)
        with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1,stdout='',stderr='Failed to connect to bus')),self.assertRaisesRegex(ValueError,'connect to bus'):
            m.uninstall(self.paths,'2')
        self.assertTrue(self.paths.app.exists())

    def test_uninstall_does_not_skip_active_unit_with_missing_file(self):
        self.paths.app.mkdir(parents=True)
        responses=[subprocess.CompletedProcess([],0,stdout='not-found',stderr=''),subprocess.CompletedProcess([],1,stdout='',stderr='Unit file missing')]
        with mock.patch.object(m,'active',return_value=True),mock.patch.object(m.subprocess,'run',side_effect=responses) as command,self.assertRaisesRegex(ValueError,'disable/stop'):
            m.uninstall(self.paths,'2')
        self.assertEqual(command.call_args_list[-1].args[0][1:3],['disable','--now'])
        self.assertTrue(self.paths.app.exists())

    def test_uninstall_aborts_if_service_cannot_stop(self):
        self.paths.app.mkdir(parents=True)
        with mock.patch.object(m, 'active', return_value=True), mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='loaded', stderr='')), self.assertRaises(ValueError):
            m.uninstall(self.paths, '2')
        self.assertTrue(self.paths.app.exists())
        self.assertTrue(self.paths.env.exists())

    def test_ansi_is_optional_but_input_marker_is_always_present(self):
        stream = mock.Mock()
        stream.isatty.return_value = True
        with mock.patch.dict(os.environ, {'TERM': 'xterm-256color'}, clear=True):
            self.assertIn('\033[1;36m', input_label('Domain:', stream))
            with mock.patch.dict(os.environ, {'NO_COLOR': ''}):
                self.assertEqual(input_label('Domain:', stream), '  [INPUT] Domain:')
        stream.isatty.return_value = False
        self.assertEqual(input_label('Domain:', stream), '  [INPUT] Domain:')


class RealHTTPSProbeTests(unittest.TestCase):
    def test_tls_probe_checks_certificate_hostname_and_prefixed_health(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory) / 'cert.pem', Path(directory) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-days', '1', '-subj', '/CN=panel.example.com', '-addext', 'subjectAltName=DNS:panel.example.com', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200 if self.path == '/Prefix/api/health' else 404)
                    self.end_headers()
                def log_message(self, *_):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original = socket.create_connection
            try:
                with mock.patch.object(m.socket, 'create_connection', side_effect=lambda _, **kw: original(server.server_address, **kw)):
                    m.verify_https('panel.example.com', '/Prefix', cert, timeout=0)
                    with self.assertRaises(ValueError):
                        m.verify_https('wrong.example.com', '/Prefix', cert, timeout=0)
                    with self.assertRaises(ValueError):
                        m.verify_https('panel.example.com', '/WrongPath', cert, timeout=0)
            finally:
                server.shutdown()
                server.server_close()


class ShellManagerTests(unittest.TestCase):
    def shell(self, script):
        return subprocess.run(['bash', '-c', 'source scripts/manage.sh\n' + script], capture_output=True, text=True)

    def test_system_upgrade_precedes_dependency_install(self):
        result = self.shell('apt-get() { printf "APT %s\\n" "$*"; }\nprepare_system')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index('APT update'), result.stdout.index('upgrade -y'))
        self.assertLess(result.stdout.index('upgrade -y'), result.stdout.index('install -y'))
        self.assertNotIn('dist-upgrade', result.stdout)
        self.assertNotIn('autoremove', result.stdout)

    def test_upgrade_failure_stops_before_dependencies_or_menu(self):
        result = self.shell('apt-get() { printf "APT %s\\n" "$*"; if [[ $* == *upgrade* ]]; then return 42; fi; }\nprepare_system\nprintf "UNREACHABLE"')
        self.assertEqual(result.returncode, 42)
        self.assertNotIn('install -y', result.stdout)
        self.assertNotIn('UNREACHABLE', result.stdout)

    def test_menu_uses_controlling_tty_with_piped_stdin_and_recovers_bad_choice(self):
        import errno
        import pty
        import select
        import time
        with tempfile.TemporaryDirectory() as directory:
            script = "source scripts/manage.sh\nuname() { echo Linux; }\nid() { echo 0; }\napt-get() { printf 'APT %s\\n' \"$*\"; }\nsystemctl() { return 0; }\napp_dir=" + directory + "/not-installed\nmanager_main --lock-held"
            pid, master = pty.fork()
            if pid == 0:
                os.environ['TERM'] = 'xterm-256color'
                os.environ.pop('NO_COLOR', None)
                descriptor = os.open(os.devnull, os.O_RDONLY)
                os.dup2(descriptor, 0)
                os.close(descriptor)
                os.execvp('bash', ['bash', '-c', script])
            output = b''
            os.write(master, b'bad-choice\n\n0\n')
            deadline = time.monotonic() + 10
            try:
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], .2)
                    if ready:
                        try:
                            block = os.read(master, 65536)
                        except OSError as exc:
                            if exc.errno == errno.EIO:
                                break
                            raise
                        if not block:
                            break
                        output += block
                else:
                    os.kill(pid, 15)
                    self.fail('Menu did not exit: ' + repr(output))
            finally:
                os.close(master)
                _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, repr(output))
            self.assertIn(b'\033[1m\033[36m  [INPUT]', output)
            self.assertIn(b'Choose a number from the menu', output)
            self.assertIn(b'Press Enter to return to the menu', output)
            self.assertLess(output.index(b'APT update'), output.index(b'Server manager'))

    def test_action_failure_does_not_fall_through_under_subshell_dispatch(self):
        # The manager deliberately does not use `if action` / `action || ...`,
        # which silently disable Bash errexit inside nested functions.
        result = self.shell('upgrade_panel() { false; printf "UNREACHABLE"; }\nset +e\n( set -e; case 2 in 2) upgrade_panel ;; esac )\ncode=$?\nset -e\nprintf "RESULT=%s" "$code"')
        self.assertEqual(result.returncode, 0)
        self.assertIn('RESULT=1', result.stdout)
        self.assertNotIn('UNREACHABLE', result.stdout)

class InstallerRollbackTests(unittest.TestCase):
    def test_failed_readiness_restores_application_core_venv_and_entry_files(self):
        # Run the actual shell installer against mapped temporary filesystem paths
        # and fake OS commands. No package manager, account or systemd is changed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            app = root / 'opt/nara-panel'
            fakebin = root / 'fakebin'
            fakebin.mkdir()
            (source / 'scripts').mkdir(parents=True)
            (source / 'deploy').mkdir()
            for item in ('nara', 'web', 'scripts', 'bin', '.venv/bin'):
                (app / item).mkdir(parents=True, exist_ok=True)
                (app / item / 'original-marker').write_text('old-' + item)
            (app / 'requirements.txt').write_text('old dependencies')
            for item in ('nara', 'web'):
                (source / item).mkdir()
                (source / item / 'new-marker').write_text('new code')
            (source / 'requirements.txt').write_text('new dependencies')
            (source / 'deploy/nara-panel.service').write_text('new service')
            (source / 'deploy/nara-panel-access.path').write_text('fixture path unit')
            (source / 'deploy/nara-panel-access.service').write_text('fixture oneshot unit')
            (source / 'scripts/nara-command.sh').write_text('#!/bin/sh\nexit 0\n')
            (source / 'scripts/terminal.sh').write_text(Path('scripts/terminal.sh').read_text())
            env = root / 'etc/nara-panel.env'
            env.parent.mkdir(parents=True)
            env.write_text('NARA_PORT=12345\nNARA_WEB_PATH=/Existing\n')
            unit = root / 'etc/systemd/system/nara-panel.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('old service')
            command = root / 'usr/local/bin/nara'
            command.parent.mkdir(parents=True)
            command.write_text('old manager')
            log = root / 'systemctl.log'
            scripts = {
                'uname': 'echo Linux',
                'id': 'echo 0',
                'systemctl': 'echo "$*" >> "$NARA_TEST_LOG"; exit 0',
                'install': 'if [ "${1:-}" = -d ]; then shift; while [ $# -gt 0 ] && [ "${1#-}" != "$1" ]; do shift 2; done; mkdir -p "$@"; else shift 2; cp "$1" "$2"; fi',
                'runuser': 'exit 0',
                'chown': 'exit 0',
                'python3': '''if [ "${2:-}" = venv ]; then
    mkdir -p "$3/bin"
    cp "$NARA_TEST_PYTHON" "$3/bin/python"
    chmod +x "$3/bin/python"
fi
exit 0''',
            }
            fake_python = root / 'new-python'
            fake_python.write_text('#!/bin/sh\nif [ "${2:-}" = pip ] || [ "${1:-}" = -c ]; then exit 0; fi\nexit 37\n')
            fake_python.chmod(0o755)
            old_python = app / '.venv/bin/python'
            old_python.write_text('#!/bin/sh\necho original-python\n')
            old_python.chmod(0o755)
            for name, body in scripts.items():
                target = fakebin / name
                target.write_text('#!/bin/sh\n' + body + '\n')
                target.chmod(0o755)
            core = root / 'new-core'
            core.write_text('#!/bin/sh\necho "with_v2ray_api with_quic"\n')
            core.chmod(0o755)
            script = Path('scripts/install.sh').read_text()
            for path in ('/opt/nara-panel', '/etc/nara-panel.env', '/etc/systemd/system', '/usr/local/bin/nara', '/var/lib/nara-panel', '/etc/nara-panel/https'):
                script = script.replace(path, str(root) + path)
            target = source / 'scripts/install.sh'
            target.write_text(script)
            result = subprocess.run(['sh', str(target)], env={**os.environ, 'PATH': str(fakebin) + ':' + os.environ['PATH'], 'NARA_KEEP_ENTRY': '1', 'NARA_MANAGER_LOCK_HELD': '1', 'NARA_INSTALL_CORE': str(core), 'NARA_TEST_PYTHON': str(fake_python), 'NARA_TEST_LOG': str(log)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
            self.assertIn('restoring the previous application', result.stdout)
            self.assertEqual((app / 'nara/original-marker').read_text(), 'old-nara')
            self.assertFalse((app / 'nara/new-marker').exists())
            self.assertEqual((app / 'bin/original-marker').read_text(), 'old-bin')
            self.assertIn('original-python', old_python.read_text())
            self.assertEqual(env.read_text(), 'NARA_PORT=12345\nNARA_WEB_PATH=/Existing\n')
            self.assertEqual(unit.read_text(), 'old service')
            self.assertEqual(command.read_text(), 'old manager')
            self.assertTrue(log.read_text().rstrip().endswith('start nara-panel'))

CADDIES = [path for path in os.environ.get('NARA_TEST_CADDY_BINARIES', '').split(os.pathsep) if path]


@unittest.skipUnless(CADDIES, 'Set NARA_TEST_CADDY_BINARIES for official Caddy proxy integration')
class RealCaddyProxyTests(unittest.TestCase):
    def test_generated_configs_proxy_real_nara_auth_with_secure_cookie_and_path(self):
        import http.client
        import re
        import time
        from nara.server import make_handler
        from nara.runtime import Runtime
        from nara.store import password_hash
        for binary in CADDIES:
            for test_host in ('panel.example.com', '203.0.113.42'):
                with self.subTest(binary=binary, host=test_host), tempfile.TemporaryDirectory() as directory:
                    directory = Path(directory)
                    installed = subprocess.check_output([binary, 'version'], text=True)
                    match = re.search(r'v?(\d+)\.(\d+)\.', installed)
                    legacy = tuple(map(int, match.groups())) < (2, 6)
                    cert, key = directory / 'cert.pem', directory / 'key.pem'
                    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-days', '1', '-subj', '/CN=' + test_host, '-addext', 'subjectAltName=' + ('IP:' if test_host[0].isdigit() else 'DNS:') + test_host, '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
                    store = Store(directory / 'store')
                    store.set('admin', {'username': 'admin', 'password': password_hash('fixture-only-password')})
                    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(store, Runtime(store, '/nonexistent'), Path('web'), secure_cookie=True, web_path='/Entry'))
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    with socket.socket() as sock:
                        sock.bind(('127.0.0.1', 0))
                        proxy_port = sock.getsockname()[1]
                    config = m.caddyfile(test_host, server.server_port, '/Entry', 'self-signed', directory, legacy=legacy)
                    # Keep tests on ephemeral loopback ports; disable only redirects,
                    # with explicit certs, so no ACME/80/443 or trust-store changes occur.
                    config = config.replace('    admin off', '    admin off\n    auto_https disable_redirects')
                    config = config.replace('https://' + test_host + ' {', 'https://' + test_host + ':' + str(proxy_port) + ' {\n    bind 127.0.0.1')
                    file = directory / 'Caddyfile'
                    file.write_text(config)
                    environ = {**os.environ, 'XDG_DATA_HOME': str(directory / 'xdg-data'), 'XDG_CONFIG_HOME': str(directory / 'xdg-config')}
                    automatic = directory / 'Automatic.Caddyfile'
                    automatic.write_text(m.caddyfile('panel.example.com', server.server_port, '/Entry', 'automatic', directory, legacy=legacy))
                    automatic_check = subprocess.run([binary, 'adapt', '--config', str(automatic), '--adapter', 'caddyfile'], capture_output=True, text=True, env=environ)
                    self.assertEqual(automatic_check.returncode, 0, automatic_check.stderr)
                    adapted = subprocess.run([binary, 'adapt', '--config', str(file), '--adapter', 'caddyfile'], capture_output=True, text=True, env=environ)
                    self.assertEqual(adapted.returncode, 0, adapted.stderr)
                    self.assertTrue(json.loads(adapted.stdout)['admin']['disabled'])
                    with open(directory / 'caddy.log', 'w') as logs:
                        process = subprocess.Popen([binary, 'run', '--config', str(file), '--adapter', 'caddyfile'], stdout=logs, stderr=logs, env=environ)
                        original_connection = socket.create_connection
                        context = ssl.create_default_context(cafile=str(cert))
                        class Connection(http.client.HTTPSConnection):
                            def connect(self):
                                raw = original_connection(('127.0.0.1', proxy_port), timeout=3)
                                self.sock = context.wrap_socket(raw, server_hostname=test_host)
                        def request(method, path, body=None, headers=None):
                            connection = Connection(test_host, proxy_port, timeout=3, context=context)
                            connection.request(method, path, body, headers or {})
                            response = connection.getresponse()
                            result = response.status, dict(response.getheaders()), response.read()
                            connection.close()
                            return result
                        try:
                            deadline = time.monotonic() + 10
                            while True:
                                try:
                                    ready = request('GET', '/Entry/api/health')
                                    if ready[0] == 200:
                                        break
                                except OSError:
                                    pass
                                if time.monotonic() > deadline or process.poll() is not None:
                                    self.fail('Proxy failed: ' + (directory / 'caddy.log').read_text())
                                time.sleep(.1)
                            self.assertEqual(request('GET', '/outside')[0], 404)
                            status, headers, body = request('POST', '/Entry/api/login', json.dumps({'username': 'admin', 'password': 'fixture-only-password'}), {'Content-Type': 'application/json', 'Origin': 'https://' + test_host + ':' + str(proxy_port)})
                            self.assertEqual(status, 200, body)
                            self.assertIn('; Secure', headers['Set-Cookie'])
                            self.assertIn('Path=/Entry/', headers['Set-Cookie'])
                            self.assertEqual(request('GET', '/Entry/api/state', headers={'Cookie': headers['Set-Cookie'].split(';')[0]})[0], 200)
                        finally:
                            process.terminate()
                            process.wait(timeout=5)
                            server.shutdown()
                            server.server_close()

    def test_two_https_ports_keep_subscription_and_administration_separate(self):
        import http.client
        import time
        from nara.server import make_handler
        from nara.runtime import Runtime
        from nara.store import password_hash
        from tests.helpers import example_state, free_port
        for binary in CADDIES:
            with self.subTest(binary=binary), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                legacy = 'v2.4.' in subprocess.check_output([binary, 'version'], text=True)
                cert, key = directory / 'cert.pem', directory / 'key.pem'
                subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=panel.example.com','-addext','subjectAltName=DNS:panel.example.com','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
                store = Store(directory / 'store')
                state = example_state(); store.set('state',state)
                runtime = Runtime(store,'/nonexistent'); runtime.active = state
                servers = [ThreadingHTTPServer(('127.0.0.1',0), make_handler(store,runtime,Path('web'),web_path=path,role=role)) for path,role in [('/PrivatePanel','panel'),('/Downloads','subscription')]]
                for server in servers:
                    threading.Thread(target=server.serve_forever,daemon=True).start()
                panel_port, sub_port = free_port(), free_port()
                config={'NARA_PORT':str(servers[0].server_port),'NARA_SUB_PORT':str(servers[1].server_port),'NARA_WEB_PATH':'/PrivatePanel','NARA_SUB_PATH':'/Downloads','NARA_PUBLIC_PANEL_PORT':str(panel_port),'NARA_PUBLIC_SUB_PORT':str(sub_port)}
                text=m.proxy_config('panel.example.com',config,'self-signed',directory,legacy=legacy).replace('    admin off','    admin off\n    auto_https disable_redirects')
                for port in (panel_port,sub_port):
                    text=text.replace('https://panel.example.com:'+str(port)+' {','https://panel.example.com:'+str(port)+' {\n    bind 127.0.0.1')
                file=directory/'Caddyfile';file.write_text(text)
                environ={**os.environ,'XDG_DATA_HOME':str(directory/'xdg-data'),'XDG_CONFIG_HOME':str(directory/'xdg-config')}
                context=ssl.create_default_context(cafile=str(cert))
                connection_factory=socket.create_connection
                class Connection(http.client.HTTPSConnection):
                    def connect(self):
                        self.sock=context.wrap_socket(connection_factory(('127.0.0.1',self.port),timeout=3),server_hostname='panel.example.com')
                def request(port,path,method='GET'):
                    connection=Connection('panel.example.com',port,timeout=3,context=context)
                    connection.request(method,path)
                    response=connection.getresponse();data=response.read();result=response.status,data
                    connection.close();return result
                with open(directory/'caddy.log','w') as log:
                    process=subprocess.Popen([binary,'run','--config',str(file),'--adapter','caddyfile'],stdout=log,stderr=log,env=environ)
                    try:
                        deadline=time.monotonic()+10
                        while True:
                            try:
                                if request(panel_port,'/PrivatePanel/api/health')[0]==200: break
                            except OSError: pass
                            if time.monotonic()>deadline or process.poll() is not None:
                                self.fail((directory/'caddy.log').read_text())
                            time.sleep(.1)
                        self.assertEqual(request(panel_port,'/PrivatePanel/')[0],200)
                        self.assertEqual(request(panel_port,'/Downloads/'+state['clients'][0]['token'])[0],404)
                        status,profile=request(sub_port,'/Downloads/'+state['clients'][0]['token'])
                        self.assertEqual(status,200)
                        self.assertIn('outbounds',json.loads(profile))
                        for path in ('/PrivatePanel/','/Downloads/','/Downloads/api/login','/Downloads/api/state','/Downloads/app.js'):
                            self.assertEqual(request(sub_port,path)[0],404,path)
                            self.assertEqual(request(sub_port,path,'POST')[0],404,path)
                    finally:
                        process.terminate();process.wait(timeout=5)
                        for server in servers:
                            server.shutdown();server.server_close()

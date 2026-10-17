"""Fixed operations for entry settings and verified stable panel upgrades.

The unprivileged web service requests allow-listed entry values or a version.
The root oneshot restores entry settings on readiness failure and delegates
fixed-source upgrades to panel_update. Request data is never evaluated as code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile
import time
from urllib.parse import urlsplit
from .install_config import normalize_web_path, panel_port, read_env, port_available

FIELDS = ('web_path', 'panel_port', 'sub_path', 'subscription_port')


def validate(values, stats_port=10085):
    if not isinstance(values, dict) or set(values) != set(FIELDS):
        raise ValueError('Provide webPath, panel port, subPath and subscription port')
    if not all(isinstance(values[key], str) for key in ('web_path', 'sub_path')):
        raise ValueError('Paths must be text')
    result = {key: normalize_web_path(values[key]) for key in ('web_path', 'sub_path')}
    result.update({key: panel_port(values[key]) for key in ('panel_port', 'subscription_port')})
    if not result['web_path'] or not result['sub_path'] or result['web_path'] == result['sub_path']:
        raise ValueError('Choose two different nonempty paths')
    if len({result['panel_port'], result['subscription_port'], int(stats_port)}) != 3:
        raise ValueError('Panel, subscription and statistics ports must be different')
    return result


def from_env(config):
    return {'web_path': normalize_web_path(config.get('NARA_WEB_PATH', '')),
            'panel_port': int(config.get('NARA_PUBLIC_PANEL_PORT') or config.get('NARA_PORT', 10000)),
            'sub_path': normalize_web_path(config.get('NARA_SUB_PATH', '/subscriptions')),
            'subscription_port': int(config.get('NARA_PUBLIC_SUB_PORT') or config.get('NARA_SUB_PORT', 10001))}


def signature(values):
    return hashlib.sha256(json.dumps({key: values[key] for key in FIELDS}, sort_keys=True).encode()).hexdigest()


def public_url(host, port, path, scheme='http'):
    authority = '[' + host + ']' if ':' in host else host
    if int(port) != (443 if scheme == 'https' else 80):
        authority += ':' + str(port)
    return scheme + '://' + authority + path + '/'


def change_url(current, values, scheme=None, host=None):
    parsed = urlsplit(current)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Invalid panel address')
    return public_url(host or parsed.hostname, values['panel_port'], values['web_path'], scheme or parsed.scheme)


class Access:
    def __init__(self, directory, config):
        self.directory = Path(directory)
        self.config = dict(config)
        self.values = from_env(config)

    def info(self):
        return {**self.values, 'revision': signature(self.values),
                'managed': self.config.get('NARA_ACCESS_MANAGED') == '1',
                'subscription_scheme': self.config.get('NARA_SUB_SCHEME', 'http'),
                'public_host': self.config.get('NARA_PUBLIC_HOST', '')}

    def request(self, values, expected, current_url):
        if not self.info()['managed']:
            raise ValueError('Run the Linux installer to enable entry changes from Settings. Containers/manual services use their environment configuration.')
        values = validate(values, self.config.get('NARA_STATS_PORT', 10085))
        if expected != signature(self.values):
            raise ValueError('Entry settings changed; refresh this page first')
        protected = {int(self.config.get('NARA_STATS_PORT', 10085))}
        if self.config.get('NARA_PUBLIC_HOST'):
            protected.update((int(self.config['NARA_PORT']), int(self.config['NARA_SUB_PORT'])))
            protected.add(80)  # Managed ACME/HTTP redirect listener.
        if values['panel_port'] in protected or values['subscription_port'] in protected:
            raise ValueError('A selected port is reserved for the internal service or certificate renewal')
        url = change_url(current_url, values, host=self.info()['public_host'] or None,
                         scheme='https' if self.info()['public_host'] else None)
        job = {'id': secrets.token_urlsafe(24), 'expected': expected, 'values': values, 'created_at': time.time()}
        self.queue(job)
        return {'id': job['id'], 'url': url, 'values': values}

    def request_update(self, version):
        from .panel_update import target
        if not self.info()['managed']:
            raise ValueError('Use the Linux installer once to enable panel updates; containers use their image update process')
        job = {'id':secrets.token_urlsafe(24), 'operation':'update-panel', 'version':target(version), 'created_at':time.time()}
        self.queue(job)
        return {'id':job['id'], 'version':job['version']}

    def queue(self, job):
        descriptor, temporary = tempfile.mkstemp(prefix='.access-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'w') as file:
                json.dump(job, file)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, self.directory / 'access-request.json')
            except FileExistsError as exc:
                raise ValueError('Another maintenance operation is in progress; wait and refresh') from exc
        finally:
            Path(temporary).unlink(missing_ok=True)

    def status(self, job_id):
        path = self.directory / 'access-result.json'
        if path.exists():
            result = json.loads(path.read_text())
            if result.get('id') == job_id:
                return result
        return {'id': job_id, 'status': 'pending'}


def apply_job(paths, job):
    from . import maintenance as m
    from .runtime import atomic_write
    config = m.settings(paths)
    current = from_env(config)
    if job.get('expected') != signature(current):
        raise ValueError('Entry settings changed; reload Settings before trying again')
    values = validate(job.get('values'), config.get('NARA_STATS_PORT', 10085))
    old_ports = {current['panel_port'], current['subscription_port']}
    https = (paths.https / 'current/metadata.json').exists()
    reserved = {int(config.get('NARA_STATS_PORT', 10085))} | m.configured_inbound_ports(paths)
    if https:
        reserved.update({80, int(config['NARA_PORT']), int(config['NARA_SUB_PORT'])})
    for key in ('panel_port', 'subscription_port'):
        if values[key] in reserved:
            raise ValueError('That port is reserved for the internal service or certificate renewal')
        if values[key] not in old_ports and not port_available(values[key]):
            raise ValueError('Port ' + str(values[key]) + ' is already in use; previous settings were kept')
    # A port swap is supported: both owned listeners stop together below.
    original_env = paths.env.read_text()
    original_metadata = (paths.https / 'current/metadata.json').read_text() if https else None
    original_proxy = (paths.https / 'current/Caddyfile').read_text() if https else None
    old_urls = None
    was_running = m.active('nara-panel')
    proxy_running = https and m.active('nara-panel-https')
    config.update(NARA_WEB_PATH=values['web_path'], NARA_SUB_PATH=values['sub_path'])
    if https:
        config.update(NARA_PUBLIC_PANEL_PORT=str(values['panel_port']), NARA_PUBLIC_SUB_PORT=str(values['subscription_port']))
    else:
        config.update(NARA_PORT=str(values['panel_port']), NARA_SUB_PORT=str(values['subscription_port']))
    changed = False
    try:
        if https:
            metadata = json.loads(original_metadata)
            proxy = m.proxy_config(metadata['host'], config, metadata['mode'], (paths.https / 'current').resolve(), metadata.get('legacy', False))
            # Validate the staged config before stopping either live service.
            descriptor, candidate = tempfile.mkstemp(prefix='access-', suffix='.Caddyfile', dir=paths.https)
            os.close(descriptor)
            try:
                Path(candidate).write_text(proxy)
                m.run(['caddy', 'validate', '--config', candidate, '--adapter', 'caddyfile'], stdout=m.subprocess.DEVNULL)
            finally:
                Path(candidate).unlink(missing_ok=True)
        m.run(['systemctl', 'stop', 'nara-panel'])
        changed = True
        if https:
            m.run(['systemctl', 'stop', 'nara-panel-https'])
        m.write_env(paths.env, config)
        if https:
            atomic_write(paths.https / 'current/Caddyfile', proxy)
            atomic_write(paths.https / 'current/metadata.json', json.dumps({**metadata,
                'url': public_url(metadata['host'], values['panel_port'], values['web_path'], 'https'),
                'subscription_url': public_url(metadata['host'], values['subscription_port'], values['sub_path'], 'https')}))
            for file in ('Caddyfile', 'metadata.json'):
                shutil.chown(paths.https / ('current/' + file), user='root', group='nara-https')
                (paths.https / ('current/' + file)).chmod(0o640)
        old_urls = m.update_access_urls(paths, values, config)
        m.run(['systemctl', 'start', 'nara-panel'])
        m.panel_health(paths)
        m.subscription_health(paths)
        if https:
            m.run(['systemctl', 'start', 'nara-panel-https'])
            cert = paths.https / 'current/cert.pem' if metadata['mode'] == 'self-signed' else None
            m.verify_https(metadata['host'], values['web_path'], cert, port=values['panel_port'])
            m.verify_https(metadata['host'], values['sub_path'], cert, port=values['subscription_port'])
    except Exception:
        if changed:
            m.run(['systemctl', 'stop', 'nara-panel'])
            m.write_env(paths.env, read_env_text(original_env))
            if https:
                m.subprocess.run(['systemctl', 'stop', 'nara-panel-https'], check=False)
                atomic_write(paths.https / 'current/Caddyfile', original_proxy)
                atomic_write(paths.https / 'current/metadata.json', original_metadata)
                for file in ('Caddyfile', 'metadata.json'):
                    shutil.chown(paths.https / ('current/' + file), user='root', group='nara-https')
                    (paths.https / ('current/' + file)).chmod(0o640)
            if old_urls is not None:
                m.restore_access_urls(paths, old_urls)
            if was_running:
                m.run(['systemctl', 'start', 'nara-panel'])
            if proxy_running:
                m.run(['systemctl', 'start', 'nara-panel-https'])
        raise
    return values


def read_env_text(value):
    return dict(line.split('=', 1) for line in value.splitlines() if line and not line.lstrip().startswith('#') and '=' in line)


def process_request(paths, blocked_error=None):
    request = paths.data / 'access-request.json'
    job = {}
    try:
        descriptor = os.open(request, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as source:
            details = os.fstat(source.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_size > 16384:
                raise ValueError('Invalid entry change request')
            payload = json.loads(source.read(16385))
        if not isinstance(payload, dict):
            raise ValueError('Invalid entry change request')
        job = payload
        if not isinstance(job.get('id'), str) or len(job['id']) > 64 or not isinstance(job.get('created_at'), (int, float)) or abs(time.time() - job['created_at']) > 300:
            raise ValueError('Entry change request expired or is invalid')
        if blocked_error:
            raise ValueError(blocked_error)
        time.sleep(max(0, .5 - max(0, time.time() - job['created_at'])))
        if job.get('operation') == 'update-panel':
            from .panel_update import apply
            values = apply(paths, job)
        else:
            values = apply_job(paths, job)
        result = {'id': job['id'], 'status': 'complete', 'values': values}
    except Exception as exc:
        result = {'id': job.get('id', ''), 'status': 'failed', 'error': str(exc)}
    finally:
        destination = paths.data / 'access-result.json'
        owner = paths.data.stat()
        descriptor, temporary = tempfile.mkstemp(prefix='.access-result-', dir=paths.data)
        try:
            os.fchown(descriptor, owner.st_uid, owner.st_gid)
            with os.fdopen(descriptor, 'w') as file:
                json.dump(result, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        request.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='NARA entry-settings broker')
    parser.add_argument('command', choices=('apply', 'migrate', 'snapshot', 'restore-urls'))
    parser.add_argument('--env', type=Path, default=Path('/etc/nara-panel.env'))
    parser.add_argument('--snapshot', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or os.uname().sysname != 'Linux':
        parser.error('Root on Linux is required')
    from .maintenance import Layout, write_env
    if args.command == 'apply':
        import fcntl
        with open('/run/lock/nara-panel-manager.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                process_request(Layout(), 'Server maintenance is running; try again after it finishes')
            else:
                process_request(Layout())
    elif args.command == 'snapshot':
        from . import maintenance as m
        from .store import Store
        paths = Layout()
        def capture():
            store = Store(paths.data)
            return {name: {key: store.get(name)['settings'].get(key, '') for key in ('public_url', 'subscription_url')} for name in ('state', 'active') if store.get(name)}
        print(json.dumps(m.database_as_owner(paths, capture) if m.needs_database_owner(paths) else capture()))
    elif args.command == 'restore-urls':
        from .maintenance import restore_access_urls
        if not args.snapshot:
            parser.error('Snapshot path is required')
        restore_access_urls(Layout(), json.loads(args.snapshot.read_text()))
    else:
        config = read_env(args.env)
        if not config.get('NARA_SUB_PATH') or not config.get('NARA_SUB_PORT'):
            from .install_config import configure_file
            configure_file(args.env, keep_panel=True)
        else:
            config['NARA_ACCESS_MANAGED'] = '1'
            write_env(args.env, config)


if __name__ == '__main__':
    main()

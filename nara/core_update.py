"""Install only the compatible core pinned by the installed panel release."""
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time

from .native import VERSION
from .updates import version

MANAGED_BINARY = '/opt/nara-panel/bin/sing-box'
MANIFEST = Path(__file__).with_name('core-release.json')
ARCHITECTURES = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}


def compatible_release(path=MANIFEST):
    arch = ARCHITECTURES.get(platform.machine())
    if platform.system() != 'Linux' or not arch:
        return None
    try:
        manifest = json.loads(path.read_text())
        asset = manifest['assets']['linux-' + arch]
        if (manifest['version'] == VERSION
                and re.fullmatch(r'core-v' + re.escape(VERSION) + r'-nara\.[0-9]+', manifest['release_tag'])
                and asset['name'] == f'nara-sing-box-{VERSION}-linux-{arch}.tar.gz'
                and re.fullmatch(r'[a-f0-9]{64}', asset['sha256'])):
            return VERSION
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def status(installed, managed, binary):
    compatible = compatible_release() if managed and binary == MANAGED_BINARY else None
    current = version(installed)
    return {'version': compatible, 'available': bool(compatible and current and version(compatible) > current),
            'managed': bool(managed and binary == MANAGED_BINARY)}


def require_target(requested, installed, pinned):
    current = version(installed)
    if not pinned or requested != pinned or not current or version(pinned) <= current:
        raise ValueError('No newer compatible Sing-box core is approved for this installation.')
    return pinned


def core_info(binary):
    result = subprocess.run([str(binary), 'version'], capture_output=True, text=True, timeout=10, check=True)
    lines = result.stdout.splitlines()
    tags = next((line[6:].strip().split(',') for line in lines if line.startswith('Tags: ')), [])
    return version(lines[0] if lines else ''), set(tags)


def validate_models(paths, candidate, stats_port):
    from .runtime import Runtime
    from .store import Store

    store = Store(paths.data)
    state, active = store.get('state'), store.get('active')
    runtime = Runtime(store, str(candidate), stats_port)
    # Runtime.apply prunes its own generation directory independently.
    with tempfile.TemporaryDirectory(prefix='core-check-', dir=paths.data) as work:
        runtime.run_dir = Path(work)
        runtime.prepare(state)
        if active is not None and active != state:
            runtime.prepare(active)
    return fingerprint(state, active, store.get('autostart', False))


def fingerprint(state, active, autostart):
    payload = json.dumps([state, active, autostart], sort_keys=True, separators=(',', ':')).encode()
    return [hashlib.sha256(payload).hexdigest(), bool(active and autostart)]


def snapshot(paths):
    from .store import Store
    store = Store(paths.data)
    return fingerprint(store.get('state'), store.get('active'), store.get('autostart', False))


def verify_health(paths, expected_running):
    from . import maintenance as m
    deadline = time.monotonic() + 35
    stable = None
    while time.monotonic() < deadline:
        health = m.panel_health(paths, timeout=3)
        if health.get('core_running') is expected_running:
            stable = stable or time.monotonic()
            if time.monotonic() - stable >= 2:
                m.subscription_health(paths)
                return
        else:
            stable = None
        time.sleep(.5)
    raise ValueError('The core did not stay in its expected running state.')


def apply(paths, job):
    from . import maintenance as m
    from .access import write_result

    if set(job) != {'id', 'operation', 'version', 'created_at'} or job['operation'] != 'update-core':
        raise ValueError('Invalid core update request')
    config = m.settings(paths)
    if config.get('NARA_ACCESS_MANAGED') != '1' or config.get('NARA_CORE', MANAGED_BINARY) != MANAGED_BINARY:
        raise ValueError('Core updates require a managed Linux installation using the bundled core.')
    live = paths.app / 'bin'
    if (live.is_symlink() or (live / 'sing-box').is_symlink()
            or not (live / 'sing-box').is_file() or not m.needs_database_owner(paths)):
        raise ValueError('The bundled core or the panel service account is not configured as expected.')
    pinned = compatible_release(paths.app / 'nara/core-release.json')
    if not pinned or job['version'] != pinned:
        raise ValueError('No compatible Sing-box core is approved for this request.')

    def as_owner(operation, timeout=25):
        return m._database_owner_worker(paths.data.stat(), operation, timeout=timeout)

    def progress(percent, stage):
        write_result(paths, {'id': job['id'], 'status': 'running', 'progress': percent, 'stage': stage})

    def installed_version():
        current, _ = core_info(live / 'sing-box')
        return '.'.join(map(str, current)) if current else ''

    target = require_target(job['version'], as_owner(installed_version), pinned)
    work = Path(tempfile.mkdtemp(prefix='.nara-core-update-', dir=paths.app))
    keep_backup = False
    try:
        # The unprivileged validator can read the verified bundle, but cannot change it.
        work.chmod(0o755)
        staged, previous = work / 'staged', work / 'previous'
        progress(10, 'Downloading the verified compatible core')
        try:
            subprocess.run([str(paths.app / '.venv/bin/python'), str(paths.app / 'scripts/fetch-core.py'),
                            '--manifest', str(paths.app / 'nara/core-release.json'), '--output', str(staged)],
                           check=True, timeout=650)
            staged.chmod(0o755)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Could not download or verify the compatible core. The installed core was kept.') from None
        progress(35, 'Checking saved and active configurations with the candidate')
        try:
            def preflight():
                candidate = staged / 'sing-box'
                actual, tags = core_info(candidate)
                if actual != version(target) or not {'with_quic', 'with_v2ray_api'} <= tags:
                    raise ValueError('Core version or required capabilities do not match.')
                return validate_models(paths, candidate, int(config.get('NARA_STATS_PORT', 10085)))
            checked = as_owner(preflight, timeout=150)
        except Exception:
            raise ValueError('The new core did not pass configuration checks. The installed core was kept. See the private core log.') from None
        health = m.panel_health(paths, timeout=5)
        expect_running = checked[1]
        if health.get('core_running') is not expect_running:
            raise ValueError('The core is not in its expected state. Check its status before updating.')
        progress(55, 'Creating a private server backup')
        m.backup(paths)
        stopped = switched = False
        def interrupted(*_):
            raise InterruptedError('Core update interrupted')
        old_handler = signal.signal(signal.SIGTERM, interrupted)
        try:
            progress(70, 'Switching to the verified core')
            stopped = True
            m.run(['systemctl', 'stop', 'nara-panel'], timeout=60)
            if as_owner(lambda: snapshot(paths)) != checked:
                raise ValueError('Settings changed during verification. Retry the core update.')
            live.rename(previous)
            staged.rename(live)
            switched = True
            m.run(['systemctl', 'start', 'nara-panel'], timeout=30)
            progress(90, 'Checking panel, subscriptions and core startup')
            verify_health(paths, expect_running)
        except BaseException as failure:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if stopped:
                try:
                    if previous.exists():
                        if switched or live.exists():
                            m.run(['systemctl', 'stop', 'nara-panel'], timeout=60)
                            live.rename(staged)
                        previous.rename(live)
                    m.run(['systemctl', 'start', 'nara-panel'], timeout=30)
                    verify_health(paths, expect_running)
                except Exception:
                    keep_backup = previous.exists()
                    raise ValueError('The core update failed and recovery could not be verified. Check the private service logs.'
                                     + (f' Previous core files: {previous}.' if keep_backup else '')) from None
            if isinstance(failure, ValueError) and str(failure).startswith('Settings changed'):
                raise
            raise ValueError('The new core did not start successfully. The previous core was restored.') from None
        finally:
            signal.signal(signal.SIGTERM, old_handler)
        return {'version': target, 'core_running': expect_running}
    finally:
        if not keep_backup:
            shutil.rmtree(work)

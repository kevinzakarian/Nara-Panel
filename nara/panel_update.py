"""Fixed-source panel upgrades, executed only by the existing root broker."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import traceback
import urllib.request
from .network import open_https
from . import __version__
from .updates import version

REPOSITORY = "kevinzakarian/Nara-Panel"


def target(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", value):
        raise ValueError("Choose a published stable panel version")
    if version(value) <= version(__version__):
        raise ValueError("The panel is already at this version or newer")
    return value


def download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent":"NARA-panel-updater/" + __version__})
    with open_https(request, timeout=30) as response:
        if not response.url.startswith("https://"):
            raise ValueError("An HTTPS release is required")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Panel release is too large")
        return data


def unpack(data, directory):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 5000 or sum(m.size for m in members) > 100_000_000:
            raise ValueError("Panel archive is too large")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'nara-panel' or not (member.isfile() or member.isdir()):
                raise ValueError("Invalid panel archive entry")
        for member in members:
            path = directory / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open('xb') as destination:
                    shutil.copyfileobj(source, destination)
    return directory / 'nara-panel'


def run_installer(source, output):
    env = {**os.environ, 'NARA_MANAGER_LOCK_HELD':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
    process = subprocess.Popen(['/bin/bash', str(source / 'update.sh'), '--source', str(source)],
                               cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                               start_new_session=True)
    try:
        status = process.wait(timeout=750)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise ValueError('Panel update timed out; review the private server update log') from None
    if status:
        raise ValueError('Panel update failed; the updater attempted rollback. Review the private server update log')


def apply(paths, job):
    if set(job) != {'id','operation','version','created_at'} or job['operation'] != 'update-panel':
        raise ValueError("Invalid panel update request")
    release = target(job['version'])
    metadata = json.loads(download('https://api.github.com/repos/' + REPOSITORY + '/releases/tags/v' + release, 2_000_000))
    if metadata.get('tag_name') != 'v' + release or metadata.get('draft') or metadata.get('prerelease'):
        raise ValueError("A published stable release is required")
    base = 'https://github.com/' + REPOSITORY + '/releases/download/v' + release + '/'
    name = 'nara-panel_' + release + '_source.tar.gz'
    checksums = download(base + 'SHA256SUMS', 16384).decode('ascii')
    digest = next((line.split()[0] for line in checksums.splitlines() if len(line.split()) == 2 and line.split()[1] == name), '')
    if not re.fullmatch('[a-fA-F0-9]{64}', digest):
        raise ValueError("Panel release checksum is missing")
    payload = download(base + name, 30_000_000)
    if hashlib.sha256(payload).hexdigest() != digest.lower():
        raise ValueError("Panel release checksum verification failed")
    with tempfile.TemporaryDirectory(prefix='nara-panel-update-') as temp:
        source = unpack(payload, Path(temp))
        if json.loads((source / 'release.json').read_text()).get('version') != release:
            raise ValueError("Panel release version does not match")
        if not (source / 'update.sh').is_file() or not (source / 'requirements.txt').is_file():
            raise ValueError("Panel release is incomplete")
        if (source / 'requirements.txt').read_bytes() != (paths.app / 'requirements.txt').read_bytes():
            raise ValueError("Dependencies changed; use the full installation manager for this release")
        from .maintenance import backup, panel_health
        log = paths.root / 'var/log/nara-panel-update.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'a') as output:
            try:
                backup(paths)
            except Exception:
                traceback.print_exc(file=output)
                raise ValueError('Private backup failed; no update was installed. Review /var/log/nara-panel-update.log') from None
            run_installer(source, output)
        if panel_health(paths).get('version') != release:
            raise ValueError("Updated panel did not report the expected version; review the private server update log")
    return {'version':release, 'backup_created':True}

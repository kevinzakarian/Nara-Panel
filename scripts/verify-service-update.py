"""Disposable Linux CI only: real systemd update with a live, user-owned WAL DB."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import select
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import http.cookiejar

FIXTURE = Path('/opt/nara-update-fixture')
APP = Path('/opt/nara-panel')
DATA = Path('/var/lib/nara-panel')
FUTURE = '9.0.0'


def run(*args):
    return subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def broker():
    from nara import panel_update as update
    def fetch(url, limit):
        base='https://github.com/kevinzakarian/Nara-Panel/releases/download/v'+FUTURE+'/'
        if url=='https://api.github.com/repos/kevinzakarian/Nara-Panel/releases/tags/v'+FUTURE:
            return json.dumps({'tag_name':'v'+FUTURE,'draft':False,'prerelease':False}).encode()
        name='nara-panel_'+FUTURE+'_source.tar.gz'
        payload=(FIXTURE/'release.tar.gz').read_bytes()
        if url==base+'SHA256SUMS':return (hashlib.sha256(payload).hexdigest()+'  '+name+'\n').encode()
        if url==base+name:return payload
        raise AssertionError('Unexpected release URL')
    update.download=fetch  # Only release network I/O is replaced; installation is real.
    from nara.access import main
    sys.argv=[sys.argv[0], 'apply']
    main()


def ports():
    with contextlib.ExitStack() as stack:
        sockets=[stack.enter_context(socket.socket()) for _ in range(3)]
        for sock in sockets:sock.bind(('127.0.0.1',0))
        return [sock.getsockname()[1] for sock in sockets]


def controller(source):
    from nara import maintenance as m
    from nara.store import Store, password_hash
    if DATA.exists():raise RuntimeError('This runner already has panel data')
    run('useradd','--system','--home-dir',str(DATA),'--shell','/usr/sbin/nologin','nara-panel')
    identity=pwd.getpwnam('nara-panel')
    for name in ('nara','web','scripts'):
        shutil.copytree(source/name,APP/name)
    shutil.copyfile(source/'requirements.txt',APP/'requirements.txt')
    (APP/'bin').mkdir()
    core=APP/'bin/sing-box'
    core.write_text('#!/bin/sh\n[ "$1" = version ] && { echo "sing-box version 1.14.3"; exit 0; }\nexit 1\n')
    core.chmod(0o755);core_hash=hashlib.sha256(core.read_bytes()).hexdigest()
    DATA.mkdir(mode=0o700);os.chown(DATA,identity.pw_uid,identity.pw_gid)
    # Initialize and keep a WAL writer open under the real service identity.
    commands, control=os.pipe();responses, ready=os.pipe();writer=os.fork()
    if writer==0:
        os.close(control);os.close(responses)
        try:
            os.setgroups([]);os.setgid(identity.pw_gid);os.setuid(identity.pw_uid)
            store=Store(DATA);store.set('admin',{'username':'fixture','password':password_hash('fixture-only-password')})
            store.set('autostart',False)
            with sqlite3.connect(DATA/'panel.sqlite3') as db:
                db.execute('PRAGMA wal_autocheckpoint=0')
                db.execute("INSERT INTO kv VALUES('backup-proof','42')");db.commit()
                os.write(ready,b'ready\n');os.read(commands,1)
                db.execute("UPDATE kv SET value='43' WHERE key='backup-proof'");db.commit()
                os.write(ready,b'writable\n');os.read(commands,1)
        except Exception:
            import traceback;traceback.print_exc();os._exit(1)
        os._exit(0)
    os.close(commands);os.close(ready)
    def expect(message):
        if not select.select([responses],[],[],30)[0] or os.read(responses,1024)!=message:
            raise AssertionError('Database owner worker did not complete')
    try:
        expect(b'ready\n')
        FIXTURE.mkdir(mode=0o700)
        shutil.copyfile(Path(__file__),FIXTURE/'driver.py')
        # Simulate a host policy where runuser cannot change UID, as reported.
        (FIXTURE/'blocked').mkdir();shim=FIXTURE/'blocked/runuser'
        shim.write_text('#!/bin/sh\necho "runuser: cannot set user id: Operation not permitted" >&2\nexit 1\n');shim.chmod(0o755)
        with tarfile.open(FIXTURE/'release.tar.gz','w:gz') as archive:
            for name in ('nara','web','scripts','deploy','update.sh','requirements.txt','release.json'):
                path=source/name
                for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
                    if not file.is_file() or '__pycache__' in file.parts:continue
                    payload=file.read_bytes();relative=file.relative_to(source).as_posix()
                    if relative=='release.json':payload=json.dumps({'version':FUTURE,'core_version':'1.14.3'}).encode()
                    if relative=='nara/__init__.py':payload=('__version__ = "'+FUTURE+'"\n').encode()
                    info=tarfile.TarInfo('nara-panel/'+relative);info.size=len(payload);info.mode=0o644;archive.addfile(info,io.BytesIO(payload))
        panel,sub,stats=ports()
        env={'NARA_BIND':'127.0.0.1','NARA_PORT':str(panel),'NARA_WEB_PATH':'/CIEntry','NARA_SUB_PORT':str(sub),'NARA_SUB_PATH':'/CIProfiles','NARA_STATS_PORT':str(stats),'NARA_ACCESS_MANAGED':'1'}
        m.write_env(Path('/etc/nara-panel.env'),env)
        for name in ('nara-panel.service','nara-panel-access.service','nara-panel-access.path'):
            shutil.copyfile(source/'deploy'/name,Path('/etc/systemd/system')/name)
        override=Path('/etc/systemd/system/nara-panel-access.service.d');override.mkdir()
        (override/'fixture.conf').write_text('[Service]\nEnvironment=GITHUB_ACTIONS=true\nEnvironment=PATH='+str(FIXTURE/'blocked')+':/usr/sbin:/usr/bin:/sbin:/bin\nExecStart=\nExecStart='+str(APP/'.venv/bin/python')+' '+str(FIXTURE/'driver.py')+' --broker\n')
        run('systemctl','daemon-reload');run('systemctl','start','nara-panel.service','nara-panel-access.path')
        m.panel_health(m.Layout())
        jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
        base='http://127.0.0.1:'+str(panel)+'/CIEntry/api/'
        def request(path,body=None,csrf=''):
            headers={'Content-Type':'application/json','X-CSRF-Token':csrf}
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            with opener.open(req,timeout=5) as response:return json.load(response)
        csrf=request('login',{'username':'fixture','password':'fixture-only-password'})['csrf']
        job=request('update-panel',{'version':FUTURE},csrf)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            time.sleep(.5)
            try:result=request('access-status/'+job['id'])
            except (OSError,ValueError):continue  # The real panel restarts mid-upgrade.
            if result['status']=='failed':raise AssertionError(result.get('error'))
            if result['status']=='complete':break
        else:raise AssertionError('The systemd update did not finish')
        assert request('health')['version']==FUTURE
        assert hashlib.sha256(core.read_bytes()).hexdigest()==core_hash
        assert m._database_owner_worker(DATA.stat(),lambda:Store(DATA).get('admin'))['username']=='fixture'
        backups=list(Path('/var/backups/nara-panel').glob('*.tar.gz'));assert len(backups)==1
        assert backups[0].stat().st_mode&0o777==0o600
        with tarfile.open(backups[0]) as archive:
            snapshot=FIXTURE/'snapshot.sqlite3';snapshot.write_bytes(archive.extractfile('var/lib/nara-panel/panel.sqlite3').read())
        with sqlite3.connect(snapshot) as db:assert db.execute("SELECT value FROM kv WHERE key='backup-proof'").fetchone()[0]=='42'
        assert all(file.stat().st_uid==identity.pw_uid for file in DATA.glob('panel.sqlite3*'))
        os.write(control,b'w');expect(b'writable\n')
        print('Real systemd upgrade passed: blocked runuser, live owner WAL backup, API job, restart, version, account/core preservation and subsequent database writes.')
    finally:
        os.close(control);os.close(responses);os.waitpid(writer,0)
        subprocess.run(['systemctl','stop','nara-panel-access.path','nara-panel-access.service','nara-panel.service'],check=False)


if __name__=='__main__':
    if os.geteuid()!=0 or sys.platform!='linux' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('Only run on a disposable root Linux GitHub Actions runner')
    if sys.argv[1:] == ['--broker']:
        sys.path.insert(0,str(APP));broker()
    elif len(sys.argv)==2:
        controller(Path(sys.argv[1]).resolve())
    else:raise SystemExit('Provide the source path or --broker')

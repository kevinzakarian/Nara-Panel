"""Fixed migration entry point sent over a host-key-pinned SSH connection.

Run as root on a fresh destination only. No credentials are printed.
"""
import json
import os
from pathlib import Path
import pwd
import socket
import shutil
import subprocess
import sys


def main(directory):
    log=Path('/var/log/nara-migration.log')
    descriptor=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
    os.fchmod(descriptor,0o600)
    with os.fdopen(descriptor,'ab',buffering=0) as output:
        def run(args,**kwargs):
            return subprocess.run(args,check=True,stdout=output,stderr=output,stdin=subprocess.DEVNULL,timeout=900,**kwargs)
        config=json.loads((directory/'destination.json').read_text())
        if '--finish' not in sys.argv:
            # Refuse a source/destination mistake or an existing installation.
            for path in ('/etc/nara-panel.env','/opt/nara-panel','/var/lib/nara-panel/panel.sqlite3'):
                if Path(path).exists():raise ValueError('Destination already contains NARA')
            if config['https']:
                for host in {config['panel_host'],config['sub_host']}:
                    addresses={row[4][0] for row in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)}
                    if config['host'] not in addresses:raise ValueError('Destination domain DNS does not point to this server')
            env={**os.environ,'DEBIAN_FRONTEND':'noninteractive','PYTHONDONTWRITEBYTECODE':'1'}
            run(['apt-get','update'],env=env)
            run(['apt-get','install','-y','ca-certificates','curl','tar','gzip','python3','python3-venv','openssl','iproute2','tzdata','openssh-client'],env=env)
            # This archive comes only from the checksum-verified NARA release.
            import tarfile
            with tarfile.open(directory/'source.tar.gz','r:gz') as archive:
                members=archive.getmembers()
                if len(members)>5000 or sum(m.size for m in members)>100_000_000:raise ValueError('Source archive is too large')
                for member in members:
                    path=Path(member.name)
                    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='nara-panel' or not (member.isfile() or member.isdir()):raise ValueError('Invalid source archive')
                archive.extractall(directory,filter='data') if sys.version_info>=(3,12) else archive.extractall(directory)
            source=directory/'nara-panel';sys.path.insert(0,str(source))
            # destination() expects wizard field names, not its normalized result.
            manifest={**config,'panel_domain':config['panel_host'] if config['https'] else '', 'subscription_domain':config['sub_host'] if config['https'] else ''}
            (directory/'destination.json').write_text(json.dumps(manifest))
            run(['useradd','--system','--home-dir','/var/lib/nara-panel','--shell','/usr/sbin/nologin','nara-panel'])
            from nara.store import Store
            store=Store('/var/lib/nara-panel')
            admin=json.loads((directory/'admin.json').read_text());admin.pop('totp_pending',None)
            store.set('admin',admin)
            owner=pwd.getpwnam('nara-panel')
            for path in [store.directory,*store.directory.iterdir()]:os.chown(path,owner.pw_uid,owner.pw_gid)
            run(['/bin/sh',str(source/'scripts/install.sh')],cwd=source,env={**env,'NARA_PROVISION_FILE':str(directory/'destination.json')})
            os.execve('/opt/nara-panel/.venv/bin/python',['/opt/nara-panel/.venv/bin/python',str(directory/'remote.py'),str(directory),'--finish'],{**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        sys.path.insert(0,'/opt/nara-panel')
        from nara.store import Store
        store=Store('/var/lib/nara-panel')
        owner=pwd.getpwnam('nara-panel')
        run(['systemctl','stop','nara-panel'])
        backup=json.loads((directory/'backup.json').read_text())
        from nara.access import public_url
        # Explicit destination addresses replace source addresses before restoring.
        state=store.get('state')
        state['settings'].update(server_address=config['host'],public_url=public_url(config['host'],config['panel_port'],config['web_path']),subscription_url=public_url(config['host'],config['subscription_port'],config['sub_path']))
        store.set('state',state)
        for path in store.directory.iterdir():os.chown(path,owner.pw_uid,owner.pw_gid)
        imported=store.directory/'.migration-history.sqlite3'
        shutil.copyfile(directory/'history.sqlite3',imported)
        imported.chmod(0o600);os.chown(imported,owner.pw_uid,owner.pw_gid)
        # Restoring as the service identity prevents root-owned WAL/SHM files.
        restore_code="""import json,sys
from nara.store import Store
from nara.runtime import Runtime
from nara.portable import restore
s=Store('/var/lib/nara-panel');r=Runtime(s,'/opt/nara-panel/bin/sing-box')
try:restore(s,r,json.load(sys.stdin))
finally:r.stop()
import sqlite3,contextlib
with contextlib.closing(sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)) as source,s.connect() as target:
 for table,query in [('traffic_history',"SELECT * FROM traffic_history WHERE kind IN ('client','inbound')"),('api_keys','SELECT * FROM api_keys')]:
  cursor=source.execute(query)
  while rows:=cursor.fetchmany(1000):
   target.executemany('INSERT OR REPLACE INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
 row=source.execute("SELECT value FROM kv WHERE key='traffic_history_since'").fetchone()
 if row:target.execute("INSERT OR REPLACE INTO kv VALUES('traffic_history_since',?)",row)
"""
        process=subprocess.run(['/opt/nara-panel/.venv/bin/python','-c',restore_code,str(imported)],input=json.dumps(backup).encode(),stdout=output,stderr=output,timeout=180,cwd='/opt/nara-panel',user=owner.pw_uid,group=owner.pw_gid,extra_groups=[])
        imported.unlink(missing_ok=True)
        if process.returncode:raise ValueError('Destination core validation or restore failed')
        run(['systemctl','start','nara-panel'])
        from nara.maintenance import Layout,panel_health,subscription_health,configure_https
        paths=Layout();health=panel_health(paths);subscription_health(paths)
        if config['https']:
            configure_https(paths,'automatic',host=config['panel_host'],subscription_host=config['sub_host'],ports={'NARA_PUBLIC_PANEL_PORT':'443','NARA_PUBLIC_SUB_PORT':'8443'})
            health=panel_health(paths);subscription_health(paths)
        result={'version':health['version'],'url':public_url(config['panel_host'],443 if config['https'] else config['panel_port'],config['web_path'],'https' if config['https'] else 'http'),
                'subscription_url':public_url(config['sub_host'],8443 if config['https'] else config['subscription_port'],config['sub_path'],'https' if config['https'] else 'http'), 'snapshot_at':backup['created_at']}
    print('NARA_MIGRATION_READY '+json.dumps(result),flush=True)


if __name__=='__main__':
    try:main(Path(sys.argv[1]))
    except Exception:
        # Detailed installer output is private on the destination, never the web response.
        print('Destination migration failed. Inspect /var/log/nara-migration.log.',file=sys.stderr)
        raise SystemExit(1)

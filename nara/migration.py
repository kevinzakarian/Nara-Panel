"""Explicitly pinned SSH migration to a fresh Debian/Ubuntu systemd server.

Uses OpenSSH only. Credentials exist in a private temporary directory for the
connection, never job records, command arguments, audit events or remote logs.
"""
import base64
import copy
import contextlib
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
from . import __version__, portable
from .config import require
from .install_config import panel_port, normalize_web_path
from .maintenance import hostname

REMOTE_COMMAND = '''set -eu
[ "$(id -u)" = 0 ] || exit 70
command -v apt-get >/dev/null || exit 71
command -v systemctl >/dev/null || exit 72
command -v python3 >/dev/null || exit 73
[ ! -e /etc/nara-panel.env ] && [ ! -e /opt/nara-panel ] && [ ! -e /var/lib/nara-panel/panel.sqlite3 ] || exit 74
work=$(mktemp -d /root/.nara-migration.XXXXXXXX)
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT
umask 077
tar -xzf - -C "$work"
python3 "$work/remote.py" "$work"
'''


def address(data):
    require(isinstance(data,dict),'Invalid destination')
    try:host=ipaddress.ip_address(data.get('host',''))
    except ValueError:raise ValueError('Enter the destination IPv4 or IPv6 address') from None
    require(not (host.is_loopback or host.is_unspecified or host.is_multicast or host.is_link_local),'Choose a remote server address')
    port=panel_port(data.get('ssh_port',22))
    return str(host),port


def probe(store,data):
    host,port=address(data)
    require(shutil.which('ssh') and shutil.which('ssh-keyscan'),'Install openssh-client on the source server to enable migration')
    result=subprocess.run(['ssh-keyscan','-T','5','-p',str(port),'-t','ed25519,ecdsa,rsa',host],capture_output=True,timeout=20)
    keys=[]
    for line in result.stdout.decode('ascii',errors='ignore').splitlines():
        parts=line.split()
        if len(parts)==3 and parts[1] in ('ssh-ed25519','ecdsa-sha2-nistp256','ssh-rsa'):
            try:raw=base64.b64decode(parts[2],validate=True)
            except ValueError:continue
            if len(raw)<=8192:keys.append((parts[1],parts[2],raw))
    require(bool(keys),'Could not read an SSH host key. Check the destination SSH port and firewall')
    algorithm,key,raw=min(keys,key=lambda x: {'ssh-ed25519':0,'ecdsa-sha2-nistp256':1,'ssh-rsa':2}[x[0]])
    fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
    value={'id':secrets.token_urlsafe(24),'host':host,'ssh_port':port,'algorithm':algorithm,'key':key,'fingerprint':fingerprint,'expires':time.time()+600}
    store.set('migration_probe',value)
    return {key:value[key] for key in ('id','host','ssh_port','algorithm','fingerprint','expires')}


def destination(data):
    host,port=address(data)
    panel_host=hostname(data.get('panel_domain') or host, automatic=bool(data.get('panel_domain')))
    sub_host=hostname(data.get('subscription_domain') or panel_host, automatic=bool(data.get('subscription_domain')))
    require(not data.get('subscription_domain') or data.get('panel_domain'),'Choose a panel domain before setting a subscription domain')
    values={'web_path':normalize_web_path(data.get('web_path','')), 'sub_path':normalize_web_path(data.get('sub_path','')),
            'panel_port':panel_port(data.get('panel_port',10000)), 'subscription_port':panel_port(data.get('subscription_port',10001))}
    require(values['web_path'] and values['sub_path'] and values['web_path']!=values['sub_path'],'Choose separate nonempty panel and subscription paths')
    require(len({values['panel_port'],values['subscription_port'],80,443,8443,10085})==6,'Internal ports must be different and cannot use 80,443,8443,10085')
    return {'host':host,'ssh_port':port,'panel_host':panel_host,'sub_host':sub_host,'https':bool(data.get('panel_domain')),**values}


def source_archive():
    from .panel_update import download, REPOSITORY
    release=__version__
    base='https://github.com/'+REPOSITORY+'/releases/download/v'+release+'/'
    name='nara-panel_'+release+'_source.tar.gz'
    checks=download(base+'SHA256SUMS',16384).decode('ascii')
    digest=next((x.split()[0] for x in checks.splitlines() if len(x.split())==2 and x.split()[1]==name),'')
    require(bool(re.fullmatch('[a-fA-F0-9]{64}',digest)),'Published migration source checksum is unavailable')
    payload=download(base+name,30_000_000)
    require(hashlib.sha256(payload).hexdigest()==digest.lower(),'Migration source checksum verification failed')
    return payload


def bundle(store, config, source=None, database=None):
    if database is not None:
        store=copy.copy(store);store.path=database
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:gz') as archive:
        files={'source.tar.gz':source if source is not None else source_archive(), 'backup.json':json.dumps(portable.document(store)).encode(),
               'admin.json':json.dumps(store.get('admin')).encode(), 'destination.json':json.dumps(config).encode(),
               'remote.py':Path(__file__).with_name('migration_remote.py').read_bytes()}
        for name,data in files.items():
            member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o600
            archive.addfile(member,io.BytesIO(data))
        if database is not None:
            require(database.stat().st_size<=512*1024*1024,'Migration database exceeds 512 MiB; use a portable settings backup and retain the original statistics separately')
            archive.add(database,arcname='history.sqlite3',recursive=False)
    return output.getvalue()


class Manager:
    def __init__(self,store,runtime):
        self.store,self.runtime=store,runtime
        self.lock=threading.Lock()
        old=store.get('migration_job')
        if old and old.get('status')=='running':
            store.set('migration_job',{**old,'status':'interrupted','stage':'The source service restarted. Check the destination before retrying; the source is unchanged.'})

    def status(self):
        return self.store.get('migration_job',{'status':'idle'})

    def start(self,data):
        config=destination(data)
        pin=self.store.get('migration_probe',{})
        require(pin.get('id')==data.get('probe_id') and pin.get('expires',0)>time.time() and pin.get('host')==config['host'] and pin.get('ssh_port')==config['ssh_port'],'SSH verification expired; check the destination again')
        require(data.get('fingerprint')==pin['fingerprint'],'Confirm the SSH fingerprint using a trusted server console')
        mode=data.get('auth_mode')
        require(mode in ('password','key'),'Choose SSH password or private key')
        password=data.get('ssh_password','');key=data.get('ssh_key','')
        require(isinstance(password,str) and len(password)<=1024 and not any(x in password for x in '\x00\r\n'),'Invalid SSH password/passphrase')
        require(isinstance(key,str) and len(key)<=32768,'SSH key is too large')
        require(bool(password) if mode=='password' else 'PRIVATE KEY' in key,'Enter the SSH password or a PEM/OpenSSH private key')
        require(self.lock.acquire(blocking=False),'A migration is already running')
        job={'id':secrets.token_urlsafe(24),'status':'running','stage':'Preparing verified source and a private snapshot','created_at':time.time(),'destination':config['host']}
        self.store.set('migration_job',job)
        threading.Thread(target=self.run,args=(job,config,pin,mode,password,key),daemon=True).start()
        return job

    def run(self,job,config,pin,mode,password,key):
        def stage(message):
            job['stage']=message;self.store.set('migration_job',dict(job))
        try:
            source=source_archive()
            with tempfile.TemporaryDirectory(prefix='.migration-',dir=self.store.directory) as directory:
                directory=Path(directory);directory.chmod(0o700)
                database=directory/'history.sqlite3'
                with self.runtime.lock:
                    if self.runtime.running:self.runtime.collect()
                    portable.snapshot(self.store)
                    with self.store.connect() as source_db, contextlib.closing(sqlite3.connect(database)) as target_db:
                        source_db.backup(target_db)
                    database.chmod(0o600)
                    # Build settings and security from the same frozen database.
                payload=bundle(self.store,config,source,database)
                database.unlink()
                known=directory/'known_hosts'
                known.write_text((config['host'] if config['ssh_port']==22 else '['+config['host']+']:'+str(config['ssh_port']))+' '+pin['algorithm']+' '+pin['key']+'\n');known.chmod(0o600)
                arguments=['ssh','-F','/dev/null','-T','-p',str(config['ssh_port']),'-o','ConnectTimeout=15','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                           '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null',
                           '-o','HostKeyAlgorithms='+('rsa-sha2-512,rsa-sha2-256' if pin['algorithm']=='ssh-rsa' else pin['algorithm']),
                           '-o','IdentitiesOnly=yes','-o','IdentityAgent=none','-o','NumberOfPasswordPrompts=1','-o','LogLevel=ERROR']
                env={**os.environ,'SSH_ASKPASS_REQUIRE':'force','DISPLAY':'nara-migration'}
                if password:
                    secret=directory/'secret';secret.write_text(password);secret.chmod(0o600)
                    askpass=directory/'askpass'
                    askpass.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nprint(Path('+repr(str(secret))+').read_text())\n');askpass.chmod(0o700)
                    env['SSH_ASKPASS']=str(askpass)
                if mode=='key':
                    identity=directory/'identity';identity.write_text(key);identity.chmod(0o600)
                    arguments+=['-i',str(identity),'-o','PreferredAuthentications=publickey']
                else:
                    arguments+=['-o','PreferredAuthentications=password,keyboard-interactive','-o','PubkeyAuthentication=no']
                stage('Connecting to the pinned host; installing and verifying destination (up to 25 minutes)')
                # The command is constant; destination data travels in stdin, never shell text.
                with tempfile.TemporaryFile() as output:
                    process=subprocess.Popen(arguments+['root@'+config['host'],REMOTE_COMMAND],stdin=subprocess.PIPE,stdout=output,stderr=output,env=env,start_new_session=True)
                    try:
                        process.communicate(payload,timeout=1500)
                    except subprocess.TimeoutExpired:
                        process.kill();process.communicate()
                        raise ValueError('SSH migration timed out. Check the destination /var/log/nara-migration.log before retrying') from None
                    output.seek(0);result=output.read(1_048_577)
                    require(process.returncode==0,'Destination setup did not complete (SSH status '+str(process.returncode)+'). Check SSH access and /var/log/nara-migration.log on the destination. Existing destination installations are never overwritten.')
                    line=next((line for line in result.decode(errors='replace').splitlines() if line.startswith('NARA_MIGRATION_READY ')),None)
                    require(line is not None,'Destination did not confirm readiness; inspect its private migration log')
                    ready=json.loads(line[len('NARA_MIGRATION_READY '):])
                    require(ready.get('version')==__version__,'Destination version check failed')
                    from .access import public_url
                    expected=public_url(config['panel_host'],443 if config['https'] else config['panel_port'],config['web_path'],'https' if config['https'] else 'http')
                    require(ready.get('url')==expected,'Destination URL verification failed')
            job.update(status='complete',stage='Destination verified. Source remains running. Review the target, then move DNS/clients and stop the source when ready.',url=ready['url'],subscription_url=ready['subscription_url'],snapshot_at=ready['snapshot_at'])
            self.store.audit('Server migration completed; source retained')
        except Exception as exc:
            job.update(status='failed',stage=str(exc) if isinstance(exc,ValueError) else 'Migration could not complete; check destination access and its private migration log. The source remains unchanged.')
        finally:
            self.store.set('migration_job',job)
            self.lock.release()

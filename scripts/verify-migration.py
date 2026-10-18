"""Disposable GitHub-runner fixture: pinned OpenSSH -> real destination install.

Never run on a user server. This fixture intentionally installs NARA on the VM.
"""
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock


def main(root):
    assert os.geteuid()==0 and os.environ.get('GITHUB_ACTIONS')=='true','Only for a disposable root CI VM'
    assert not Path('/etc/nara-panel.env').exists() and not Path('/opt/nara-panel').exists(),'Requires a fresh disposable VM'
    sys.path.insert(0,str(root))
    from nara.store import Store,password_hash
    from nara.runtime import Runtime
    from nara.migration import Manager,probe,destination
    from nara import __version__
    from tests.helpers import example_state,free_port
    subprocess.run([sys.executable,str(root/'scripts/package.py')],check=True)
    archive=(root/'dist'/('nara-panel_'+__version__+'_source.tar.gz')).read_bytes()
    host=subprocess.check_output(['hostname','-I'],text=True).split()[0]
    with tempfile.TemporaryDirectory(prefix='nara-ssh-ci-') as directory:
        directory=Path(directory)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(directory/'host')],check=True)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(directory/'identity')],check=True)
        (directory/'authorized_keys').write_bytes((directory/'identity.pub').read_bytes())
        port=free_port()
        (directory/'sshd_config').write_text(f'Port {port}\nListenAddress {host}\nHostKey {directory}/host\nPidFile {directory}/sshd.pid\nAuthorizedKeysFile {directory}/authorized_keys\nPermitRootLogin yes\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\nLogLevel ERROR\n')
        Path('/run/sshd').mkdir(exist_ok=True)
        with subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f',str(directory/'sshd_config')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as sshd:
            try:
                for _ in range(50):
                    try:
                        with socket.create_connection((host,port),timeout=.2):break
                    except OSError:time.sleep(.1)
                store=Store(directory/'source-data');state=example_state();state['inbounds'][0]['listen']='::';state['settings']['server_address']='203.0.113.77';state['settings']['public_url']='https://source.invalid/Old';state['settings']['subscription_url']='https://sub.source.invalid/OldSub';store.set('state',state)
                store.set('admin',{'username':'migration-ci','password':password_hash('Fixture-only-password!')})
                store.add_traffic([('user1','upload',1234),('user1','download',5678)],[('in1','download',5678)])
                from nara import api_keys
                api_key=api_keys.create(store,{'name':'Migrated key','days':30,'scopes':['read']})
                fake=SimpleNamespace(lock=threading.RLock(),running=False)
                manager=Manager(store,fake);pin=probe(store,{'host':host,'ssh_port':port})
                data={'host':host,'ssh_port':port,'web_path':'/MigrationCI','sub_path':'/ProfilesCI','panel_port':10000,'subscription_port':10001,'probe_id':pin['id'],'fingerprint':pin['fingerprint'],'auth_mode':'key','ssh_key':(directory/'identity').read_text()}
                # A changed host key cannot proceed to installation or authentication.
                wrong={**store.get('migration_probe'),'key':(directory/'identity.pub').read_text().split()[1]}
                bad={'id':'bad-host','status':'running'}
                with mock.patch('nara.migration.source_archive',return_value=archive):
                    manager.lock.acquire();manager.run(bad,destination(data),wrong,'key','',data['ssh_key'])
                assert manager.status()['status']=='failed'
                assert not Path('/etc/nara-panel.env').exists(),'Host key failure must precede every remote mutation'
                with mock.patch('nara.migration.source_archive',return_value=archive):
                    manager.start(data)
                    deadline=time.monotonic()+1300
                    while manager.status()['status']=='running' and time.monotonic()<deadline:time.sleep(2)
                result=manager.status();assert result['status']=='complete',result
                target=Store('/var/lib/nara-panel');restored=target.get('state')
                assert restored['settings']['server_address']==host
                assert restored['settings']['public_url']==f'http://{host}:10000/MigrationCI/'
                assert 'source.invalid' not in json.dumps(restored['settings'])
                assert target.totals()['user1']=={'upload':1234,'download':5678}
                assert restored['clients'][0]['token']==state['clients'][0]['token']
                assert target.get('admin')['username']=='migration-ci'
                with target.connect() as db:
                    assert db.execute('SELECT COUNT(*) FROM api_keys').fetchone()[0]==1
                    assert db.execute("SELECT SUM(download) FROM traffic_history WHERE kind='inbound' AND step=3600").fetchone()[0]==5678
                assert store.totals()['user1']=={'upload':1234,'download':5678},'Source counters must remain intact'
                import urllib.request
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                token=state['clients'][0]['token']
                with opener.open(f'http://127.0.0.1:10001/ProfilesCI/{token}',timeout=5) as response:
                    profile=json.load(response)
                assert any(row.get('server')==host for row in profile['outbounds'])
                assert 'PRIVATE KEY' not in json.dumps(result)
                print('Pinned SSH migration, changed-host rejection, real installer/core, destination URLs, quotas, source preservation and subscription readiness passed.',flush=True)
            finally:
                subprocess.run(['systemctl','stop','nara-panel','nara-panel-access.path'],check=False)
                sshd.terminate();sshd.wait(timeout=10)


if __name__=='__main__':main(Path(sys.argv[1]).resolve())

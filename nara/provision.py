"""Installer-only entry values for a root-owned migration manifest."""
import json
import os
from pathlib import Path
import stat
import sys
from .access import validate
from .install_config import port_available



def configure(source, target):
    info=source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o077 or info.st_size>65536:
        raise ValueError('Provisioning requires a private root-owned manifest')
    manifest=json.loads(source.read_text())
    value=validate({key:manifest[key] for key in ('web_path','sub_path','panel_port','subscription_port')})
    for port in (value['panel_port'],value['subscription_port']):
        if not port_available(port):raise ValueError('Destination port is already in use: '+str(port))
    values={'NARA_WEB_PATH':value['web_path'],'NARA_SUB_PATH':value['sub_path'],
        'NARA_PORT':str(value['panel_port']),'NARA_SUB_PORT':str(value['subscription_port']),
        'NARA_BIND':'0.0.0.0','NARA_STATS_PORT':'10085','NARA_SECURE_COOKIE':'0','NARA_ACCESS_MANAGED':'1'}
    target.write_text(''.join(key+'='+value+'\n' for key,value in values.items()))
    target.chmod(0o600)


if __name__=='__main__':
    configure(Path(sys.argv[1]),Path(sys.argv[2]))

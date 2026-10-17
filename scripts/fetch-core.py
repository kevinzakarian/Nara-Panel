"""Fetch a pinned NARA-compatible core; never download or invoke a compiler."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

REPOSITORY = 'https://github.com/kevinzakarian/Nara-Panel'
MEMBERS = {'sing-box', 'libcronet.so', 'libcronet.LICENSE', 'SING-BOX-LICENSE', 'SING-BOX-COPYING', 'build.json'}
MAX_ARCHIVE = 300 * 1024**2
MAX_UNPACKED = 800 * 1024**2


def digest(path):
    value = hashlib.sha256()
    with open(path,'rb') as source:
        for chunk in iter(lambda: source.read(1024**2), b''):
            value.update(chunk)
    return value.hexdigest()


def architecture(machine=None):
    value = machine or platform.machine()
    mapping = {'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}
    if value not in mapping:
        raise ValueError('Prebuilt cores support Linux amd64 and arm64')
    return mapping[value]


def artifact(manifest, arch):
    if arch not in ('amd64','arm64'):
        raise ValueError('Unsupported core architecture')
    version = manifest.get('version','')
    tag = manifest.get('release_tag','')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) or not re.fullmatch(r'core-v[0-9]+\.[0-9]+\.[0-9]+-nara\.[0-9]+',tag):
        raise ValueError('Invalid pinned core release')
    if not re.fullmatch(r'[a-f0-9]{40}',manifest.get('upstream_commit','')):
        raise ValueError('Invalid pinned upstream revision')
    item = manifest['assets']['linux-'+arch]
    if not re.fullmatch(r'[a-f0-9]{64}',item.get('sha256','')):
        raise ValueError('Missing pinned core checksum; no build fallback is allowed')
    name = f'nara-sing-box-{version}-linux-{arch}.tar.gz'
    if item.get('name') != name:
        raise ValueError('Invalid core artifact name')
    return REPOSITORY+'/releases/download/'+tag+'/'+name, item['sha256']


def check_elf(path, arch):
    with open(path,'rb') as source:
        header=source.read(20)
    if len(header)!=20 or header[:6]!=b'\x7fELF\x02\x01' or struct.unpack('<H',header[18:20])[0] != {'amd64':62,'arm64':183}[arch]:
        raise ValueError('The downloaded ELF does not match the requested architecture')


def unpack(archive, destination, manifest, arch):
    _, expected = artifact(manifest,arch)
    if archive.stat().st_size > MAX_ARCHIVE or digest(archive) != expected:
        raise ValueError('Core archive checksum verification failed; nothing was installed')
    if destination.exists():
        raise ValueError('Core staging directory already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nara-core-',dir=destination.parent) as temporary:
        stage=Path(temporary)
        with tarfile.open(archive,'r:gz') as source:
            seen=set(); total=0
            for member in source:
                if member.name not in MEMBERS or member.name in seen or not member.isfile():
                    raise ValueError('Unexpected or unsafe entry in the core archive')
                if member.size < 0 or (member.name not in ('sing-box','libcronet.so') and member.size > 2*1024**2):
                    raise ValueError('Invalid core archive entry size')
                total += member.size
                if total > MAX_UNPACKED:
                    raise ValueError('Core archive is too large')
                with source.extractfile(member) as incoming,open(stage/member.name,'wb') as output:
                    shutil.copyfileobj(incoming,output,1024**2)
                (stage/member.name).chmod(0o755 if member.name in ('sing-box','libcronet.so') else 0o644)
                seen.add(member.name)
            if seen != MEMBERS:
                raise ValueError('Core archive is incomplete')
        metadata=json.loads((stage/'build.json').read_text())
        if any(metadata.get(k)!=v for k,v in {'os':'linux','architecture':arch,'version':manifest['version'],'upstream_commit':manifest['upstream_commit'],'release_tag':manifest['release_tag']}.items()):
            raise ValueError('Core build metadata does not match the pinned release')
        for name in ('sing-box','libcronet.so'):
            check_elf(stage/name,arch)
            if metadata.get('files',{}).get(name)!=digest(stage/name):
                raise ValueError('Core payload checksum verification failed')
        # The caller uses a fresh staging directory; publication happens only
        # after the entire archive, metadata and both ELF files are verified.
        destination.mkdir(mode=0o755)
        for name in MEMBERS:
            shutil.move(str(stage/name),destination/name)
    return destination/'sing-box'


def fetch(manifest, arch, destination):
    url, _=artifact(manifest,arch)
    with tempfile.TemporaryDirectory(prefix='nara-download-') as directory:
        archive=Path(directory)/'core.tar.gz'
        print(f'[NARA] Downloading verified Sing-box {manifest["version"]} for Linux {arch}...',flush=True)
        subprocess.run(['curl','--proto','=https','--proto-redir','=https','--tlsv1.2','--fail','--location','--retry','3','--retry-all-errors','--connect-timeout','15','--max-time','600','--max-filesize',str(MAX_ARCHIVE),url,'--output',str(archive)],check=True)
        binary=unpack(archive,destination,manifest,arch)
        print('[NARA] Core checksums and architecture verified. No Go toolchain is needed.',flush=True)
        return binary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path,help='New staging directory')
    parser.add_argument('--arch',choices=['amd64','arm64'])
    args=parser.parse_args()
    try:
        manifest=json.loads((Path(__file__).resolve().parent.parent/'core-release.json').read_text())
        fetch(manifest,args.arch or architecture(),args.output)
    except (OSError,ValueError,KeyError,TypeError,tarfile.TarError,subprocess.SubprocessError) as exc:
        parser.exit(1,'NARA core download failed: '+str(exc)+'\nThe existing installation was kept. Retry the download; compilation is never used as a fallback.\n')


if __name__=='__main__':
    main()

"""Package a CI-built core with its original notices and exact build provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def package(root, binary, arch, output, source):
    config = json.loads((root / 'core-build.json').read_text())
    revision = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip()
    upstream = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'], text=True).strip()
    if upstream != config['upstream_commit']:
        raise ValueError('Unexpected upstream source revision')
    text = subprocess.check_output([str(binary),'version'], text=True)
    if not text.startswith('sing-box version ' + config['version'] + '\n') or 'with_v2ray_api' not in text or 'with_quic' not in text:
        raise ValueError('The packaged core is incompatible with NARA')
    output.mkdir(parents=True, exist_ok=True)
    name = f"nara-sing-box-{config['version']}-linux-{arch}.tar.gz"
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for filename, path in {'sing-box':binary, 'libcronet.so':binary.parent/'libcronet.so', 'libcronet.LICENSE':binary.parent/'libcronet.LICENSE', 'SING-BOX-LICENSE':source/'LICENSE', 'SING-BOX-COPYING':root/'deploy/licenses/GPL-3.0.txt'}.items():
            shutil.copyfile(path, stage/filename)
        (stage/'sing-box').chmod(0o755)
        (stage/'libcronet.so').chmod(0o755)
        metadata = {**config, 'architecture':arch, 'os':'linux', 'nara_revision':revision, 'build_info':text}
        metadata['files']={name:hashlib.sha256((stage/name).read_bytes()).hexdigest() for name in ['sing-box','libcronet.so']}
        (stage/'build.json').write_text(json.dumps(metadata,indent=2)+'\n')
        with tarfile.open(output/name,'w:gz') as archive:
            for path in sorted(stage.iterdir()):
                archive.add(path,arcname=path.name,recursive=False)
    digest = hashlib.sha256((output/name).read_bytes()).hexdigest()
    (output/(name+'.sha256')).write_text(digest+'  '+name+'\n')
    print(name)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',required=True,type=Path)
    parser.add_argument('--arch',required=True,choices=['amd64','arm64'])
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',default='dist/core-release',type=Path)
    args=parser.parse_args()
    package(Path(__file__).resolve().parent.parent,args.binary.resolve(),args.arch,args.output,args.source)

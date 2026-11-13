"""Regenerate the pinned schema/help from a pinned upstream checkout and binary."""
import argparse
import json
import re
import subprocess
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path)
parser.add_argument('--binary',type=Path,default=Path('dist/sing-box'))
args=parser.parse_args()
root=Path(__file__).resolve().parent.parent
output=root/'nara/schema'
pin=json.loads((root/'core-build.json').read_text())
version=pin['version']
if subprocess.check_output(['git','-C',str(args.source),'rev-parse','HEAD'],text=True).strip()!=pin['upstream_commit']:
    raise SystemExit('The documentation checkout does not match the pinned core.')
if subprocess.check_output([str(args.binary.resolve()),'version'],text=True).splitlines()[0]!=f'sing-box version {version}':
    raise SystemExit(f'The generator requires Sing-box {version}.')
schema_path=output/f'sing-box-{version}.schema.json'
subprocess.run([str(args.binary.resolve()),'schema','-o',str(schema_path)],check=True)
schema=json.loads(schema_path.read_text())
schema_path.write_text(json.dumps(schema,ensure_ascii=False,separators=(',',':'))+'\n')
docroot=args.source/'docs/configuration'
documents={}
for file in docroot.rglob('*.md'):
    if len(file.name.split('.'))>2:
        continue
    records={};key=None;body=[];code=False
    for line in file.read_text().splitlines()+['# END']:
        if line.startswith('```'):
            code=not code
            continue
        if code:
            continue
        if line.startswith('#'):
            if key and body:
                text=' '.join(body)
                text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
                text=re.sub(r'[`*_]','',text)
                records[key]={'description':text[:500]}
            key=line[5:].strip().strip('`') if line.startswith('#### ') else None
            body=[]
        elif key and line.strip() and not line.startswith(('    ','|','!!!','???','==','===')):
            body.append(line.strip())
    documents[str(file.relative_to(docroot).with_suffix(''))]=records
common={}
for scope in ('shared/listen','shared/dial','shared/udp-nat','shared/tls','shared/quic'):
    common.update(documents.get(scope,{}))
common.update({k:{'description':v} for k,v in {
    'tag':'A unique name used to reference this item in other settings.',
    'listen':'Local address on which this server listens.',
    'server':'Address of the remote server.',
    'users':'Accounts accepted by this standalone listener.',
    'password':'Authentication password.','enabled':'Enable this option.'}.items()})
(output/'field-help.json').write_text(json.dumps({'_documents':documents,**common},ensure_ascii=False,separators=(',',':'))+'\n')
(output/'COPYING').write_text((args.source/'LICENSE').read_text())
print('Regenerated schema and documentation help from',len(documents),'versioned documents.')

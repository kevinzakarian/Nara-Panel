"""Regenerate the pinned schema/help from an official 1.14.3 checkout and binary."""
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
version=subprocess.check_output([str(args.binary.resolve()),'version'],text=True).splitlines()[0]
if version!='sing-box version 1.14.3':
    raise SystemExit('The generator requires exactly Sing-box 1.14.3')
subprocess.run([str(args.binary.resolve()),'schema','-o',str(output/'sing-box-1.14.3.schema.json')],check=True)
schema=json.loads((output/'sing-box-1.14.3.schema.json').read_text())
(output/'sing-box-1.14.3.schema.json').write_text(json.dumps(schema,ensure_ascii=False,separators=(',',':'))+'\n')
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

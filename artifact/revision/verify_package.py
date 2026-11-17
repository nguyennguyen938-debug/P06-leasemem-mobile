#!/usr/bin/env python3
from pathlib import Path
import sys,json,hashlib,tarfile
root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve();manifest=json.loads((root/'MANIFEST.json').read_text())
sha=lambda b:hashlib.sha256(b).hexdigest()
for rel,h in manifest.items():assert sha((root/rel).read_bytes())==h,rel
actual={str(p.relative_to(root))for p in root.rglob('*')if p.is_file()};assert actual==set(manifest)|{'MANIFEST.json'},'unexpected/missing files'
for p in (root/'artifact/results/revision-20261115').glob('*source.tar.gz'):
 name=p.name.replace('.tar.gz','-manifest.json')
 if p.name=='historical-source.tar.gz':name='historical-manifest.json'
 expected=json.loads((p.parent/name).read_text())
 with tarfile.open(p)as t:observed={m.name:sha(t.extractfile(m).read())for m in t.getmembers()if m.isfile()}
 assert observed==expected,p.name
for rel in manifest:
 p=root/rel
 if p.suffix in ['.py','.sh','.md','.tex','.json','.jsonl','.log']:
  b=p.read_bytes();assert (b'/' + b'Users' + b'/') not in b,rel
print(json.dumps({'verified_files':len(manifest),'source_archives_verified':True,'local_paths_scan':'passed'}))

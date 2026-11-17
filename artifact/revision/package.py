#!/usr/bin/env python3
"""Create a local allowlisted anonymous ZIP; never uploads or publishes."""
from pathlib import Path
import io,json,hashlib,tarfile,zipfile,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/review-package';OUT.mkdir(parents=True,exist_ok=True)
PREFIXES=[str(ROOT.parent.parent).encode(),str(Path.home()).encode()]
def sha(b):return hashlib.sha256(b).hexdigest()
def scrub(b):
 if b'\0' in b[:4096]:return b
 try:b.decode('utf-8')
 except UnicodeDecodeError:return b
 for prefix in PREFIXES:b=b.replace(prefix,b'/anonymous-workspace')
 return b
files={};normal=[];overrides={}
for base in ['artifact','manuscript']:
 for p in sorted((ROOT/base).rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(ROOT);parts=rel.parts
  if any(x in parts for x in ['build','__pycache__','.DS_Store']):continue
  if p.suffix in ['.pyc','.aux','.out','.log','.bbl','.blg','.fls','.fdb_latexmk','.synctex'] and base=='manuscript':continue
  if p.suffix in ['.pyc','.idsig']:continue
  if p.name.endswith('.pid') or p.name in ['tmp.png']:continue
  b=p.read_bytes();new=b
  if p.name.endswith('.tar.gz'):
   raw=io.BytesIO();members={}
   with tarfile.open(fileobj=io.BytesIO(b),mode='r:gz') as old,tarfile.open(fileobj=raw,mode='w:gz') as t:
    for m in old.getmembers():
     if not m.isfile():continue
     content=scrub(old.extractfile(m).read());members[m.name]=sha(content)
     info=tarfile.TarInfo(m.name);info.size=len(content);info.mode=m.mode;info.mtime=0;info.uid=info.gid=0;info.uname=info.gname='';t.addfile(info,io.BytesIO(content))
   new=raw.getvalue()
   name=p.name.replace('.tar.gz','-manifest.json')
   if p.name=='historical-source.tar.gz':name='historical-manifest.json'
   overrides[str(rel.parent/name)]=(json.dumps(members,indent=2,sort_keys=True)+'\n').encode()
  elif p.suffix not in ['.apk','.pdf','.png','.jpg','.jks','.ttf','.woff']:new=scrub(b)
  files[str(rel)]=new
  if new!=b:normal.append({'path':str(rel),'original_sha256':sha(b),'packaged_sha256':sha(new),'reason':'anonymous path or tar metadata normalization'})
for rel,b in overrides.items():
 old=files.get(rel,b);files[rel]=b
 if old!=b:normal.append({'path':rel,'original_sha256':sha((ROOT/rel).read_bytes()),'packaged_sha256':sha(b),'reason':'manifest recomputed for normalized source archive'})
for name in ['revision-execution-report.md','artifact-revision-audit.md']:
 p=ROOT/'review'/name
 if p.exists():files['review/'+name]=scrub(p.read_bytes())
files['NORMALIZATION.json']=(json.dumps(normal,indent=2,sort_keys=True)+'\n').encode()
files['README.md']=b'# P06 anonymous local package\n\nSee artifact/README.md. This ZIP has not been publicly hosted. Verify with python3 artifact/revision/verify_package.py .\n'
manifest={k:sha(v) for k,v in sorted(files.items())};files['MANIFEST.json']=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
path=OUT/'P06-review.zip'
with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for name,b in sorted(files.items()):
  info=zipfile.ZipInfo(name,date_time=(2026,11,15,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o755 if name.endswith('.sh') else 0o644)<<16;z.writestr(info,b)
(OUT/'P06-review.zip.sha256').write_text(sha(path.read_bytes())+'  P06-review.zip\n')
(OUT/'package-summary.json').write_text(json.dumps({'files':len(files),'bytes':path.stat().st_size,'sha256':sha(path.read_bytes()),'public_upload':False},indent=2)+'\n')
print(path.name,len(files),path.stat().st_size)

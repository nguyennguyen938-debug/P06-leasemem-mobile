#!/usr/bin/env python3
"""Extract to a new temporary directory, validate manifest, rebuild analyses/PDF/APKs."""
from pathlib import Path
import sys,os,subprocess,tempfile,zipfile,json,hashlib
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/review-package'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
work=Path(tempfile.mkdtemp(prefix='p06-review-check-'))
with zipfile.ZipFile(OUT/'P06-review.zip')as z:z.extractall(work)
for p in work.rglob('*.sh'):p.chmod(0o755)
report={'extraction':str(work),'commands':[]}
env=os.environ.copy();env.setdefault('ANDROID_HOME',str(ROOT.parent/'shared-android/sdk'));env.setdefault('JAVA_HOME','/opt/homebrew/opt/openjdk@17')
log=OUT/'release-validation.log'
with log.open('w')as f:
 def run(cmd,cwd):
  proc=subprocess.run(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT);report['commands'].append({'command':cmd,'exit_code':proc.returncode});f.flush();assert proc.returncode==0,cmd
 run([sys.executable,'artifact/revision/verify_package.py','.'],work)
 inputs=list((work/'manuscript/generated').glob('*'))+list((work/'artifact/results/derived').glob('*.csv'))+[work/'artifact/results/derived/summary.json',work/'artifact/results/revision-20261115/summary.json',work/'artifact/results/revision-20261115/deployment-summary.json']
 before={str(p.relative_to(work)):sha(p)for p in inputs if p.is_file()}
 run(['make','all'],work/'artifact')
 changed=[p for p,h in before.items()if sha(work/p)!=h];report['generated_files_compared']=len(before);report['generated_differences']=changed;assert not changed,changed
 run([sys.executable,'revision/test_oracle.py'],work/'artifact')
 run(['make','apks'],work/'artifact')
 a=subprocess.check_output(['pdftotext',str(work/'manuscript/main.pdf'),'-']);b=subprocess.check_output(['pdftotext',str(ROOT/'manuscript/main.pdf'),'-']);report['pdf_text_identical']=a==b;assert a==b
 report['result']='passed'
(OUT/'release-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

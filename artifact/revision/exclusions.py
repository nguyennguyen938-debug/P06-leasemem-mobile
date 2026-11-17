from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parents[2];d=root/'artifact/results/revision-20261115'
rows=[]
for base in [root/'artifact/results/raw',root/'artifact/logs',d]:
 for p in sorted(base.rglob('*')):
  if not p.is_file() or p.name in ['exclusions.json','summary.json'] or p.suffix not in ['.jsonl','.log']:continue
  rel=str(p.relative_to(root));status='historical input governed by scripts/analyze.py validity rules'
  if '/excluded/' in rel or '/discarded_' in rel or 'INVALID' in rel or '/logs/' in rel:status='historical diagnostic/excluded; retained'
  if d in p.parents:
   status='revision raw campaign' if p.suffix=='.jsonl' else 'revision build/runtime diagnostic'
   if p.name.startswith('supplement-emulator'):status='initial supplemental harness; permission cleanup/relaunch defects, replaced by separately named final cohort; retained'
   if p.name.startswith('reference-emulator') and '-final' not in p.name:status='initial reference cohort; superseded for headline counts by final process-isolation regression; retained and separately audited'
  rows.append({'path':rel,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'status':status})
(d/'exclusions.json').write_text(json.dumps(rows,indent=2)+'\n')
print(len(rows),'raw/log records inventoried')

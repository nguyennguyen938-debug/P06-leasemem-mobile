#!/usr/bin/env python3
"""Reproduce sample selection and bundle the inspected pinned source, not an automated semantic classifier."""
from pathlib import Path
import csv,json,hashlib,subprocess,shutil
root=Path(__file__).resolve().parents[2];out=root/'artifact/revision/provenance';out.mkdir(exist_ok=True)
aw=root.parent/'shared-android/android_world';pin='55ddaf5edc6f6c25673aed343907d5b9dca66f84'
assert subprocess.check_output(['git','-C',str(aw),'rev-parse','HEAD'],text=True).strip()==pin
rows=list(csv.DictReader((root/'artifact/results/derived/aw_census_tasks.csv').open()))
selected=[r for c in ['watermark','api-only','gui-only'] for r in sorted(rows,key=lambda r:r['task']) if r['task_class']==c and r['reads_state']=='1']
selected=sum([[r for r in selected if r['task_class']==c][:3] for c in ['watermark','api-only','gui-only']],[])
judgments={
'FilesDeleteFile':('single/files.py:83; common_validators/file_validators.py:154','Named-path existence check; validator does not read content.','Shell filesystem access; mtime does not certify path identity.'),
'FilesMoveFile':('single/files.py:28; common_validators/file_validators.py:84','Source absence plus destination presence, not complete content identity.','Shell filesystem access; rename/membership and identity need explicit evidence.'),
'MarkorAddNoteHeader':('single/markor.py:734,784','Old/new path existence and exact new content equal to header plus original content.','Filesystem input includes content and path; timestamp alone is insufficient.'),
'MarkorCreateNoteFromClipboard':('single/markor.py:452,494; common_validators/file_validators.py:199','Clipboard initialized/checked during setup; result validated as a created file.','Clipboard read and file-output validation are different provenance; no clipboard revision.'),
'SimpleSmsReply':('single/sms.py:115; common_validators/sms_validators.py:214','Recipient and reply text are goal parameters; validator reads sent SMS.','Name rule overstates need for a remembered input: task name alone does not prove dependence.'),
'SimpleSmsReplyMostRecent':('single/sms.py:57; common_validators/sms_validators.py:214,223','Setup reads inbox; sent-message validator checks output against selected recipient.','Privileged adb content queries differ from ordinary app permission/role access.'),
'ExpenseAddMultipleFromGallery':('single/expense.py:363,264; common_validators/sqlite_validators.py:210','Generated image is task input; result is checked as added private SQLite rows.','Validator database access is privileged harness access, not an app public provider.'),
'ExpenseAddMultipleFromMarkor':('single/expense.py:328,264; common_validators/sqlite_validators.py:210','Markor note is input; added expense rows are output validation.','Input file and output private database require separate provenance.'),
'ExpenseDeleteDuplicates':('single/expense.py:145,188; common_validators/sqlite_validators.py:210','Reads private database rows and compares deletion integrity.','Root/adb private-database access is not evidence of ordinary application access.')}
for r in selected:
 loc,query,note=judgments[r['task']];r.update(source_locations=loc,inspected_query=query,qualification=note,strict_cached_verdict='UNKNOWN',audit='manual source inspection, no task execution')
(out/'sample.json').write_text(json.dumps({'commit':pin,'selection':'first three reads_state=1 names sorted in each historical class','rows':selected},indent=2)+'\n')
paths=['task_evals/single/'+x+'.py' for x in ['files','markor','sms','expense']]+['task_evals/common_validators/'+x+'.py' for x in ['file_validators','sms_validators','sqlite_validators']]+['task_evals/utils/sqlite_utils.py','utils/file_utils.py']
manifest={}
for rel in paths:
 p=aw/'android_world'/rel;q=out/'source'/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q);manifest[rel]=hashlib.sha256(q.read_bytes()).hexdigest()
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Inspected sample:',len(selected))

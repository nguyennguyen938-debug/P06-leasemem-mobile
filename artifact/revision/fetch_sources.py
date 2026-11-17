from pathlib import Path
import urllib.request,base64,json,hashlib
root=Path(__file__).resolve().parent/'source-audit';root.mkdir(exist_ok=True)
files={
'contacts':('platform/packages/providers/ContactsProvider','src/com/android/providers/contacts/ContactsDatabaseHelper.java'),
'calllog':('platform/packages/providers/ContactsProvider','src/com/android/providers/contacts/CallLogProvider.java'),
'media_db':('platform/packages/providers/MediaProvider','src/com/android/providers/media/DatabaseHelper.java'),
'media_provider':('platform/packages/providers/MediaProvider','src/com/android/providers/media/MediaProvider.java')}
manifest={}
for tag in ['android-13.0.0_r1','android-15.0.0_r1']:
 for name,(repo,path) in files.items():
  url=f'https://android.googlesource.com/{repo}/+/{tag}/{path}?format=TEXT';dest=root/f'{tag}-{name}.java'
  try:
   data=base64.b64decode(urllib.request.urlopen(url,timeout=30).read());dest.write_bytes(data);manifest[dest.name]={'url':url,'sha256':hashlib.sha256(data).hexdigest(),'status':'retrieved'}
  except Exception as e:manifest[dest.name]={'url':url,'status':'failed','error':str(e)}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))

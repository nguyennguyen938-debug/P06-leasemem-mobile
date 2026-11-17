from pathlib import Path
p=Path('artifact/app/client/src/org/leasemem/client/LmApp.java')
s=p.read_text().replace('    void observe(JSONObject out) throws Exception {','    void observeHistorical(JSONObject out) throws Exception {').replace('    Map<String, String> lmValidate(Set<String> srcs, boolean strict, JSONObject cost) throws Exception {','    Map<String, String> lmValidateHistorical(Set<String> srcs, boolean strict, JSONObject cost) throws Exception {')
pos=s.index('    String derivedVal(')
s=s[:pos]+'''    void observe(JSONObject out) throws Exception {
        observeHistorical(out);
        // Historical fields remain for historical baselines only. Strict certificates are separate.
        JSONObject certs = new JSONObject();
        for (String[] f : FACTS) certs.put(f[0], Revision.observe(this, f[0]));
        mem.put("certificates_v4", certs);
        out.put("certificates_v4", certs);
    }

    Map<String, String> lmValidate(Set<String> srcs, boolean strict, JSONObject cost) throws Exception {
        if (!strict) return lmValidateHistorical(srcs, false, cost); // explicitly weak historical ablation
        Map<String,String> result = new HashMap<>();
        JSONObject certs = mem.optJSONObject("certificates_v4");
        for (String[] f : FACTS) if (srcs.contains(f[1])) {
            JSONObject v = Revision.validate(this, f[0], certs == null ? null : certs.optJSONObject(f[0]));
            result.put(f[0], v.getString("verdict")); cost.put(f[0], v);
        }
        return result;
    }

'''+s[pos:]
s=s.replace('        save();\n        Log.i(TAG, "START', '        save();\n        Revision.start(this);\n        Log.i(TAG, "START')
p.write_text(s)
p=Path('artifact/app/client/AndroidManifest.xml');s=p.read_text().replace('  <application','  <uses-permission android:name="android.permission.INTERNET"/>\n  <uses-permission android:name="android.permission.WRITE_CONTACTS"/>\n  <application');s=s.replace('    <receiver','    <provider android:name=".ReferenceProvider" android:authorities="org.leasemem.reference" android:exported="false" android:process=":reference"/>\n    <receiver');p.write_text(s)

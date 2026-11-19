package org.leasemem.mut;

import android.content.BroadcastReceiver;
import android.content.ContentProviderOperation;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.CalendarContract;
import android.provider.CallLog;
import android.provider.ContactsContract;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * "Another app" that mutates Android content sources through their public APIs (ContentResolver, MediaStore,
 * Settings, FUSE file I/O). Used by the host driver for experiment setup and for the mutations injected while
 * the memory-holding client is absent. Each call writes its result to files/done_<id>.
 */
public class Cmd extends BroadcastReceiver {
    static final String VOL = MediaStore.VOLUME_EXTERNAL_PRIMARY;
    // This user's shared storage (/storage/emulated/<user>), never another user's.
    static final String DOC = android.os.Environment.getExternalStorageDirectory().getPath() + "/Documents/lm";
    static final String PHONE = ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE;
    static final String NAME = ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE;
    ContentResolver cr; Context ctx; Random rnd = new Random();
    /** True if this install must not touch, one per line in files/p06_exclude (written by the driver before the
     *  first start). On the personal test phone the driver excludes SMS: the SMS provider is shared by all
     *  Android users, so reading, observing or writing it from the test user could reach the owner's messages. */
    boolean excluded(String src) {
        try { for (String s : new String(java.nio.file.Files.readAllBytes(new File(ctx.getFilesDir(), "p06_exclude").toPath())).split("\\s+")) if (s.equals(src)) return true; }
        catch (Exception ignored) {}
        return false;
    }

    @Override public void onReceive(Context c, Intent it) {
        ctx = c; cr = c.getContentResolver();
        String op = it.getStringExtra("op"), a = it.getStringExtra("a"), b = it.getStringExtra("b"), id = it.getStringExtra("id");
        JSONObject res = new JSONObject();
        try {
            res.put("t_pre", System.currentTimeMillis());
            switch (op) {
                case "ensure": ensure(res); break;
                case "mutate": res.put("did", mutate(a, b, it.getStringExtra("tag"))); break;
                // G11: notifyChange on uri `a` with flags `b` from this app, no write: the flags an observer then
                // receives tell whether the provider or ContentService adds NOTIFY_NO_DELAY (Galaxy S25 Contacts).
                case "notify": cr.notifyChange(Uri.parse(a), null, Integer.parseInt(b)); res.put("did", "notify " + a + " flags " + b); break;
                case "mutate_at": {   // sleep on-device until absolute wall time `at`, then mutate; record start/end
                    long at = it.getLongExtra("at", 0);
                    long w; while ((w = at - System.currentTimeMillis()) > 0) Thread.sleep(Math.min(w, 50));
                    long m0 = System.currentTimeMillis();
                    res.put("did", mutate(a, b, it.getStringExtra("tag")));
                    res.put("mut_start", m0); res.put("mut_end", System.currentTimeMillis()); res.put("at", at);
                    break; }
                case "sms_reuse": res.put("did", smsReuse()); break;
                case "bulk_contacts": {   // a = count (<=500), b = name prefix; batches of 100 raw contacts
                    int n = Integer.parseInt(a);
                    for (int i0 = 0; i0 < n; i0 += 100) {
                        ArrayList<ContentProviderOperation> ops = new ArrayList<>();
                        for (int i = i0; i < Math.min(n, i0 + 100); i++) {
                            int back = ops.size();
                            ops.add(ContentProviderOperation.newInsert(ContactsContract.RawContacts.CONTENT_URI)
                                    .withValue(ContactsContract.RawContacts.ACCOUNT_TYPE, null).withValue(ContactsContract.RawContacts.ACCOUNT_NAME, null).build());
                            ops.add(ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI).withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, back)
                                    .withValue(ContactsContract.Data.MIMETYPE, NAME).withValue(ContactsContract.CommonDataKinds.StructuredName.DISPLAY_NAME, b + " " + i).build());
                            ops.add(ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI).withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, back)
                                    .withValue(ContactsContract.Data.MIMETYPE, PHONE).withValue(ContactsContract.CommonDataKinds.Phone.NUMBER, "+1888" + i).build());
                        }
                        cr.applyBatch(ContactsContract.AUTHORITY, ops);
                    }
                    res.put("did", "bulk contacts " + n); break; }
                case "bulk_images": {     // a = count (<=200), b = name prefix
                    int n = Integer.parseInt(a);
                    for (int i = 0; i < n; i++) imgInsert(b + "_" + i + ".png");
                    res.put("did", "bulk images " + n); break; }
                case "contact_update_at": res.put("did", contactUpdate(it.getStringExtra("tag"))); break;
                case "file_touch_same_second": res.put("did", fileSameSecond(it.getStringExtra("tag"))); break;
            }
            res.put("t_post", System.currentTimeMillis());
            res.put("ok", true);
        } catch (Exception e) { try { res.put("ok", false); res.put("err", e.toString()); } catch (Exception ignored) {} Log.e("LMMUT", op, e); }
        try (FileOutputStream f = new FileOutputStream(new File(c.getFilesDir(), "done_" + id))) { f.write(("R:" + res).getBytes()); } catch (Exception ignored) {}
    }

    // ---------------- helpers ----------------
    List<String[]> q(Uri u, String[] proj, String sel, String[] args, String order) {
        List<String[]> rows = new ArrayList<>();
        try (Cursor c = cr.query(u, proj, sel, args, order)) {
            while (c != null && c.moveToNext()) { String[] r = new String[proj.length]; for (int i = 0; i < proj.length; i++) r[i] = c.getString(i); rows.add(r); }
        }
        return rows;
    }

    List<String> rawOf(String name) {
        List<String> ids = new ArrayList<>();
        for (String[] x : q(ContactsContract.Data.CONTENT_URI, new String[]{ContactsContract.Data.RAW_CONTACT_ID},
                ContactsContract.Data.MIMETYPE + "=? AND " + ContactsContract.Data.DISPLAY_NAME + "=?", new String[]{NAME, name}, null)) ids.add(x[0]);
        return ids;
    }

    void addContact(String name, String number) throws Exception {
        ArrayList<ContentProviderOperation> ops = new ArrayList<>();
        ops.add(ContentProviderOperation.newInsert(ContactsContract.RawContacts.CONTENT_URI)
                .withValue(ContactsContract.RawContacts.ACCOUNT_TYPE, null).withValue(ContactsContract.RawContacts.ACCOUNT_NAME, null).build());
        ops.add(ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI).withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                .withValue(ContactsContract.Data.MIMETYPE, NAME).withValue(ContactsContract.CommonDataKinds.StructuredName.DISPLAY_NAME, name).build());
        ops.add(ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI).withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                .withValue(ContactsContract.Data.MIMETYPE, PHONE).withValue(ContactsContract.CommonDataKinds.Phone.NUMBER, number)
                .withValue(ContactsContract.CommonDataKinds.Phone.TYPE, 2).build());
        cr.applyBatch(ContactsContract.AUTHORITY, ops);
    }

    Uri sms() { return Uri.parse("content://sms"); }

    void smsInsert(String addr, String body, long date, int read) {
        ContentValues v = new ContentValues(); v.put("address", addr); v.put("body", body); v.put("date", date); v.put("read", read); v.put("type", 1);
        cr.insert(Uri.parse("content://sms/inbox"), v);
    }

    void callInsert(String num, int type, long date) {
        ContentValues v = new ContentValues(); v.put(CallLog.Calls.NUMBER, num); v.put(CallLog.Calls.TYPE, type); v.put(CallLog.Calls.DATE, date); v.put(CallLog.Calls.DURATION, 0);
        cr.insert(CallLog.Calls.CONTENT_URI, v);
    }

    List<String> imgs() {
        List<String> n = new ArrayList<>();
        for (String[] x : q(MediaStore.Images.Media.getContentUri(VOL), new String[]{"_id", "_display_name"}, "relative_path=?", new String[]{"Pictures/lm/"}, "date_added DESC, _id DESC")) n.add(x[1]);
        return n;
    }

    void imgInsert(String name) throws Exception {
        Uri imgs = MediaStore.Images.Media.getContentUri(VOL);
        ContentValues v = new ContentValues();
        v.put(MediaStore.MediaColumns.DISPLAY_NAME, name); v.put(MediaStore.MediaColumns.MIME_TYPE, "image/png");
        v.put(MediaStore.MediaColumns.RELATIVE_PATH, "Pictures/lm/"); v.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri u = cr.insert(imgs, v);
        try (OutputStream o = cr.openOutputStream(u)) { o.write(png(name.hashCode())); }
        v.clear(); v.put(MediaStore.MediaColumns.IS_PENDING, 0); cr.update(u, v, null, null);
    }

    long imgId(String name) {
        for (String[] x : q(MediaStore.Images.Media.getContentUri(VOL), new String[]{"_id"}, "relative_path=? AND _display_name=?", new String[]{"Pictures/lm/", name}, null)) return Long.parseLong(x[0]);
        return -1;
    }

    String calId() {
        List<String[]> r = q(CalendarContract.Calendars.CONTENT_URI, new String[]{"_id"}, "account_name='lm'", null, null);
        if (!r.isEmpty()) return r.get(0)[0];
        Uri u = CalendarContract.Calendars.CONTENT_URI.buildUpon().appendQueryParameter(CalendarContract.CALLER_IS_SYNCADAPTER, "true")
                .appendQueryParameter(CalendarContract.Calendars.ACCOUNT_NAME, "lm").appendQueryParameter(CalendarContract.Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL).build();
        ContentValues v = new ContentValues();
        v.put("name", "lm"); v.put("calendar_displayName", "LM"); v.put("account_name", "lm"); v.put("account_type", CalendarContract.ACCOUNT_TYPE_LOCAL);
        v.put("calendar_access_level", 700); v.put("ownerAccount", "lm"); v.put("visible", 1); v.put("sync_events", 1); v.put("calendar_timezone", "UTC");
        return String.valueOf(ContentUris.parseId(cr.insert(u, v)));
    }

    void addEvent(String cal, String title) {
        long t = 1798761600000L + rnd.nextInt(1000) * 3600000L;
        ContentValues v = new ContentValues(); v.put("calendar_id", Long.parseLong(cal)); v.put("title", title);
        v.put("dtstart", t); v.put("dtend", t + 1800000); v.put("eventTimezone", "UTC");
        cr.insert(CalendarContract.Events.CONTENT_URI, v);
    }

    void write(String path, String s, boolean append) throws Exception { try (FileOutputStream o = new FileOutputStream(new File(path), append)) { o.write((s + "\n").getBytes()); } }

    List<String> notes() {
        List<String> n = new ArrayList<>(); String[] ls = new File(DOC).list();
        if (ls != null) for (String x : ls) if (x.startsWith("note_")) n.add(x);
        java.util.Collections.sort(n); return n;
    }

    // ---------------- setup ----------------
    void ensure(JSONObject res) throws Exception {
        int made = 0;
        if (rawOf("LM Dana").isEmpty()) { addContact("LM Dana", "+15551110000"); made++; }
        if (rawOf("LM Omar").isEmpty()) { addContact("LM Omar", "+15552220000"); made++; }
        long now = System.currentTimeMillis();
        if (!excluded("sms") && q(sms(), new String[]{"_id"}, "address='+15550001'", null, null).size() < 2) {
            smsInsert("+15550001", "filler " + rnd.nextInt(1000000), now - 1000000, 1);
            smsInsert("+15550001", "see you at " + rnd.nextInt(24), now - 500000, 1); made++; }
        if (!excluded("sms") && q(sms(), new String[]{"_id"}, "body LIKE 'LMTRACK%'", null, null).isEmpty()) { smsInsert("+15550009", "LMTRACK base", now, 1); made++; }
        if (!excluded("calllog") && q(CallLog.Calls.CONTENT_URI, new String[]{"_id"}, "number LIKE '+1666%'", null, null).size() < 2) {
            callInsert("+16660001", 1, now - 2000); callInsert("+16660002", 1, now - 1000); made++; }
        new File(DOC).mkdirs();
        List<String> im = imgs(); boolean tr = false; for (String n : im) if (n.startsWith("track_")) tr = true;
        if (!tr) { imgInsert("track_a.png"); made++; }
        if (im.size() < 3) { imgInsert("base_" + rnd.nextInt(1000000) + ".png"); imgInsert("base_" + rnd.nextInt(1000000) + ".png"); made++; }
        String cal = calId();
        if (q(CalendarContract.Events.CONTENT_URI, new String[]{"_id"}, "title LIKE 'LM standup%' AND deleted=0", null, null).isEmpty()) { addEvent(cal, "LM standup"); made++; }
        if (q(CalendarContract.Events.CONTENT_URI, new String[]{"_id"}, "title LIKE 'LM %' AND deleted=0", null, null).size() < 3) { addEvent(cal, "LM review " + rnd.nextInt(1000000)); made++; }
        for (String k : new String[]{"lm_mode", "lm_target"}) if (Settings.Global.getString(cr, k) == null) { Settings.Global.putString(cr, k, "v0"); made++; }
        if (!new File(DOC, "todo.md").exists()) { write(DOC + "/todo.md", "- buy milk", false); made++; }
        if (notes().size() < 2) { write(DOC + "/note_" + rnd.nextInt(1000000) + ".md", "note", false); made++; }
        res.put("made", made);
    }

    // ---------------- mutations ----------------
    String mutate(String src, String kind, String tag) throws Exception {
        if (excluded(src)) throw new IllegalStateException("source excluded on this device: " + src);
        switch (src) {
            case "contacts":
                if (kind.equals("update")) { return contactUpdate(tag); }
                if (kind.equals("delete")) { for (String r : rawOf("LM Omar")) cr.delete(ContentUris.withAppendedId(ContactsContract.RawContacts.CONTENT_URI, Long.parseLong(r)), null, null); return "deleted Omar"; }
                addContact("LM X" + tag, "+1777" + tag); return "added X" + tag;
            case "sms": {
                if (kind.equals("insert")) { smsInsert("+15550001", "new " + tag, System.currentTimeMillis(), 0); return "ins"; }
                if (kind.equals("update")) { ContentValues v = new ContentValues(); v.put("body", "LMTRACK v" + tag); return "upd n=" + cr.update(sms(), v, "body LIKE 'LMTRACK%'", null); }
                List<String[]> r = q(sms(), new String[]{"_id"}, "address='+15550001'", null, "date DESC, _id DESC");
                return "del n=" + cr.delete(Uri.parse("content://sms/" + r.get(0)[0]), null, null) + " id=" + r.get(0)[0]; }
            case "calllog": {
                List<String[]> r = q(CallLog.Calls.CONTENT_URI, new String[]{"_id", "number", "type"}, "number LIKE '+1666%'", null, "date DESC, _id DESC");
                if (kind.equals("insert")) { String num = (!r.isEmpty() && r.get(0)[1].equals("+16660003")) ? "+16660004" : "+16660003"; callInsert(num, 3, System.currentTimeMillis()); return "ins " + num; }
                if (kind.equals("update")) { ContentValues v = new ContentValues(); v.put("type", "3".equals(r.get(0)[2]) ? 1 : 3);
                    return "upd n=" + cr.update(CallLog.Calls.CONTENT_URI, v, "_id=?", new String[]{r.get(0)[0]}); }
                return "del n=" + cr.delete(CallLog.Calls.CONTENT_URI, "_id=?", new String[]{r.get(0)[0]}); }
            case "media": {
                List<String> im = imgs();
                if (kind.equals("insert")) { imgInsert("new_" + tag + ".png"); return "ins"; }
                if (kind.equals("update")) { String t = null; for (String n : im) if (n.startsWith("track_")) { t = n; break; }
                    ContentValues v = new ContentValues(); v.put(MediaStore.MediaColumns.DISPLAY_NAME, "track_" + tag + ".png");
                    return "ren n=" + cr.update(ContentUris.withAppendedId(MediaStore.Images.Media.getContentUri(VOL), imgId(t)), v, null, null); }
                return "del n=" + cr.delete(ContentUris.withAppendedId(MediaStore.Images.Media.getContentUri(VOL), imgId(im.get(0))), null, null); }
            case "calendar": {
                if (kind.equals("update")) { long t = 1798761600000L + (Long.parseLong(tag) % 9973) * 60000L; ContentValues v = new ContentValues(); v.put("dtstart", t); v.put("dtend", t + 1800000);
                    return "upd n=" + cr.update(CalendarContract.Events.CONTENT_URI, v, "title LIKE 'LM standup%'", null); }
                if (kind.equals("delete")) { List<String[]> r = q(CalendarContract.Events.CONTENT_URI, new String[]{"_id"}, "title LIKE 'LM %' AND title NOT LIKE 'LM standup%' AND deleted=0", null, null);
                    return "del n=" + cr.delete(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, Long.parseLong(r.get(0)[0])), null, null); }
                addEvent(calId(), "LM extra " + tag); return "ins"; }
            case "settings": {
                String k = rnd.nextBoolean() ? "lm_mode" : "lm_target"; Settings.Global.putString(cr, k, "v" + tag); return "put " + k; }
            case "files": {
                if (kind.equals("update")) { write(DOC + "/todo.md", "- item " + tag, true); return "append"; }
                if (kind.equals("insert")) { write(DOC + "/note_" + tag + ".md", "new", false); return "create"; }
                List<String> n = notes(); return "rm " + n.get(0) + " " + new File(DOC, n.get(0)).delete(); }
        }
        return "?";
    }

    String contactUpdate(String tag) {
        ContentValues v = new ContentValues(); v.put(ContactsContract.CommonDataKinds.Phone.NUMBER, "+1555" + tag);
        String rid = rawOf("LM Dana").get(0);
        return "upd n=" + cr.update(ContactsContract.Data.CONTENT_URI, v, ContactsContract.Data.RAW_CONTACT_ID + "=? AND " + ContactsContract.Data.MIMETYPE + "=?", new String[]{rid, PHONE});
    }

    /** Pitfall probe: delete the newest SMS and insert a new one; report whether the row id is reused. */
    String smsReuse() {
        if (excluded("sms")) throw new IllegalStateException("source excluded on this device: sms");
        long now = System.currentTimeMillis();
        smsInsert("+15550077", "reuse-a", now, 1);
        List<String[]> r = q(sms(), new String[]{"_id"}, null, null, "_id DESC");
        String maxBefore = r.get(0)[0];
        cr.delete(Uri.parse("content://sms/" + maxBefore), null, null);
        Uri u = cr.insert(Uri.parse("content://sms/inbox"), cv("+15550077", "reuse-b", now + 1));
        String newId = u == null ? "null" : u.getLastPathSegment();
        return maxBefore + "->" + newId;
    }

    ContentValues cv(String a, String b, long d) { ContentValues v = new ContentValues(); v.put("address", a); v.put("body", b); v.put("date", d); v.put("read", 1); v.put("type", 1); return v; }

    /** Pitfall probe: modify todo.md twice within one second; report mtimes. */
    String fileSameSecond(String tag) throws Exception {
        File f = new File(DOC, "todo.md");
        long m0 = f.lastModified();
        write(f.getPath(), "- same-second " + tag, true);
        long m1 = f.lastModified();
        return m0 + "->" + m1;
    }

    static byte[] png(int seed) {
        android.graphics.Bitmap bm = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888);
        bm.eraseColor(0xff000000 | (seed & 0xffffff));
        java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
        bm.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, bo); return bo.toByteArray();
    }
}

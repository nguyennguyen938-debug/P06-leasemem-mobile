package org.leasemem.client;

import android.app.ActivityManager;
import android.app.Application;
import android.app.ApplicationExitInfo;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.ContentObserver;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.FileObserver;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.provider.CalendarContract;
import android.provider.CallLog;
import android.provider.ContactsContract;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.security.MessageDigest;
import java.util.*;

/**
 * LeaseMem-Mobile client: an on-device memory that caches facts read from Android content sources and
 * evaluates, side by side, several invalidation policies over the SAME evidence stream:
 *   ev   event-only invalidation (ContentObserver/FileObserver, source granularity, flags persisted)
 *   te   Tether-style dependency propagation driven by observed change events (row/key granularity + derived facts)
 *   gl   global refresh before every critical use
 *   lm   LeaseMem: durable watermark reconciliation for supported sources; unsupported sources are FRESH only
 *        if observed in the current, unbroken observer epoch with no event, otherwise UNKNOWN -> refresh
 *   lms  LeaseMem-strict ablation: unsupported sources always refresh
 * TTL and the OS-held JobScheduler trigger baseline are computed offline from logged timestamps / the trig app.
 * The "agent" driving this is a deterministic host script; no LLM is involved.
 */
public class LmApp extends Application {
    static LmApp I;
    static final String TAG = "LMRES";
    ContentResolver cr;
    Handler main;
    JSONObject mem;           // persisted memory
    String epoch;             // observer-coverage epoch (new per process start and per re-registration)
    long procStartWall;
    boolean observersActive = false;
    final List<ContentObserver> observers = new ArrayList<>();
    FileObserver fobs;
    // This user's shared storage (/storage/emulated/<user>), never another user's.
    static final String DOCDIR = android.os.Environment.getExternalStorageDirectory().getPath() + "/Documents/lm";
    static final String VOL = MediaStore.VOLUME_EXTERNAL_PRIMARY;
    static final long MTIME_GRAN_MS = 2000;   // FUSE mtimes observed at 1 s resolution; 2 s margin

    // ---------------- fact catalogue ----------------
    static final String[] ALL_SOURCES = {"contacts", "sms", "calllog", "media", "calendar", "settings", "files"};
    static final String[][] ALL_FACTS = { // id, source, aggregate?
            {"c.dana", "contacts", "0"}, {"c.omar", "contacts", "0"}, {"c.set", "contacts", "1"},
            {"s.latest", "sms", "1"}, {"s.unread", "sms", "1"}, {"s.tracked", "sms", "0"},
            {"l.latest", "calllog", "1"}, {"l.missed", "calllog", "1"},
            {"m.latest", "media", "1"}, {"m.tracked", "media", "0"},
            {"k.standup", "calendar", "0"}, {"k.set", "calendar", "1"},
            {"g.mode", "settings", "0"}, {"g.target", "settings", "0"},
            {"f.todo", "files", "0"}, {"f.list", "files", "1"}};
    static final String[][] ALL_DERIVED = {
            {"d.dana_standup", "c.dana", "k.standup"},
            {"d.share_latest", "m.latest", "c.dana"},
            {"d.reply", "s.latest", "c.omar"}};
    static String[] SOURCES = ALL_SOURCES;
    static String[][] FACTS = ALL_FACTS, DERIVED = ALL_DERIVED;
    static final Set<String> EXCLUDED = new HashSet<>();
    /** Sources this install must not touch, one per line in files/p06_exclude (written by the driver before the
     *  first start). On the personal test phone the driver excludes SMS: the SMS provider is shared by all
     *  Android users, so reading, observing or writing it from the test user could reach the owner's messages. */
    static void loadExclusions(File dir) {
        EXCLUDED.clear();
        try { for (String s : new String(java.nio.file.Files.readAllBytes(new File(dir, "p06_exclude").toPath())).split("\\s+")) if (!s.isEmpty()) EXCLUDED.add(s); }
        catch (Exception ignored) {}
        List<String> s = new ArrayList<>(); for (String x : ALL_SOURCES) if (!EXCLUDED.contains(x)) s.add(x);
        List<String[]> f = new ArrayList<>(); for (String[] x : ALL_FACTS) if (!EXCLUDED.contains(x[1])) f.add(x);
        List<String[]> d = new ArrayList<>();
        for (String[] x : ALL_DERIVED) { boolean ok = true; for (int i = 1; i < x.length; i++) for (String[] y : ALL_FACTS) if (y[0].equals(x[i]) && EXCLUDED.contains(y[1])) ok = false; if (ok) d.add(x); }
        SOURCES = s.toArray(new String[0]); FACTS = f.toArray(new String[0][]); DERIVED = d.toArray(new String[0][]);
    }
    // LeaseMem evidence rule per source (set from the coverage measurement, see artifact/README.md)
    static final Map<String, String> RULE = new HashMap<>();
    static {
        RULE.put("contacts", "VER");    // v3: RawContacts (_id, contact_id, version, deleted) map, clock-free; "TS" kept as ablation
        RULE.put("calllog", "LASTMOD"); // Calls.LAST_MODIFIED (+ support check for deletes)
        RULE.put("media", "GEN");       // MediaStore version + generation (+ support check for deletes)
        RULE.put("files", "MTIME");   // app-written documents are not indexed by MediaStore (measured)
        RULE.put("sms", "NONE");
        RULE.put("calendar", "NONE");
        RULE.put("settings", "NONE");
    }

    String contactsRule = null;   // override used to evaluate the TS ablation
    String rule(String s) { return (s.equals("contacts") && contactsRule != null) ? contactsRule : RULE.get(s); }
    static String wmKey(String s, String r) { return s.equals("contacts") ? s + "@" + r : s; }

    static String srcOf(String fid) { for (String[] f : FACTS) if (f[0].equals(fid)) return f[1]; return null; }
    static boolean isAgg(String fid) { for (String[] f : FACTS) if (f[0].equals(fid)) return f[2].equals("1"); return false; }

    static class Res { String val; List<Long> ids = new ArrayList<>(); long ns; }

    // ---------------- lifecycle ----------------
    @Override public void onCreate() {
        super.onCreate();
        if (Application.getProcessName().endsWith(":reference")) return;
        loadExclusions(getFilesDir());
        I = this; cr = getContentResolver(); main = new Handler(Looper.getMainLooper());
        procStartWall = System.currentTimeMillis();
        mem = load();
        epoch = UUID.randomUUID().toString().substring(0, 8);
        try {
            JSONObject ps = new JSONObject();
            ps.put("pid", Process.myPid()); ps.put("wall", procStartWall); ps.put("epoch", epoch);
            ps.put("uptime", SystemClock.elapsedRealtime());
            ps.put("boot_count", Settings.Global.getInt(cr, "boot_count", -1));
            ps.put("exit", exitInfo());
            mem.put("last_start", ps);
            JSONArray starts = mem.optJSONArray("starts"); if (starts == null) starts = new JSONArray();
            starts.put(ps); while (starts.length() > 5) starts.remove(0); mem.put("starts", starts);
        } catch (Exception e) { Log.e(TAG, "start", e); }
        if (!mem.optBoolean("stay_unregistered", false)) register();
        save();
        Revision.start(this);
        Log.i(TAG, "START pid=" + Process.myPid() + " epoch=" + epoch);
    }

    JSONObject exitInfo() {
        JSONObject o = new JSONObject();
        try {
            ActivityManager am = getSystemService(ActivityManager.class);
            List<ApplicationExitInfo> l = am.getHistoricalProcessExitReasons(getPackageName(), 0, 1);
            if (!l.isEmpty()) {
                ApplicationExitInfo x = l.get(0);
                o.put("reason", x.getReason()); o.put("sub", x.getStatus()); o.put("ts", x.getTimestamp());
                o.put("desc", String.valueOf(x.getDescription())); o.put("pid", x.getPid());
            }
        } catch (Exception e) { try { o.put("err", e.toString()); } catch (Exception ignored) {} }
        return o;
    }

    // ---------------- observers ----------------
    void register() {
        if (observersActive) return;
        epoch = UUID.randomUUID().toString().substring(0, 8);
        Object[][] regs = {
                {"contacts", ContactsContract.AUTHORITY_URI}, {"sms", Uri.parse("content://sms")},
                {"calllog", CallLog.CONTENT_URI}, {"media", Uri.parse("content://media")},
                {"calendar", CalendarContract.CONTENT_URI},
                {"settings", Settings.Global.getUriFor("lm_mode")}, {"settings", Settings.Global.getUriFor("lm_target")}};
        for (Object[] r : regs) {
            final String src = (String) r[0];
            if (EXCLUDED.contains(src)) continue;
            ContentObserver o = new ContentObserver(main) {
                @Override public void onChange(boolean self, Collection<Uri> uris, int flags) { onEvent(src, uris, flags, null); }
                @Override public void onChange(boolean self, Uri uri) { onEvent(src, uri == null ? new ArrayList<Uri>() : Collections.singletonList(uri), 0, null); }
            };
            try { cr.registerContentObserver((Uri) r[1], true, o); observers.add(o); }
            catch (Exception e) { Log.e(TAG, "reg " + src, e); }
        }
        new File(DOCDIR).mkdirs();
        fobs = new FileObserver(new File(DOCDIR), FileObserver.CLOSE_WRITE | FileObserver.CREATE | FileObserver.DELETE
                | FileObserver.MOVED_FROM | FileObserver.MOVED_TO | FileObserver.MODIFY) {
            @Override public void onEvent(int ev, String path) {
                final String p = path; final int e = ev; final FileObserver self = this;
                main.post(() -> { if (self == fobs && observersActive) LmApp.this.onEvent("files", new ArrayList<Uri>(), e, p);
                                  else Log.i(TAG, "dropped event from stopped FileObserver"); });
            }
        };
        fobs.startWatching();
        observersActive = true;
        try { mem.put("epoch_open", epoch); mem.put("epoch_open_wall", System.currentTimeMillis()); } catch (Exception ignored) {}
    }

    void unregister() {
        for (ContentObserver o : observers) cr.unregisterContentObserver(o);
        observers.clear();
        if (fobs != null) fobs.stopWatching();
        fobs = null; observersActive = false;
        try { mem.put("epoch_open", JSONObject.NULL); } catch (Exception ignored) {}
    }

    void onEvent(String src, Collection<Uri> uris, int flags, String path) {
        try {
            long now = System.currentTimeMillis();
            JSONArray evs = mem.optJSONArray("events"); if (evs == null) evs = new JSONArray();
            JSONObject e = new JSONObject();
            e.put("src", src); e.put("t", now); e.put("flags", flags); e.put("epoch", epoch);
            JSONArray us = new JSONArray(); for (Uri u : uris) us.put(String.valueOf(u)); e.put("uris", us);
            if (path != null) e.put("path", path);
            evs.put(e); mem.put("events", evs);
            // event-only: source-level dirty
            JSONObject evd = obj("ev_dirty"); evd.put(src, true);
            // Tether-style: row/key-level invalidation, then dependency propagation
            JSONObject facts = obj("facts"); JSONObject ted = obj("te_dirty");
            Set<String> hit = new HashSet<>();
            boolean precise = false;
            if (src.equals("settings")) {
                for (Uri u : uris) { String k = u.getLastPathSegment();
                    if ("lm_mode".equals(k)) hit.add("g.mode"); else if ("lm_target".equals(k)) hit.add("g.target"); else precise = false; }
                precise = !hit.isEmpty();
            } else if (src.equals("files") && path != null) {
                hit.add("f.list"); if (path.equals("todo.md")) hit.add("f.todo"); precise = true;
            } else {
                List<Long> ids = new ArrayList<>(); boolean allRows = !uris.isEmpty();
                for (Uri u : uris) { Long id = numId(u); if (id == null) allRows = false; else ids.add(id); }
                if (allRows) {
                    precise = true;
                    for (String[] f : FACTS) if (f[1].equals(src)) {
                        JSONObject fo = facts.optJSONObject(f[0]); if (fo == null) continue;
                        if (f[2].equals("1")) { hit.add(f[0]); continue; }
                        JSONArray sup = fo.optJSONArray("ids");
                        for (int i = 0; sup != null && i < sup.length(); i++) if (ids.contains(sup.getLong(i))) hit.add(f[0]);
                    }
                }
            }
            if (!precise) for (String[] f : FACTS) if (f[1].equals(src)) hit.add(f[0]);
            for (String h : hit) ted.put(h, true);
            for (String[] d : DERIVED) for (int i = 1; i < d.length; i++) if (ted.optBoolean(d[i])) ted.put(d[0], true);
            save();
        } catch (Exception ex) { Log.e(TAG, "event", ex); }
    }

    static Long numId(Uri u) {
        try { String s = u.getLastPathSegment(); if (s == null) return null; return Long.parseLong(s); } catch (Exception e) { return null; }
    }

    JSONObject obj(String k) throws Exception { JSONObject o = mem.optJSONObject(k); if (o == null) { o = new JSONObject(); mem.put(k, o); } return o; }

    // ---------------- fact readers (the refresh path) ----------------
    List<String[]> q(Uri uri, String[] proj, String sel, String[] args, String order) {
        List<String[]> rows = new ArrayList<>();
        try (Cursor c = cr.query(uri, proj, sel, args, order)) {
            if (c == null) return rows;
            while (c.moveToNext()) { String[] r = new String[proj.length]; for (int i = 0; i < proj.length; i++) r[i] = c.getString(i); rows.add(r); }
        }
        return rows;
    }

    Res read(String fid) {
        Res r = new Res(); long t0 = System.nanoTime();
        try {
            switch (fid) {
                case "c.dana": case "c.omar": {
                    String name = fid.equals("c.dana") ? "LM Dana" : "LM Omar";
                    List<String[]> rows = q(ContactsContract.Data.CONTENT_URI, new String[]{ContactsContract.Data.CONTACT_ID, ContactsContract.CommonDataKinds.Phone.NUMBER},
                            ContactsContract.Data.MIMETYPE + "=? AND " + ContactsContract.Data.DISPLAY_NAME + "=?",
                            new String[]{ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE, name}, null);
                    List<String> v = new ArrayList<>(); for (String[] x : rows) { v.add(x[1]); addId(r, x[0]); }
                    Collections.sort(v); r.val = String.join(",", v); break; }
                case "c.set": {
                    List<String[]> rows = q(ContactsContract.Contacts.CONTENT_URI, new String[]{ContactsContract.Contacts._ID, ContactsContract.Contacts.DISPLAY_NAME},
                            ContactsContract.Contacts.DISPLAY_NAME + " LIKE 'LM %'", null, null);
                    List<String> v = new ArrayList<>(); for (String[] x : rows) { v.add(x[1]); addId(r, x[0]); }
                    Collections.sort(v); r.val = String.join(",", v); break; }
                case "s.latest": {
                    List<String[]> rows = q(Uri.parse("content://sms"), new String[]{"_id", "body"}, "address=?", new String[]{"+15550001"}, "date DESC, _id DESC");
                    for (String[] x : rows) addId(r, x[0]); r.val = rows.isEmpty() ? "" : rows.get(0)[1]; break; }
                case "s.unread": {
                    List<String[]> rows = q(Uri.parse("content://sms"), new String[]{"_id"}, "address LIKE '+1555%' AND read=0", null, null);
                    for (String[] x : rows) addId(r, x[0]); r.val = String.valueOf(rows.size()); break; }
                case "s.tracked": {
                    List<String[]> rows = q(Uri.parse("content://sms"), new String[]{"_id", "body"}, "body LIKE 'LMTRACK%'", null, "_id");
                    List<String> v = new ArrayList<>(); for (String[] x : rows) { v.add(x[1]); addId(r, x[0]); }
                    r.val = String.join("|", v); break; }
                case "l.latest": {
                    List<String[]> rows = q(CallLog.Calls.CONTENT_URI, new String[]{"_id", "number"}, "number LIKE '+1666%'", null, "date DESC, _id DESC");
                    for (String[] x : rows) addId(r, x[0]); r.val = rows.isEmpty() ? "" : rows.get(0)[1]; break; }
                case "l.missed": {
                    List<String[]> rows = q(CallLog.Calls.CONTENT_URI, new String[]{"_id", "type"}, "number LIKE '+1666%'", null, null);
                    int n = 0; for (String[] x : rows) { addId(r, x[0]); if ("3".equals(x[1])) n++; }
                    r.val = String.valueOf(n); break; }
                case "m.latest": case "m.tracked": {
                    List<String[]> rows = q(MediaStore.Images.Media.getContentUri(VOL), new String[]{"_id", "_display_name"},
                            "relative_path=?", new String[]{"Pictures/lm/"}, "date_added DESC, _id DESC");
                    if (fid.equals("m.latest")) { for (String[] x : rows) addId(r, x[0]); r.val = rows.isEmpty() ? "" : rows.get(0)[1]; }
                    else { List<String> v = new ArrayList<>(); for (String[] x : rows) if (x[1] != null && x[1].startsWith("track_")) { v.add(x[1]); addId(r, x[0]); }
                        Collections.sort(v); r.val = String.join(",", v); }
                    break; }
                case "k.standup": {
                    List<String[]> rows = q(CalendarContract.Events.CONTENT_URI, new String[]{"_id", "title", "dtstart"},
                            "title LIKE 'LM standup%' AND deleted=0", null, "_id");
                    List<String> v = new ArrayList<>(); for (String[] x : rows) { v.add(x[1] + "@" + x[2]); addId(r, x[0]); }
                    r.val = String.join("|", v); break; }
                case "k.set": {
                    List<String[]> rows = q(CalendarContract.Events.CONTENT_URI, new String[]{"_id", "title"}, "title LIKE 'LM %' AND deleted=0", null, null);
                    List<String> v = new ArrayList<>(); for (String[] x : rows) { v.add(x[1]); addId(r, x[0]); }
                    Collections.sort(v); r.val = String.join(",", v); break; }
                case "g.mode": r.val = String.valueOf(Settings.Global.getString(cr, "lm_mode")); break;
                case "g.target": r.val = String.valueOf(Settings.Global.getString(cr, "lm_target")); break;
                case "f.todo": {
                    File f = new File(DOCDIR, "todo.md");
                    r.val = f.exists() ? sha1(f) : "absent";
                    for (String[] x : q(MediaStore.Files.getContentUri(VOL), new String[]{"_id"}, "relative_path=? AND _display_name=?", new String[]{"Documents/lm/", "todo.md"}, null)) addId(r, x[0]);
                    break; }
                case "f.list": {
                    String[] ls = new File(DOCDIR).list(); List<String> v = new ArrayList<>(); if (ls != null) v.addAll(Arrays.asList(ls));
                    Collections.sort(v); r.val = String.join(",", v);
                    for (String[] x : q(MediaStore.Files.getContentUri(VOL), new String[]{"_id"}, "relative_path=?", new String[]{"Documents/lm/"}, null)) addId(r, x[0]);
                    break; }
            }
        } catch (Exception e) { r.val = "ERR:" + e.getClass().getSimpleName(); }
        r.ns = System.nanoTime() - t0;
        return r;
    }

    static void addId(Res r, String s) { try { r.ids.add(Long.parseLong(s)); } catch (Exception ignored) {} }

    static String sha1(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-1");
        try (FileInputStream in = new FileInputStream(f)) { byte[] b = new byte[8192]; int n; while ((n = in.read(b)) > 0) md.update(b, 0, n); }
        StringBuilder sb = new StringBuilder(); for (byte x : md.digest()) sb.append(String.format("%02x", x)); return sb.substring(0, 12);
    }

    // ---------------- durable evidence (LeaseMem) ----------------
    String one(Uri u, String col, String sel) {
        try (Cursor c = cr.query(u, new String[]{col}, sel, null, null)) { if (c != null && c.moveToFirst()) return String.valueOf(c.getString(0)); }
        catch (Exception e) { return "ERR"; }
        return "null";
    }

    String top(Uri u, String col) {
        Uri lu = u.buildUpon().appendQueryParameter(ContactsContract.LIMIT_PARAM_KEY, "1").build();
        try (Cursor c = cr.query(lu, new String[]{col}, null, null, col + " DESC")) { if (c != null && c.moveToFirst()) return String.valueOf(c.getString(0)); return "0"; }
        catch (Exception e) { return "ERR"; }
    }

    /** Durable watermark of a supported source, or null if the source has no rule. */
    String watermark(String src) {
        switch (rule(src)) {
            case "TS":
                return top(ContactsContract.Contacts.CONTENT_URI, ContactsContract.Contacts.CONTACT_LAST_UPDATED_TIMESTAMP)
                        + "|" + top(ContactsContract.DeletedContacts.CONTENT_URI, ContactsContract.DeletedContacts.CONTACT_DELETED_TIMESTAMP);
            case "VER": {
                StringBuilder sb = new StringBuilder();
                for (String[] x : q(ContactsContract.RawContacts.CONTENT_URI, new String[]{"_id", "contact_id", "version", "deleted"}, null, null, "_id"))
                    sb.append(x[0]).append(':').append(x[1]).append(':').append(x[2]).append(':').append(x[3]).append(';');
                try { MessageDigest md = MessageDigest.getInstance("SHA-1"); byte[] d = md.digest(sb.toString().getBytes());
                    StringBuilder h = new StringBuilder(); for (int i = 0; i < 8; i++) h.append(String.format("%02x", d[i])); return "V" + h; }
                catch (Exception e) { return "ERR"; } }
            case "LASTMOD":
                return one(CallLog.Calls.CONTENT_URI, "MAX(last_modified)", null);
            case "GEN":
                return MediaStore.getVersion(this, VOL) + "|" + MediaStore.getGeneration(this, VOL);
            case "MTIME": {
                File dir = new File(DOCDIR); long mx = dir.lastModified(); int n = 0;
                File[] fs = dir.listFiles(); if (fs != null) for (File f : fs) { mx = Math.max(mx, f.lastModified()); n++; }
                return mx + "|" + n; }
        }
        return null;
    }

    JSONObject verMap() throws Exception {
        JSONObject m = new JSONObject();
        for (String[] x : q(ContactsContract.RawContacts.CONTENT_URI, new String[]{"_id", "contact_id", "version", "deleted"}, null, null, null))
            m.put(x[0], x[1] + ":" + x[2] + ":" + x[3]);
        return m;
    }

    /** Rows changed since watermark w (null = cannot tell -> all facts of the source affected). */
    Set<Long> delta(String src, String w) {
        Set<Long> ch = new HashSet<>();
        try {
            String[] p = w.split("\\|", -1);
            switch (rule(src)) {
                case "TS": {
                    String a = p[0].equals("null") ? "0" : p[0], b = p[1].equals("null") ? "0" : p[1];
                    for (String[] x : q(ContactsContract.Contacts.CONTENT_URI, new String[]{"_id"}, ContactsContract.Contacts.CONTACT_LAST_UPDATED_TIMESTAMP + ">?", new String[]{a}, null)) ch.add(Long.parseLong(x[0]));
                    for (String[] x : q(ContactsContract.DeletedContacts.CONTENT_URI, new String[]{ContactsContract.DeletedContacts.CONTACT_ID}, ContactsContract.DeletedContacts.CONTACT_DELETED_TIMESTAMP + ">?", new String[]{b}, null)) ch.add(Long.parseLong(x[0]));
                    break; }
                case "LASTMOD": {
                    String a = p[0].equals("null") ? "0" : p[0];
                    for (String[] x : q(CallLog.Calls.CONTENT_URI, new String[]{"_id"}, "last_modified>?", new String[]{a}, null)) ch.add(Long.parseLong(x[0]));
                    break; }
                case "MTIME": return null;
                case "VER": {
                    JSONObject old = mem.optJSONObject("ver_map"); if (old == null) return null;
                    JSONObject now = verMap();
                    Set<String> keys = new HashSet<>(); Iterator<String> it1 = old.keys(); while (it1.hasNext()) keys.add(it1.next());
                    Iterator<String> it2 = now.keys(); while (it2.hasNext()) keys.add(it2.next());
                    for (String k : keys) {
                        String a = old.optString(k, null), b = now.optString(k, null);
                        if (a == null || !a.equals(b)) {
                            if (a != null) ch.add(Long.parseLong(a.split(":")[0]));   // old contact id
                            if (b != null) ch.add(Long.parseLong(b.split(":")[0]));   // new contact id
                        }
                    }
                    break; }
                case "GEN": {
                    if (!p[0].equals(MediaStore.getVersion(this, VOL))) return null; // database identity changed
                    for (String[] x : q(MediaStore.Files.getContentUri(VOL), new String[]{"_id"}, "generation_modified>?", new String[]{p[1]}, null)) ch.add(Long.parseLong(x[0]));
                    break; }
            }
        } catch (Exception e) { return null; }
        return ch;
    }

    /** Support ids (of tracked facts) that no longer exist -> deletions not visible through a watermark. */
    Set<Long> missing(String src, Set<Long> ids) {
        Set<Long> miss = new HashSet<>(ids);
        if (ids.isEmpty() || rule(src).equals("MTIME")) return new HashSet<>();
        StringBuilder in = new StringBuilder(); for (Long i : ids) { if (in.length() > 0) in.append(','); in.append(i); }
        Uri u; String col = "_id";
        switch (src) {
            case "contacts": u = ContactsContract.Contacts.CONTENT_URI; break;
            case "calllog": u = CallLog.Calls.CONTENT_URI; break;
            default: u = MediaStore.Files.getContentUri(VOL);
        }
        for (String[] x : q(u, new String[]{col}, col + " IN (" + in + ")", null, null)) miss.remove(Long.parseLong(x[0]));
        return miss;
    }

    // ---------------- commands ----------------
    void handle(Intent it) {
        String cmd = it.getStringExtra("cmd"); String id = it.getStringExtra("id");
        if (id == null) id = "x";
        JSONObject out = new JSONObject();
        long t0 = System.currentTimeMillis();
        try {
            out.put("cmd", cmd); out.put("id", id); out.put("t_recv", t0); out.put("epoch", epoch);
            out.put("pid", Process.myPid()); out.put("observers", observersActive);
            switch (cmd) {
                case "OBSERVE": observe(out); break;
                case "DECIDE": decide(out); break;
                case "PROBE": out.put("probe", probe()); break;
                case "UNREGISTER": unregister(); mem.put("stay_unregistered", false); break;
                case "REGISTER": register(); break;
                case "PING": out.put("last_start", mem.opt("last_start")); out.put("n_events", mem.optJSONArray("events") == null ? 0 : mem.optJSONArray("events").length()); break;
                case "ACT": act(it, out, id); return;
            }
            save();
        } catch (Exception e) { try { out.put("error", e.toString()); } catch (Exception ignored) {} Log.e(TAG, "cmd", e); }
        finish(out, id, cmd);
    }

    void finish(JSONObject out, String id, String cmd) {
        try (FileOutputStream f = new FileOutputStream(new File(getFilesDir(), "res_" + id + ".json"))) { f.write(out.toString().getBytes()); }
        catch (Exception e) { Log.e(TAG, "write", e); }
        Log.i(TAG, "DONE " + id + " " + cmd);
    }

    void observeHistorical(JSONObject out) throws Exception {
        JSONObject facts = new JSONObject(); long now = System.currentTimeMillis();
        for (String[] f : FACTS) {
            Res r = read(f[0]); JSONObject fo = new JSONObject();
            fo.put("val", r.val); JSONArray ids = new JSONArray(); for (Long x : r.ids) ids.put(x); fo.put("ids", ids);
            fo.put("t_obs", now); fo.put("epoch", epoch);
            facts.put(f[0], fo);
        }
        JSONObject wms = new JSONObject();
        for (String s : SOURCES) {
            if (s.equals("contacts")) {
                for (String r : new String[]{"VER", "TS"}) { contactsRule = r; String w = watermark(s); if (w != null) wms.put(wmKey(s, r), w); }
                contactsRule = null;
            } else { String w = watermark(s); if (w != null) wms.put(s, w); }
        }
        mem.put("ver_map", verMap());
        mem.put("facts", facts); mem.put("wm", wms); mem.put("t_obs", now); mem.put("epoch_obs", epoch);
        mem.put("boot_wall_obs", now - SystemClock.elapsedRealtime());
        mem.put("boot_count_obs", Settings.Global.getInt(cr, "boot_count", -1));
        mem.put("obs_observers", observersActive);
        mem.put("ev_dirty", new JSONObject()); mem.put("te_dirty", new JSONObject()); mem.put("events", new JSONArray());
        // epoch continuity: an epoch is "unbroken since observation" iff it equals epoch_obs and observers are active
        out.put("wm", wms); out.put("facts", facts);
    }

    void observe(JSONObject out) throws Exception {
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

    String derivedVal(Map<String, String> vals, String[] d) { StringBuilder sb = new StringBuilder(); for (int i = 1; i < d.length; i++) sb.append(vals.get(d[i])).append("#"); return sb.toString(); }

    /** LeaseMem validation for a set of sources; returns fact -> FRESH | CHANGED | UNKNOWN and fills cost. */
    Map<String, String> lmValidateHistorical(Set<String> srcs, boolean strict, JSONObject cost) throws Exception {
        Map<String, String> st = new HashMap<>();
        JSONObject facts = mem.getJSONObject("facts"); JSONObject wms = mem.optJSONObject("wm");
        boolean unbroken = epoch.equals(mem.optString("epoch_obs")) && observersActive && mem.optBoolean("obs_observers");
        boolean clockJump = clockJumped();
        JSONObject evd = obj("ev_dirty");
        for (String s : srcs) {
            long t0 = System.nanoTime(); String reason;
            if (rule(s).equals("NONE")) {
                boolean fresh = !strict && unbroken && !evd.optBoolean(s);
                for (String[] f : FACTS) if (f[1].equals(s)) st.put(f[0], fresh ? "FRESH" : "UNKNOWN");
                reason = fresh ? "epoch" : "unknown";
            } else {
                String w0 = wms == null ? null : wms.optString(wmKey(s, rule(s)), null);
                String w1 = watermark(s);
                Set<Long> sup = new HashSet<>();
                for (String[] f : FACTS) if (f[1].equals(s)) { JSONArray a = facts.getJSONObject(f[0]).optJSONArray("ids"); for (int i = 0; a != null && i < a.length(); i++) sup.add(a.getLong(i)); }
                Set<Long> miss = missing(s, sup);
                boolean bad = w1 == null || w1.contains("ERR") || (w0 != null && w0.contains("ERR"));
                // racy-timestamp guard: a coarse (1 s) mtime equal to the stored one cannot exclude a change made in the
                // same tick as the observation; such evidence is treated as UNKNOWN
                boolean racy = false;
                if (rule(s).equals("MTIME") && w0 != null) { long m0 = Long.parseLong(w0.split("\\|")[0]); racy = mem.optLong("t_obs") - m0 < MTIME_GRAN_MS; }
                boolean tsRule = rule(s).equals("TS") || rule(s).equals("LASTMOD");
                if (tsRule && clockJump) {
                    for (String[] f : FACTS) if (f[1].equals(s)) st.put(f[0], "UNKNOWN");
                    reason = "clock";
                } else if (racy && w0.equals(w1)) {
                    for (String[] f : FACTS) if (f[1].equals(s)) st.put(f[0], "UNKNOWN");
                    reason = "racy";
                } else if (!bad && w0 != null && w0.equals(w1) && miss.isEmpty()) {
                    for (String[] f : FACTS) if (f[1].equals(s)) st.put(f[0], "FRESH");
                    reason = "wm_equal";
                } else {
                    Set<Long> ch = (w0 == null || bad) ? null : delta(s, w0);
                    if (ch == null) { for (String[] f : FACTS) if (f[1].equals(s)) st.put(f[0], "CHANGED"); reason = "wm_reset"; }
                    else {
                        ch.addAll(miss);
                        for (String[] f : FACTS) if (f[1].equals(s)) {
                            boolean hit = f[2].equals("1") ? !ch.isEmpty() : false;
                            JSONArray a = facts.getJSONObject(f[0]).optJSONArray("ids");
                            for (int i = 0; a != null && i < a.length(); i++) if (ch.contains(a.getLong(i))) hit = true;
                            // a keyed fact whose key now matches a new row (e.g. a re-created contact) is caught via the changed set too:
                            if (!hit && !f[2].equals("1") && !ch.isEmpty()) { Res r = read(f[0]); for (Long x : r.ids) if (ch.contains(x)) hit = true; cost.put("probe_" + f[0], r.ns); }
                            st.put(f[0], hit ? "CHANGED" : "FRESH");
                        }
                        reason = "delta:" + ch.size();
                    }
                }
            }
            JSONObject c = new JSONObject(); c.put("ns", System.nanoTime() - t0); c.put("reason", reason); cost.put(s, c);
        }
        return st;
    }

    /** Wall-clock timestamp watermarks assume a monotone clock. Within one boot, a change of the wall-clock offset
     *  against elapsedRealtime reveals a clock set since observation; across boots, only a clock that is
     *  currently behind the observation time is detectable. A transient set-back that was undone is NOT detected. */
    boolean clockJumped() {
        long now = System.currentTimeMillis();
        int bc = Settings.Global.getInt(cr, "boot_count", -1);
        if (!mem.has("boot_wall_obs")) return false;
        if (bc == mem.optInt("boot_count_obs", -2)) return Math.abs((now - SystemClock.elapsedRealtime()) - mem.optLong("boot_wall_obs")) > 2000;
        return now < mem.optLong("t_obs");
    }

    void decide(JSONObject out) throws Exception {
        long tdec = System.currentTimeMillis();
        JSONObject facts = mem.getJSONObject("facts");
        JSONObject evd = obj("ev_dirty"), ted = obj("te_dirty");
        // 1) policy decisions from memory + evidence only
        JSONObject lmCost = new JSONObject(), lmsCost = new JSONObject();
        Set<String> all = new HashSet<>(Arrays.asList(SOURCES));
        Map<String, String> lm = lmValidate(all, true, lmCost);    // LeaseMem: unsupported sources are UNKNOWN
        JSONObject lmtsCost = new JSONObject();
        contactsRule = "TS"; Map<String, String> lmts = lmValidate(Collections.singleton("contacts"), true, lmtsCost); contactsRule = null;
        boolean broken = !(epoch.equals(mem.optString("epoch_obs")) && observersActive && mem.optBoolean("obs_observers"));
        Map<String, String> lms = lmValidate(all, false, lmsCost); // ablation "lme": trust an unbroken observer epoch
        // StampCheck as in the emulator v3 data (historical watermark validation, cost per source with ns), recorded next
        // to the strict EvCheck verdicts above so that one trial carries both (physical runs, 2026-11-19)
        JSONObject lmHistCost = new JSONObject(), lmtsHistCost = new JSONObject();
        Map<String, String> lmHist = lmValidateHistorical(all, true, lmHistCost);
        contactsRule = "TS"; Map<String, String> lmtsHist = lmValidateHistorical(Collections.singleton("contacts"), true, lmtsHistCost); contactsRule = null;
        // 2) ground truth / refresh values (timed; this is also each policy's refresh cost)
        JSONObject res = new JSONObject(); Map<String, String> truth = new HashMap<>(), memv = new HashMap<>();
        for (String[] f : FACTS) {
            Res r = read(f[0]); JSONObject fo = facts.getJSONObject(f[0]);
            truth.put(f[0], r.val); memv.put(f[0], fo.optString("val"));
            JSONObject o = new JSONObject();
            o.put("mem", fo.optString("val")); o.put("truth", r.val); o.put("refresh_ns", r.ns); o.put("src", f[1]);
            o.put("ev", evd.optBoolean(f[1]) ? "REFRESH" : "FRESH");
            o.put("te", ted.optBoolean(f[0]) ? "REFRESH" : "FRESH");
            o.put("lm", lm.get(f[0])); o.put("lme", lms.get(f[0]));
            o.put("lmts", f[1].equals("contacts") ? lmts.get(f[0]) : lm.get(f[0]));
            o.put("lm_hist", lmHist.get(f[0])); o.put("lmts_hist", f[1].equals("contacts") ? lmtsHist.get(f[0]) : lmHist.get(f[0]));
            o.put("evr", (broken || evd.optBoolean(f[1])) ? "REFRESH" : "FRESH");
            o.put("t_obs", fo.optLong("t_obs"));
            res.put(f[0], o);
        }
        for (String[] d : DERIVED) {
            JSONObject o = new JSONObject();
            o.put("mem", derivedVal(memv, d)); o.put("truth", derivedVal(truth, d)); o.put("src", "derived");
            boolean evR = false, lmR = false, lmU = false, lmsR = false, lmsU = false, hR = false, hU = false; long rns = 0;
            for (int i = 1; i < d.length; i++) {
                JSONObject s = res.getJSONObject(d[i]);
                evR |= s.getString("ev").equals("REFRESH"); rns += s.getLong("refresh_ns");
                lmR |= s.getString("lm").equals("CHANGED"); lmU |= s.getString("lm").equals("UNKNOWN");
                lmsR |= s.getString("lme").equals("CHANGED"); lmsU |= s.getString("lme").equals("UNKNOWN");
                hR |= s.getString("lm_hist").equals("CHANGED"); hU |= s.getString("lm_hist").equals("UNKNOWN");
            }
            o.put("lm_hist", hR ? "CHANGED" : hU ? "UNKNOWN" : "FRESH");
            o.put("ev", evR ? "REFRESH" : "FRESH"); o.put("te", ted.optBoolean(d[0]) ? "REFRESH" : "FRESH");
            o.put("evr", (broken || evR) ? "REFRESH" : "FRESH");
            boolean tsR = false, tsU = false;
            for (int i = 1; i < d.length; i++) { String v = res.getJSONObject(d[i]).getString("lmts"); tsR |= v.equals("CHANGED"); tsU |= v.equals("UNKNOWN"); }
            o.put("lmts", tsR ? "CHANGED" : tsU ? "UNKNOWN" : "FRESH");
            o.put("lm", lmR ? "CHANGED" : lmU ? "UNKNOWN" : "FRESH"); o.put("lme", lmsR ? "CHANGED" : lmsU ? "UNKNOWN" : "FRESH");
            o.put("refresh_ns", rns); o.put("deps", new JSONArray(Arrays.asList(d).subList(1, d.length)));
            res.put(d[0], o);
        }
        out.put("t_dec", tdec); out.put("t_obs", mem.optLong("t_obs")); out.put("epoch_obs", mem.optString("epoch_obs"));
        out.put("unbroken", epoch.equals(mem.optString("epoch_obs")) && observersActive);
        out.put("clock_jump", clockJumped());
        out.put("facts", res); out.put("lm_cost", lmCost); out.put("lme_cost", lmsCost); out.put("lmts_cost", lmtsCost); out.put("broken", broken);
        out.put("lm_hist_cost", lmHistCost); out.put("lmts_hist_cost", lmtsHistCost);
        out.put("fg", FgService.running);
        out.put("events", mem.optJSONArray("events")); out.put("last_start", mem.opt("last_start"));
        out.put("wm_obs", mem.opt("wm"));
        JSONObject wnow = new JSONObject();
        for (String s : SOURCES) {
            if (s.equals("contacts")) { for (String r : new String[]{"VER", "TS"}) { contactsRule = r; String w = watermark(s); if (w != null) wnow.put(wmKey(s, r), w); } contactsRule = null; }
            else { String w = watermark(s); if (w != null) wnow.put(s, w); }
        }
        out.put("wm_now", wnow);
    }

    /** Candidate durable evidence for the coverage measurement (not used by any policy). */
    JSONObject probe() throws Exception {
        JSONObject p = new JSONObject();
        Uri C = ContactsContract.Contacts.CONTENT_URI, RC = ContactsContract.RawContacts.CONTENT_URI, DC = ContactsContract.DeletedContacts.CONTENT_URI;
        p.put("contacts.max_last_updated", top(C, "contact_last_updated_timestamp"));
        p.put("contacts.max_deleted_ts", top(DC, "contact_deleted_timestamp"));
        p.put("contacts.count", String.valueOf(q(C, new String[]{"_id"}, null, null, null).size()));
        p.put("contacts.max_raw_version", top(RC, "version"));
        long sv = 0; for (String[] x : q(RC, new String[]{"version"}, null, null, null)) sv += Long.parseLong(x[0]); p.put("contacts.sum_raw_version", String.valueOf(sv));
        p.put("contacts.max_id", top(C, "_id"));
        if (!EXCLUDED.contains("sms")) {
        Uri S = Uri.parse("content://sms");
        p.put("sms.max_id", one(S, "MAX(_id)", null)); p.put("sms.max_date", one(S, "MAX(date)", null));
        p.put("sms.count", one(S, "COUNT(*)", null)); p.put("sms.sum_read", one(S, "SUM(read)", null)); }
        if (!EXCLUDED.contains("calllog")) {
        Uri L = CallLog.Calls.CONTENT_URI;
        p.put("calllog.max_id", one(L, "MAX(_id)", null)); p.put("calllog.max_last_modified", one(L, "MAX(last_modified)", null));
        p.put("calllog.count", one(L, "COUNT(*)", null)); p.put("calllog.max_date", one(L, "MAX(date)", null)); }
        Uri F = MediaStore.Files.getContentUri(VOL);
        p.put("media.version", MediaStore.getVersion(this, VOL)); p.put("media.generation", String.valueOf(MediaStore.getGeneration(this, VOL)));
        p.put("media.max_gen_modified", one(F, "MAX(generation_modified)", null));
        p.put("media.count", one(F, "COUNT(*)", null)); p.put("media.max_id", one(F, "MAX(_id)", null));
        Uri E = CalendarContract.Events.CONTENT_URI;
        p.put("calendar.max_id", one(E, "MAX(_id)", null)); p.put("calendar.count", one(E, "COUNT(*)", null));
        p.put("calendar.sum_dirty", one(E, "SUM(dirty)", null)); p.put("calendar.count_deleted", one(E, "SUM(deleted)", null));
        p.put("files.dir_mtime", String.valueOf(new File(DOCDIR).lastModified()));
        long mx = 0; File[] fs = new File(DOCDIR).listFiles(); if (fs != null) for (File f : fs) mx = Math.max(mx, f.lastModified());
        p.put("files.max_file_mtime", String.valueOf(mx));
        p.put("files.media_count", one(F, "COUNT(*)", "relative_path='Documents/lm/'"));
        p.put("files.media_max_gen", one(F, "MAX(generation_modified)", "relative_path='Documents/lm/'"));
        // values of tracked facts, so the coverage run can tell "fact changed" from "candidate changed"
        JSONObject fv = new JSONObject(); for (String[] f : FACTS) fv.put(f[0], read(f[0]).val); p.put("facts", fv);
        JSONArray evs = mem.optJSONArray("events"); p.put("n_events", evs == null ? 0 : evs.length());
        return p;
    }

    // ---------------- action-boundary experiment (v3) ----------------
    /** ACT: validate at receipt (check1); at absolute device time `at` optionally re-validate (check2, mode bnd), then
     *  perform an external effect carrying the value used: an outgoing call-log row (effect "calllog", the emulator
     *  default) or, where the call log cannot be written (AWS Device Farm), a Data row of the separate raw contact
     *  "P06 Effect Log" (effect "contacts"). That raw contact has aggregation disabled and a custom MIME type, so it never
     *  joins Dana's contact and never changes Dana's VERSION; it is created at receipt, so the timed effect is one insert
     *  in both stores. Timestamps of every step are recorded so a host can place injected changes relative to the
     *  boundary check and the effect. */
    static final String EFFECT_MIME = "vnd.android.cursor.item/vnd.org.leasemem.effect", EFFECT_SOURCE_ID = "p06-effect-log";

    long effectRawContact() throws Exception {
        List<String[]> r = q(ContactsContract.RawContacts.CONTENT_URI, new String[]{"_id"},
                ContactsContract.RawContacts.SOURCE_ID + "=? AND " + ContactsContract.RawContacts.DELETED + "=0", new String[]{EFFECT_SOURCE_ID}, "_id");
        if (!r.isEmpty()) return Long.parseLong(r.get(0)[0]);
        android.content.ContentValues v = new android.content.ContentValues();
        v.putNull(ContactsContract.RawContacts.ACCOUNT_TYPE); v.putNull(ContactsContract.RawContacts.ACCOUNT_NAME);
        v.put(ContactsContract.RawContacts.SOURCE_ID, EFFECT_SOURCE_ID);
        v.put(ContactsContract.RawContacts.AGGREGATION_MODE, ContactsContract.RawContacts.AGGREGATION_MODE_DISABLED);
        long raw = android.content.ContentUris.parseId(cr.insert(ContactsContract.RawContacts.CONTENT_URI, v));
        android.content.ContentValues n = new android.content.ContentValues();
        n.put(ContactsContract.Data.RAW_CONTACT_ID, raw); n.put(ContactsContract.Data.MIMETYPE, ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE);
        n.put(ContactsContract.CommonDataKinds.StructuredName.DISPLAY_NAME, "P06 Effect Log");
        cr.insert(ContactsContract.Data.CONTENT_URI, n);
        return raw;
    }

    void act(Intent it, JSONObject out, String id) throws Exception {
        final String store = it.getStringExtra("effect") == null ? "calllog" : it.getStringExtra("effect");
        if (store.equals("calllog") && EXCLUDED.contains("calllog")) throw new IllegalStateException("ACT writes its effect to the call log, excluded on this device");
        if (!store.equals("calllog") && !store.equals("contacts")) throw new IllegalArgumentException("effect store " + store);
        final long effRaw = store.equals("contacts") ? effectRawContact() : -1;
        out.put("effect_store", store); out.put("effect_raw_contact", effRaw);
        final String fid = it.getStringExtra("fact"); final String mode = it.getStringExtra("mode");
        // validator "hist": StampCheck as in the emulator E3 v2 data; default "strict": EvCheck (Revision.validate)
        final boolean hist = "hist".equals(it.getStringExtra("validator"));
        out.put("validator", hist ? "hist" : "strict");
        final long at = it.getLongExtra("at", System.currentTimeMillis() + it.getLongExtra("delay", 3000));
        final String src = srcOf(fid);
        JSONObject c1 = new JSONObject();
        Map<String, String> st = hist ? lmValidateHistorical(Collections.singleton(src), true, c1) : lmValidate(Collections.singleton(src), true, c1);
        String used = mem.getJSONObject("facts").getJSONObject(fid).optString("val");
        if (!"FRESH".equals(st.get(fid))) used = read(fid).val;
        final String used1 = used;
        out.put("check1", System.currentTimeMillis()); out.put("st1", st.get(fid)); out.put("c1", c1);
        out.put("fact", fid); out.put("mode", mode); out.put("at", at);
        main.postDelayed(() -> {
            try {
                String u = used1;
                long tc0 = System.currentTimeMillis();
                if (mode.equals("bnd")) {
                    JSONObject c2 = new JSONObject();
                    Map<String, String> st2 = hist ? lmValidateHistorical(Collections.singleton(src), true, c2) : lmValidate(Collections.singleton(src), true, c2);
                    if (!"FRESH".equals(st2.get(fid))) u = read(fid).val;
                    out.put("st2", st2.get(fid)); out.put("c2", c2);
                }
                long tc1 = System.currentTimeMillis();
                // external effect: a record of whom the agent contacted, with the number it used
                String num = u.isEmpty() ? "none" : u.split(",")[0];
                android.content.ContentValues v = new android.content.ContentValues();
                Uri target;
                if (store.equals("contacts")) {   // a Data row of "P06 Effect Log": DATA1 number, DATA2 command id, DATA3 wall ms
                    v.put(ContactsContract.Data.RAW_CONTACT_ID, effRaw); v.put(ContactsContract.Data.MIMETYPE, EFFECT_MIME);
                    v.put(ContactsContract.Data.DATA1, num); v.put(ContactsContract.Data.DATA2, id); v.put(ContactsContract.Data.DATA3, String.valueOf(System.currentTimeMillis()));
                    target = ContactsContract.Data.CONTENT_URI;
                } else {
                    v.put(CallLog.Calls.NUMBER, num); v.put(CallLog.Calls.TYPE, CallLog.Calls.OUTGOING_TYPE);
                    v.put(CallLog.Calls.DATE, System.currentTimeMillis()); v.put(CallLog.Calls.DURATION, 0);
                    target = CallLog.Calls.CONTENT_URI;
                }
                long te0 = System.currentTimeMillis();
                Uri ef = null; try { ef = cr.insert(target, v); } catch (Exception e) { out.put("effect_err", e.toString()); }
                long te1 = System.currentTimeMillis();
                Res truth = read(fid);
                out.put("check2_start", tc0); out.put("check2_end", tc1); out.put("effect_start", te0); out.put("effect_end", te1);
                out.put("t_act", te0); out.put("effect_uri", String.valueOf(ef));
                out.put("used", u); out.put("truth_after_effect", truth.val); out.put("truth_read_ns", truth.ns);
                out.put("stale", !u.equals(truth.val));
            } catch (Exception e) { try { out.put("error", e.toString()); } catch (Exception ignored) {} }
            finish(out, id, "ACT");
        }, Math.max(0, at - System.currentTimeMillis()));
    }

    /** Re-anchor a single fact (used by ACT trials to start from a fresh memory). */

    // ---------------- persistence ----------------
    JSONObject load() {
        try { File f = new File(getFilesDir(), "mem.json"); if (!f.exists()) return new JSONObject();
            byte[] b = new byte[(int) f.length()]; try (FileInputStream in = new FileInputStream(f)) { int o = 0; while (o < b.length) { int n = in.read(b, o, b.length - o); if (n < 0) break; o += n; } }
            return new JSONObject(new String(b)); } catch (Exception e) { Log.e(TAG, "load", e); return new JSONObject(); }
    }

    void save() {
        try { File tmp = new File(getFilesDir(), "mem.json.tmp");
            try (FileOutputStream f = new FileOutputStream(tmp)) { f.write(mem.toString().getBytes()); f.getFD().sync(); }
            tmp.renameTo(new File(getFilesDir(), "mem.json")); } catch (Exception e) { Log.e(TAG, "save", e); }
    }
}

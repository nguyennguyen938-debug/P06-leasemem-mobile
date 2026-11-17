#!/usr/bin/env python3
"""E13: a host agent that keeps its memory on the host and reads the phone over adb (real emulator).

Such an agent has no ContentObserver, so every gap is a lost-notification gap for it: it must re-read or validate.
Per decision we time, host-side, the adb round trips each policy needs:
  global   : re-read all 16 base facts (one `adb shell` per fact). For base facts this is also what input
             memoization does (the facts are their own inputs), and what restart-aware refresh does.
  evcheck  : read one watermark per supported source (Contacts RawContacts VERSION map, call-log
             (_id, last_modified), MediaStore images (_id, generation_modified), file mtimes); the id lists double
             as the support check. Re-read the facts of every source whose watermark moved, and always re-read the
             7 facts of evidence-less sources (SMS, calendar, Settings).
Half of the decisions follow one mutation of a random source by another app, half follow none.
Ground truth = the global re-read; a policy misses if a fact changed and it did not re-read it.
Usage: e13_host.py SERIAL N SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, N, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
DOC = "/storage/emulated/0/Documents/lm"
PH = "vnd.android.cursor.item/phone_v2"
Q = {
    "c.dana": ("contacts", "content query --uri content://com.android.contacts/data --projection contact_id:data1 --where \"mimetype='%s' AND display_name='LM Dana'\"" % PH),
    "c.omar": ("contacts", "content query --uri content://com.android.contacts/data --projection contact_id:data1 --where \"mimetype='%s' AND display_name='LM Omar'\"" % PH),
    "c.set": ("contacts", "content query --uri content://com.android.contacts/contacts --projection _id:display_name --where \"display_name LIKE 'LM %'\""),
    "s.latest": ("sms", "content query --uri content://sms --projection _id:body --where \"address='+15550001'\" --sort \"date DESC, _id DESC\""),
    "s.unread": ("sms", "content query --uri content://sms --projection _id --where \"address LIKE '+1555%' AND read=0\""),
    "s.tracked": ("sms", "content query --uri content://sms --projection _id:body --where \"body LIKE 'LMTRACK%'\" --sort _id"),
    "l.latest": ("calllog", "content query --uri content://call_log/calls --projection _id:number --where \"number LIKE '+1666%'\" --sort \"date DESC, _id DESC\""),
    "l.missed": ("calllog", "content query --uri content://call_log/calls --projection _id:type --where \"number LIKE '+1666%'\""),
    "m.latest": ("media", "content query --uri content://media/external_primary/images/media --projection _id:_display_name --where \"relative_path='Pictures/lm/'\" --sort \"date_added DESC, _id DESC\""),
    "m.tracked": ("media", "content query --uri content://media/external_primary/images/media --projection _id:_display_name --where \"relative_path='Pictures/lm/' AND _display_name LIKE 'track_%'\""),
    "k.standup": ("calendar", "content query --uri content://com.android.calendar/events --projection _id:title:dtstart --where \"title LIKE 'LM standup%' AND deleted=0\""),
    "k.set": ("calendar", "content query --uri content://com.android.calendar/events --projection _id:title --where \"title LIKE 'LM %' AND deleted=0\""),
    "g.mode": ("settings", "settings get global lm_mode"),
    "g.target": ("settings", "settings get global lm_target"),
    "f.todo": ("files", "sha1sum %s/todo.md 2>/dev/null || echo absent" % DOC),
    "f.list": ("files", "ls %s" % DOC),
}
WM = {
    "contacts": "content query --uri content://com.android.contacts/raw_contacts --projection _id:contact_id:version:deleted",
    "calllog": "content query --uri content://call_log/calls --projection _id:last_modified",
    "media": "content query --uri content://media/external_primary/images/media --projection _id:generation_modified",
    "files": "stat -c '%%n %%Y %%s' %s %s/*" % (DOC, DOC),
}
SUPPORTED = set(WM)


def timed(cmd):
    t0 = time.perf_counter(); o = d.sh(cmd); return o, (time.perf_counter() - t0) * 1000.0


def read_all():
    vals, ms = {}, {}
    for f, (_, c) in Q.items():
        vals[f], ms[f] = timed(c)
    return vals, ms


def watermarks():
    vals, ms = {}, {}
    for s, c in WM.items():
        vals[s], ms[s] = timed(c)
    return vals, ms


with open(out, "a") as fo:
    w.ensure_base(); time.sleep(1)
    for i in range(N):
        change = i % 2 == 1
        w.ensure_base(); time.sleep(2.2)    # file mtimes have 1 s resolution: keep observation >1 s after setup
        mem, _ = read_all()                 # observation (memory) ...
        wm0, _ = watermarks()               # ... and its watermarks
        m = None
        if change:
            src = rng.choice(["contacts", "sms", "calllog", "media", "calendar", "settings", "files"])
            kind = rng.choice(lmdrv.World.KINDS[src])
            m = w.mutate(src, kind); time.sleep(1.2)   # >1 s so that file mtimes can move
        # ---- decision: global re-read (also ground truth) ----
        t0 = time.perf_counter(); truth, ms_g = read_all(); t_global = (time.perf_counter() - t0) * 1000.0
        # ---- decision: evidence check ----
        t0 = time.perf_counter()
        wm1, ms_w = watermarks()
        moved = {s for s in SUPPORTED if wm1[s] != wm0[s]}
        reread = [f for f, (s, _) in Q.items() if s not in SUPPORTED or s in moved]
        ms_r = {}
        for f in reread:
            _, ms_r[f] = timed(Q[f][1])
        t_ev = (time.perf_counter() - t0) * 1000.0
        changed = [f for f in Q if truth[f] != mem[f]]
        rec = {"i": i, "seed": seed, "serial": serial, "change": change, "mut": m, "t_global_ms": round(t_global, 1),
               "t_evcheck_ms": round(t_ev, 1), "n_global": len(Q), "n_wm": len(WM), "n_reread": len(reread), "moved": sorted(moved),
               "changed": changed, "evcheck_miss": [f for f in changed if f not in reread],
               "ms_global": {k: round(v, 1) for k, v in ms_g.items()}, "ms_wm": {k: round(v, 1) for k, v in ms_w.items()},
               "wm_bytes": {k: len(v) for k, v in wm1.items()}}
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(i, change, m and m["src"], "global %.0f ms, evcheck %.0f ms (%d re-reads), changed %s miss %s" %
              (t_global, t_ev, len(reread), changed, rec["evcheck_miss"]), flush=True)

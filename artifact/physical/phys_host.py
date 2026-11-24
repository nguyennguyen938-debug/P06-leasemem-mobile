#!/usr/bin/env python3
"""G17 (F6), a rented or lab phone: a host agent that keeps its memory on the host and reads the phone over adb, one
`adb shell` per read, no batching. Port of driver/e13_host.py (emulator Table host, unbatched) to the phone rules:
provider reads through Dev.u() (`content query --user 0`), the files source read with the three read-only commands
that lmdrv.AWS_ONLY_OK allows on P06's own folder; facts of excluded sources (SMS and call log on Device Farm) are
left out, so n_global is 16 in lab mode and 11 on Device Farm.

Per decision, host-side wall time of the adb round trips each policy needs:
  global   re-read every base fact (also input memoization and restart-aware refresh for base facts);
  evcheck  read one watermark per supported source (Contacts RawContacts VERSION map, call-log (_id, last_modified),
           MediaStore (_id, generation_modified), file mtimes); re-read the facts of every source whose watermark
           moved, and always the facts of sources without evidence (SMS, Calendar, Settings).
Half of the decisions follow one mutation of a random source by another app, half none. Ground truth is the global
re-read; evcheck misses a fact that changed and was not re-read.
Usage: phys_host.py SERIAL N SEED OUT.jsonl
"""
import json, random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
import lmdrv

serial, N, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
if not d.aws:
    raise SystemExit("phys_host.py reads P06's folder in shared storage: AWS or lab mode only")
DOC = "/storage/emulated/0/Documents/lm"
PH = "vnd.android.cursor.item/phone_v2"
cq = lambda q: d.u("content query " + q)
Q = {
    "c.dana": ("contacts", cq("--uri content://com.android.contacts/data --projection contact_id:data1 --where \"mimetype='%s' AND display_name='LM Dana'\"" % PH)),
    "c.omar": ("contacts", cq("--uri content://com.android.contacts/data --projection contact_id:data1 --where \"mimetype='%s' AND display_name='LM Omar'\"" % PH)),
    "c.set": ("contacts", cq("--uri content://com.android.contacts/contacts --projection _id:display_name --where \"display_name LIKE 'LM %'\"")),
    "s.latest": ("sms", cq("--uri content://sms --projection _id:body --where \"address='+15550001'\" --sort \"date DESC, _id DESC\"")),
    "s.unread": ("sms", cq("--uri content://sms --projection _id --where \"address LIKE '+1555%' AND read=0\"")),
    "s.tracked": ("sms", cq("--uri content://sms --projection _id:body --where \"body LIKE 'LMTRACK%'\" --sort _id")),
    "l.latest": ("calllog", cq("--uri content://call_log/calls --projection _id:number --where \"number LIKE '+1666%'\" --sort \"date DESC, _id DESC\"")),
    "l.missed": ("calllog", cq("--uri content://call_log/calls --projection _id:type --where \"number LIKE '+1666%'\"")),
    "m.latest": ("media", cq("--uri content://media/external_primary/images/media --projection _id:_display_name --where \"relative_path='Pictures/lm/'\" --sort \"date_added DESC, _id DESC\"")),
    "m.tracked": ("media", cq("--uri content://media/external_primary/images/media --projection _id:_display_name --where \"relative_path='Pictures/lm/' AND _display_name LIKE 'track_%'\"")),
    "k.standup": ("calendar", cq("--uri content://com.android.calendar/events --projection _id:title:dtstart --where \"title LIKE 'LM standup%' AND deleted=0\"")),
    "k.set": ("calendar", cq("--uri content://com.android.calendar/events --projection _id:title --where \"title LIKE 'LM %' AND deleted=0\"")),
    "g.mode": ("settings", "settings get global lm_mode"),
    "g.target": ("settings", "settings get global lm_target"),
    "f.todo": ("files", "sha1sum %s/todo.md 2>/dev/null || echo absent" % DOC),
    "f.list": ("files", "ls %s" % DOC),
}
WM = {
    "contacts": cq("--uri content://com.android.contacts/raw_contacts --projection _id:contact_id:version:deleted"),
    "calllog": cq("--uri content://call_log/calls --projection _id:last_modified"),
    "media": cq("--uri content://media/external_primary/images/media --projection _id:generation_modified"),
    "files": "stat -c '%%n %%Y %%s' %s %s/*" % (DOC, DOC),
}
Q = {f: v for f, v in Q.items() if v[0] not in d.excluded}
WM = {s: c for s, c in WM.items() if s not in d.excluded}
SUPPORTED = set(WM)
SRCS = sorted({s for s, _ in Q.values()})


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


with lmdrv.open_new(out) as fo:
    w.ensure_base(); time.sleep(1)
    for i in range(N):
        rec = {**d.meta(), "serial": serial, "exp": "phys_host", "i": i, "seed": seed, "change": i % 2 == 1}
        try:
            w.ensure_base(); time.sleep(2.2)    # file mtimes have 1 s resolution: observe >1 s after setup
            mem, _ = read_all(); wm0, _ = watermarks()
            m = None
            if rec["change"]:
                src = rng.choice(SRCS); m = w.mutate(src, rng.choice(w.kinds[src])); time.sleep(1.2)
            t0 = time.perf_counter(); truth, ms_g = read_all(); t_global = (time.perf_counter() - t0) * 1000.0
            t0 = time.perf_counter(); wm1, ms_w = watermarks()
            moved = {s for s in SUPPORTED if wm1[s] != wm0[s]}
            reread = [f for f, (s, _) in Q.items() if s not in SUPPORTED or s in moved]
            for f in reread:
                timed(Q[f][1])
            t_ev = (time.perf_counter() - t0) * 1000.0
            changed = [f for f in Q if truth[f] != mem[f]]
            rec.update(mut=m, t_global_ms=round(t_global, 1), t_evcheck_ms=round(t_ev, 1), n_global=len(Q), n_wm=len(WM),
                       n_reread=len(reread), moved=sorted(moved), changed=changed, evcheck_miss=[f for f in changed if f not in reread],
                       ms_global={k: round(v, 1) for k, v in ms_g.items()}, ms_wm={k: round(v, 1) for k, v in ms_w.items()},
                       wm_bytes={k: len(v) for k, v in wm1.items()})
        except Exception as e:
            rec["error"] = repr(e)
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(i, rec["change"], rec.get("t_global_ms"), rec.get("t_evcheck_ms"), rec.get("evcheck_miss"), rec.get("error", "")[:100], flush=True)

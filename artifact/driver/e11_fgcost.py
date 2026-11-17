#!/usr/bin/env python3
"""E11: what does the foreground-service alternative cost? (real emulator; energy is the platform's model estimate)

Alternates windows of W seconds with the client as a cached background app (bg) and as a foreground service (fg).
During each window another app mutates a source every MUT_EVERY s, so the client's observers do their normal work.
At the end of each window we record the client's CPU time (utime+stime from /proc/<pid>/stat), its PSS
(dumpsys meminfo), and BatteryStats' estimated power for the client's UID ("Estimated power use", model-based on an
emulator). BatteryStats is reset and the battery set to unplugged at the start of each window.
Usage: e11_fgcost.py SERIAL REPS WINDOW_S SEED OUT.jsonl
"""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, reps, W, seed, out = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
MUT_EVERY = 20.0
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
PKG = lmdrv.CPKG


def cpu_ticks(p):
    if not p:
        return None
    f = d.sh("cat /proc/%s/stat" % p).split()
    return int(f[13]) + int(f[14]) if len(f) > 15 else None


def pss_kb():
    m = re.search(r"TOTAL PSS:\s+(\d+)", d.sh("dumpsys meminfo %s" % PKG)) or re.search(r"TOTAL\s+(\d+)", d.sh("dumpsys meminfo %s" % PKG))
    return int(m.group(1)) if m else None


def uid_power():
    uid = None
    for _ in range(5):                       # robust UID lookup (dumpsys package output was empty once under load)
        m = re.search(r"uid:(\d+)", d.sh("pm list packages -U %s" % PKG)) or re.search(r"userId=(\d+)", d.sh("dumpsys package %s" % PKG))
        if m:
            uid = m.group(1); break
        time.sleep(2)
    if uid is None:
        return None, None
    txt = d.sh("dumpsys batterystats --charged %s" % PKG) + d.sh("dumpsys batterystats")
    pat = re.compile(r"(?:UID|Uid) u0a%d:\s*([0-9.eE+-]+)" % (int(uid) - 10000))
    m = pat.search(txt)
    return float(m.group(1)) if m else None, uid


with open(out, "a") as f:
    w.ensure_base()
    for r in range(reps):
        for mode in (["bg", "fg"] if r % 2 == 0 else ["fg", "bg"]):
            d.sh("am stopservice -n %s/.FgService" % PKG)
            if not d.pid():
                d.launch()
            if mode == "fg":
                d.sh("am start-foreground-service -n %s/.FgService" % PKG); time.sleep(1)
            d.home(); time.sleep(3)
            d.sh("dumpsys battery unplug"); d.sh("dumpsys batterystats --reset")
            p = d.pid(); c0 = cpu_ticks(p); t0 = time.time(); nm = 0
            while time.time() - t0 < W:
                time.sleep(MUT_EVERY)
                src = rng.choice(["contacts", "sms", "calllog", "media", "calendar", "settings"])
                w.mutate(src, {"contacts": "update", "sms": "insert", "calllog": "insert", "media": "insert", "calendar": "update", "settings": "update"}[src])
                nm += 1
            p1 = d.pid(); c1 = cpu_ticks(p1)
            pw, uid = uid_power()
            rec = {"rep": r, "mode": mode, "window_s": round(time.time() - t0, 1), "mutations": nm, "pid_same": p == p1,
                   "cpu_ticks": (c1 - c0) if (c0 is not None and c1 is not None and p == p1) else None, "pss_kb": pss_kb(),
                   "est_power_mah": pw, "uid": uid, "oom_score_adj": d.sh("cat /proc/%s/oom_score_adj" % p1).strip() if p1 else None}
            d.sh("dumpsys battery reset")
            f.write(json.dumps(rec) + "\n"); f.flush()
            print(rec, flush=True)
    d.sh("am stopservice -n %s/.FgService" % PKG)

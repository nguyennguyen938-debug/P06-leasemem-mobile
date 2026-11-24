#!/usr/bin/env python3
"""G16 (F6), a rented or lab phone: what does keeping the memory in a foreground service cost? Port of
driver/e11_fgcost.py (emulator Table fgcost) to the phone rules.

Alternates windows of W s with the client as a cached background app (bg) and as a foreground service (fg); during
each window another app mutates a source every 20 s. At the end of each window: the client's CPU ticks
(utime+stime of /proc/<pid>/stat), its PSS (dumpsys meminfo) and BatteryStats' estimated charge for its UID
(`dumpsys batterystats --charged org.leasemem.client`). BatteryStats is reset (`dumpsys batterystats --reset`, AWS or
lab mode only) and the battery set to unplugged (`dumpsys battery unplug`) at the start of each window and reset after
it. The phones charge throughout: the estimate is BatteryStats' power-profile model, not a battery measurement.
Usage: phys_fgcost.py SERIAL REPS WINDOW_S SEED OUT.jsonl
"""
import json, random, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
import lmdrv

serial, reps, W, seed, out = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
MUT_EVERY = 20.0
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
if not d.aws:
    raise SystemExit("phys_fgcost.py resets BatteryStats: AWS or lab mode only")
P = lmdrv.CPKG
SRCS = [s for s in ("contacts", "sms", "calllog", "media", "calendar", "settings") if s in w.kinds]
KIND = {"contacts": "update", "sms": "insert", "calllog": "insert", "media": "insert", "calendar": "update", "settings": "update"}


def cpu_ticks(p):
    f = d.sh("cat /proc/%s/stat" % p).split() if p else []
    return int(f[13]) + int(f[14]) if len(f) > 15 else None


def pss_kb():
    t = d.sh("dumpsys meminfo %s" % P)
    m = re.search(r"TOTAL PSS:\s+(\d+)", t) or re.search(r"TOTAL\s+(\d+)", t)
    return int(m.group(1)) if m else None


def uid():
    for _ in range(5):
        m = re.search(r"uid:(\d+)", d.sh(d.u("pm list packages -U %s" % P))) or re.search(r"userId=(\d+)", d.sh(lmdrv.DUMP_PKG % P, timeout=90))
        if m:
            return int(m.group(1))
        time.sleep(2)
    return None


def uid_power(u):
    txt = d.sh("dumpsys batterystats --charged %s" % P)
    m = re.search(r"(?:UID|Uid) u0a%d:\s*([0-9.eE+-]+)" % (u - 10000), txt) if u else None
    return (float(m.group(1)) if m else None), txt.count("\n")


with lmdrv.open_new(out) as f:
    w.ensure_base(); U = uid()
    for r in range(reps):
        for mode in (["bg", "fg"] if r % 2 == 0 else ["fg", "bg"]):
            rec = {**d.meta(), "serial": serial, "exp": "phys_fgcost", "rep": r, "mode": mode, "uid": U, "window_target_s": W}
            try:
                d.sh(d.u("am stopservice -n %s/.FgService" % P))
                if not d.pid():
                    d.launch()
                if mode == "fg":
                    d.sh(d.u("am start-foreground-service -n %s/.FgService" % P)); time.sleep(1)
                d.home(); time.sleep(3)
                d.sh("dumpsys battery unplug"); d.sh("dumpsys batterystats --reset")
                p = d.pid(); c0 = cpu_ticks(p); t0 = time.time(); nm = 0
                while time.time() - t0 < W:
                    time.sleep(MUT_EVERY)
                    src = rng.choice(SRCS); w.mutate(src, KIND[src]); nm += 1
                p1 = d.pid(); c1 = cpu_ticks(p1)
                pw, lines = uid_power(U)
                rec.update(window_s=round(time.time() - t0, 1), mutations=nm, pid_same=p == p1,
                           cpu_ticks=(c1 - c0) if (c0 is not None and c1 is not None and p == p1) else None, pss_kb=pss_kb(),
                           est_power_mah=pw, batterystats_lines=lines,
                           oom_score_adj=d.sh("cat /proc/%s/oom_score_adj" % p1).strip() if p1 else None)
            except Exception as e:
                rec["error"] = repr(e)
            finally:
                d.sh("dumpsys battery reset")
            f.write(json.dumps(rec) + "\n"); f.flush()
            print(r, mode, rec.get("cpu_ticks"), rec.get("est_power_mah"), rec.get("error", "")[:100], flush=True)
    d.sh(d.u("am stopservice -n %s/.FgService" % P))

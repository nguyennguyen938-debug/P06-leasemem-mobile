#!/usr/bin/env python3
"""G10b (F3 task 13, screen off), AWS mode only: does the Galaxy S25's own freezer (the process moved into the cgroup
v1 freezer group `/frozen` within 15 s of screen off, while ActivityManager's isFrozen stayed false; G10 run 24f2b7b9)
hold the client's change callbacks back, as Android's cached-apps freezer does?

Each trial: the client is restarted in the background as in B1 bg_unfrozen (debounce 600 s, so Android's own freezer
stays out), the screen goes off (`input keyevent KEYCODE_SLEEP`), the cgroup v1 freezer path is polled every second for
at most WAIT_S until it reads `/frozen`, then the mutator updates Contacts and MediaStore. The screen stays off for
HOLD_S more seconds while every 3 s a sample records the v1 path, isFrozen, curProcState and the /proc State and
context-switch lines (the client's memory file is not read while the screen is off). Then `KEYCODE_WAKEUP` (t_wake),
12 s for a background callback, and the client's memory file: a callback with t < t_wake arrived while the screen was
off, a later one only after the wake-up. The screen is turned on again in a finally block.
Usage: freeze_screenoff.py SERIAL OUT.jsonl [N=10] [HOLD_S=40] [WAIT_S=45]
"""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "revision"))
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
HOLD_S = float(sys.argv[4]) if len(sys.argv) > 4 else 40
WAIT_S = float(sys.argv[5]) if len(sys.argv) > 5 else 45
c, w = setup(serial, Path(out).parent); d = c.d
if not d.aws:
    raise SystemExit("freeze_screenoff.py turns the screen off: AWS mode only (a wiped rented phone)")
P = lmdrv.CPKG
SOURCES = ("contacts", "media")


def v1(pid):
    m = re.search(r"\d+:freezer:(\S+)", d.sh("cat /proc/%s/cgroup" % pid))
    return m.group(1) if m else None


def sample(pid, t0):
    blk = d.sh("dumpsys activity processes " + P); i = blk.find("*APP*"); blk = blk[i:i + 3500] if i >= 0 else blk[:500]
    g = lambda k: (re.search(k + r"=(\S+)", blk) or [None, None])[1]
    return {"t_s": round(time.monotonic() - t0, 1), "pid": d.pid(P), "v1": v1(pid), "isFrozen": g("isFrozen"),
            "curProcState": g("curProcState"), "frozen_v2": d.frozen(P),
            "status": d.sh('grep -E "^(State|voluntary_ctxt|nonvoluntary_ctxt)" /proc/%s/status' % pid).strip(),
            "wake": d.sh("dumpsys power | grep -m1 mWakefulness=").strip()}


d.sh("device_config set_sync_disabled_for_tests until_reboot")
d.sh("device_config put activity_manager_native_boot freeze_debounce_timeout 600000")
f = lmdrv.open_new(out)
try:
    for i in range(n):
        r = {**d.meta(), "serial": serial, "exp": "freeze_screenoff", "trial": i, "hold_s": HOLD_S}
        try:
            d.sh("input keyevent KEYCODE_WAKEUP"); d.home()
            d.sh(d.u("am force-stop " + P)); d.sh(d.u("am start -W -n %s/org.leasemem.client.Main" % P)); time.sleep(.4)
            w.ensure_base(); time.sleep(.5); d.home(); time.sleep(1.5)
            pid = r["pid"] = d.pid(P); t0 = time.monotonic()
            r["before"] = sample(pid, t0)
            d.sh("input keyevent KEYCODE_SLEEP"); r["t_sleep"] = d.now_ms()
            while v1(pid) != "/frozen" and time.monotonic() - t0 < WAIT_S:
                time.sleep(1)
            r["v1_at_mutation"] = v1(pid); r["s_to_frozen"] = round(time.monotonic() - t0, 1)
            r["mutations"] = {src: w.mutate(src, "update") for src in SOURCES}
            r["samples"] = []; t1 = time.monotonic()
            while time.monotonic() - t1 < HOLD_S:
                r["samples"].append(sample(pid, t0)); time.sleep(2)
            r["t_wake"] = d.now_ms(); d.sh("input keyevent KEYCODE_WAKEUP")
            r["after_wake"] = [sample(pid, t0)]; time.sleep(12); r["after_wake"].append(sample(pid, t0))
            ev = json.loads(d.cat(P, "files/mem.json")).get("events", [])
            for src in SOURCES:
                t_pre = r["mutations"][src]["t_pre"]
                mine = sorted(e["t"] for e in ev if e.get("src") == src and e["t"] >= t_pre)
                r[src] = {"t_pre": t_pre, "n_events": len(mine), "first_delay_ms": mine[0] - t_pre if mine else None,
                          "first_before_wake": (mine[0] < r["t_wake"]) if mine else None,
                          "first_after_wake_ms": (mine[0] - r["t_wake"]) if mine else None}
        except Exception as e:
            r["error"] = repr(e)
        f.write(json.dumps(r) + "\n"); f.flush()
        print(i, r.get("v1_at_mutation"), r.get("s_to_frozen"), {s: (r.get(s) or {}).get("first_before_wake") for s in SOURCES},
              r.get("error", "")[:100], flush=True)
finally:
    d.sh("input keyevent KEYCODE_WAKEUP"); d.home()
    f.write(json.dumps({**d.meta(), "serial": serial, "exp": "freeze_screenoff_restore", "wake": d.sh("dumpsys power | grep -m1 mWakefulness=").strip(),
                        "plugged": d.plugged()}) + "\n")
    f.close()
    d.sh("device_config put activity_manager_native_boot freeze_debounce_timeout 600000"); d.sh(d.u("am force-stop " + P))

#!/usr/bin/env python3
"""G10 (F3 task 13), AWS mode only: does a rented phone ever freeze a cached client when given longer, with the screen
off, or in battery saver? The Galaxy S25 never froze one within 26 s (B0 run 9f8a842d, B1FD run 8f3346a2).

The client is made cached as in the B0 probe (FGS stopped, app opened, HOME), the freezer debounce is 2 s, then four
phases are sampled: A cached, screen on (MIN minutes, a sample every 20 s); B screen off (`input keyevent
KEYCODE_SLEEP`); C battery saver (`dumpsys battery unplug`, then `cmd power set-mode 1`, falling back to `settings put
global low_power 1`); D battery saver and screen off (SIDE minutes each, a sample every 15 s). Every sample records the
cgroup v2 freeze file, every /proc/<pid>/cgroup line, ActivityManager's isFrozen, isPendingFreeze, isFreezeExempt,
curProcState and the /proc State line, so a vendor freezer that bypasses cgroup v2 still shows. Each command used to
change the phone is recorded with its output (an exp=freeze_long_cmd record), so a refused command shows. Battery
saver, the battery state and the screen are restored in a finally block and read back.
Usage: freeze_long.py SERIAL OUT.jsonl [MIN=10] [SIDE=3]
"""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "revision"))
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
MIN = float(sys.argv[3]) if len(sys.argv) > 3 else 10
SIDE = float(sys.argv[4]) if len(sys.argv) > 4 else 3
c, w = setup(serial, Path(out).parent); d = c.d
if not d.aws:
    raise SystemExit("freeze_long.py turns on battery saver: AWS mode only (a wiped rented phone)")
P = lmdrv.CPKG
f = lmdrv.open_new(out)


def emit(r):
    f.write(json.dumps({**d.meta(), "serial": serial, **r}) + "\n"); f.flush()


def run(label, cmd):
    """One phone-changing command, its output recorded (a refused or failing command shows here)."""
    try:
        o, err = d.sh(cmd, timeout=30).strip(), None
    except Exception as e:
        o, err = None, repr(e)
    emit({"exp": "freeze_long_cmd", "label": label, "cmd": cmd, "out": o, **({"error": err} if err else {})})
    return o


def field(blk, k):
    m = re.search(k + r"=(\S+)", blk)
    return m.group(1) if m else None


def sample(phase, t0):
    p = d.pid(P); s = {"exp": "freeze_long", "phase": phase, "t_s": round(time.monotonic() - t0, 1), "pid": p}
    if p:
        s["frozen"] = d.frozen(P); s["frozen_method"] = d.frozen_method
        blk = d.sh("dumpsys activity processes " + P); i = blk.find("*APP*"); blk = blk[i:i + 3500] if i >= 0 else blk[:500]
        for k in ("isFrozen", "isPendingFreeze", "isFreezeExempt", "curProcState", "cached", "empty"):
            s[k] = field(blk, k)
        s["cgroup"] = d.sh("cat /proc/%s/cgroup" % p).strip()
        s["state"] = d.sh("grep -m1 State /proc/%s/status" % p).strip()
    s["wake"] = d.sh("dumpsys power | grep -m1 mWakefulness=").strip()
    s["low_power"] = d.sh("settings get global low_power").strip()
    emit(s); print(phase, s["t_s"], s.get("frozen"), s.get("isFrozen"), s.get("curProcState"), flush=True)
    return s


def phase(name, minutes, every):
    t0 = time.monotonic(); froze = False
    while True:
        froze |= sample(name, t0).get("isFrozen") == "true"
        if time.monotonic() - t0 >= minutes * 60:
            return froze
        time.sleep(max(0, every - 1))


lp0 = d.sh("settings get global low_power").strip(); res = {}
try:
    run("settings", "dumpsys activity settings | grep -i -E 'freez'")
    run("sync_off", "device_config set_sync_disabled_for_tests until_reboot")
    run("debounce", "device_config put activity_manager_native_boot freeze_debounce_timeout 2000")
    run("debounce_get", "device_config get activity_manager_native_boot freeze_debounce_timeout")
    # cached as in b0_probe.bg_client: FGS stopped, app opened, HOME
    d.sh(d.u("am stopservice -n %s/.FgService" % P)); d.launch(); time.sleep(1); d.home(); time.sleep(2)
    res["A_cached"] = phase("A_cached", MIN, 20)
    run("screen_off", "input keyevent KEYCODE_SLEEP"); time.sleep(1)
    res["B_screen_off"] = phase("B_screen_off", SIDE, 15)
    run("screen_on", "input keyevent KEYCODE_WAKEUP"); d.home(); time.sleep(1)
    run("unplug", "dumpsys battery unplug")
    run("saver_on", "cmd power set-mode 1"); time.sleep(1)
    if run("saver_get", "settings get global low_power") != "1":
        run("saver_on_setting", "settings put global low_power 1"); time.sleep(1); run("saver_get2", "settings get global low_power")
    run("saver_power", "dumpsys power | grep -m4 -E 'LowPower|BatterySaver|mIsPowered'")
    res["C_saver"] = phase("C_saver", SIDE, 15)
    run("screen_off2", "input keyevent KEYCODE_SLEEP"); time.sleep(1)
    res["D_saver_screen_off"] = phase("D_saver_screen_off", SIDE, 15)
finally:
    run("screen_on2", "input keyevent KEYCODE_WAKEUP")
    run("saver_off", "cmd power set-mode 0")
    run("saver_restore", "settings delete global low_power" if lp0 in ("", "null") else "settings put global low_power %s" % lp0)
    run("battery_reset", "dumpsys battery reset")
    run("debounce_back", "device_config put activity_manager_native_boot freeze_debounce_timeout 600000")
    after = d.sh("settings get global low_power").strip()
    emit({"exp": "freeze_long_restore", "low_power_before": lp0, "low_power_after": after, "restored": after == lp0,
          "plugged_after": d.plugged()})
    d.home()
emit({"exp": "freeze_long_summary", "froze_by_phase": res, "minutes": MIN, "side_minutes": SIDE})
f.close()
print("froze by phase", res, flush=True)

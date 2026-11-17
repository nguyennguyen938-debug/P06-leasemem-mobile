#!/usr/bin/env python3
"""B12: overnight battery drain, screen off, client as a plain background app versus client holding a foreground
service (FGS). At most --max-hours (default 6) per night, counted from the moment the phone is unplugged.

Run over wireless debugging with the phone charged and still on the charger. The script prepares the client, then
waits (up to --wait-hours) until dumpsys battery reports no charger; that instant starts the 6-hour budget. It turns
the screen off and runs len(--order) blocks of equal length that together end --margin-min before the budget, so the
whole run stops before the 6-hour mark. Per block: set the arm (FGS on: start FgService; off: stop it), reset
BatteryStats, sample every --sample-min (charge counter, level, voltage, temperature, Doze state, client state), and at
the block end save the raw `dumpsys batterystats` text. Every sample and block summary is written and flushed at once,
so a run cut short keeps its finished blocks. Files: OUT_PREFIX-samples.jsonl and
OUT_PREFIX-block<k>-<arm>-batterystats.txt. A block ends early, marked incomplete, if a charger is reconnected or
the level drops below 15%.
Night 1: --order on,off,on,off; night 2: --order off,on,off,on.
Usage: b12_battery.py SERIAL OUT_PREFIX --order on,off,on,off [--max-hours 6] [--margin-min 10] [--sample-min 5]
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
import lmdrv

P = lmdrv.CPKG


def battery(d):
    t = d.sh("dumpsys battery", timeout=20, retries=1)
    g = lambda k: (lambda m: m and int(m.group(1)))(re.search(k + r": (-?\d+)", t))
    return {"plugged": bool(re.search(r"(AC|USB|Wireless|Dock) powered: true", t)), "level": g("level"),
            "charge_uAh": g("Charge counter"), "voltage_mV": g("voltage"), "temp_dC": g("temperature")}


def sample(d, kind, **kw):
    rec = {"kind": kind, "t": time.time(), **kw}
    try:
        rec.update(battery(d))
        rec["doze_deep"] = d.sh("dumpsys deviceidle get deep", timeout=20, retries=1).strip()
        rec["client_pid"] = d.pid() or None
        rec["fgs"] = "isForeground=true" in d.sh("dumpsys activity services %s/.FgService" % P, timeout=20, retries=1)
        rec["wakefulness"] = (lambda m: m and m.group(1))(re.search(r"mWakefulness=(\w+)", d.sh("dumpsys power | grep -m1 mWakefulness=", timeout=20, retries=1)))
    except Exception as e:
        rec["error"] = repr(e)[:300]
        if ":" in d.s:                                  # wireless serial: try to reconnect, keep going
            subprocess.run([lmdrv.ADB, "connect", d.s], capture_output=True, timeout=20)
    return rec


def still_plugged(d):
    try:
        return battery(d)["plugged"]
    except Exception:
        if ":" in d.s:
            subprocess.run([lmdrv.ADB, "connect", d.s], capture_output=True, timeout=20)
        return True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("serial"); ap.add_argument("out_prefix")
    ap.add_argument("--order", required=True); ap.add_argument("--max-hours", type=float, default=6.0)
    ap.add_argument("--margin-min", type=float, default=10.0); ap.add_argument("--sample-min", type=float, default=5.0)
    ap.add_argument("--wait-hours", type=float, default=12.0); a = ap.parse_args()
    order = a.order.split(","); assert set(order) <= {"on", "off"}, order
    d = lmdrv.Dev(a.serial); static = {k: v for k, v in d.meta().items() if k != "plugged"}
    f = lmdrv.open_new(a.out_prefix + "-samples.jsonl")
    emit = lambda r: (f.write(json.dumps({**static, **r}) + "\n"), f.flush())
    d.sh("am stopservice -n %s/.FgService" % P); d.launch(); time.sleep(1); d.home()
    emit({"kind": "start", "t": time.time(), "order": order, "max_hours": a.max_hours, "margin_min": a.margin_min,
          **battery(d), "device_config": d.sh("dumpsys activity settings | grep -i freeze").strip()})
    if ":" not in a.serial and "_adb-tls-connect" not in a.serial:
        print("WARNING: %s looks like a USB serial; unplugging will drop it. Use the wireless serial." % a.serial, flush=True)
    t_wait = time.time()
    while still_plugged(d):                        # the budget starts when the user unplugs the phone
        if time.time() - t_wait > a.wait_hours * 3600:
            emit({"kind": "abort", "t": time.time(), "reason": "never unplugged"}); return 1
        time.sleep(30)
    t_unplug = time.time(); deadline = t_unplug + a.max_hours * 3600 - a.margin_min * 60
    d.sh("input keyevent KEYCODE_SLEEP")
    block_s = (deadline - time.time()) / len(order)
    emit(sample(d, "unplugged", t_unplug=t_unplug, deadline=deadline, block_s=round(block_s, 1)))
    for k, arm in enumerate(order):
        if time.time() + 60 > deadline:
            break
        try:
            d.sh("am start-foreground-service -n %s/.FgService" % P if arm == "on" else "am stopservice -n %s/.FgService" % P, timeout=30)
            time.sleep(2); d.sh("dumpsys batterystats --reset", timeout=30); set_err = None
        except Exception as e:
            set_err = repr(e)[:200]
        s0 = sample(d, "block_start", block=k, arm=arm, set_error=set_err); emit(s0)
        b_end = min(deadline, s0["t"] + block_s); stop = None
        while time.time() < b_end:
            time.sleep(max(0.0, min(a.sample_min * 60, b_end - time.time())))
            s = sample(d, "sample", block=k, arm=arm); emit(s)
            if s.get("plugged"):
                stop = "replugged"; break
            if s.get("level") is not None and s["level"] < 15:
                stop = "low_battery"; break
        s1 = sample(d, "block_end", block=k, arm=arm); emit(s1)
        try:
            with lmdrv.open_new("%s-block%d-%s-batterystats.txt" % (a.out_prefix, k, arm)) as g:
                g.write(d.sh("dumpsys batterystats", timeout=120, retries=1))
        except Exception as e:
            s1["batterystats_error"] = repr(e)[:200]
        cc = lambda s: s.get("charge_uAh")
        emit({"kind": "block", "block": k, "arm": arm, "t_start": s0["t"], "t_end": s1["t"],
              "duration_s": round(s1["t"] - s0["t"], 1), "charge_start_uAh": cc(s0), "charge_end_uAh": cc(s1),
              "level_start": s0.get("level"), "level_end": s1.get("level"), "complete": stop is None and s1["t"] >= b_end - 5,
              "stopped": stop, "fgs_start": s0.get("fgs"), "fgs_end": s1.get("fgs")})
        if stop:
            break
    try:
        d.sh("am stopservice -n %s/.FgService" % P, timeout=30)
    except Exception:
        pass
    emit({"kind": "end", "t": time.time(), "hours_since_unplug": round((time.time() - t_unplug) / 3600, 3)})
    f.close()


if __name__ == "__main__":
    sys.exit(main())

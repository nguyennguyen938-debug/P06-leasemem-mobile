#!/usr/bin/env python3
"""B11: 24-hour state log of the memory client on the test phone, deployed as a plain background app.

Every PERIOD s (default 5) one `adb shell` call (wireless debugging, phone unplugged) reads: client alive and pid,
oom_score_adj, cgroup freeze state (ActivityManager's isFrozen if the cgroup is unreadable), standby bucket, the
foreground user (P06 Test must stay in the foreground; campaign.py stops the run otherwise), deep and
light Doze state, charger state, battery level and charge counter, screen wakefulness. Only the client's state and the
phone's power state are logged, never user data. One JSONL line per sample, flushed at once; an adb failure is logged
as a sample with "error" and the loop continues (reconnecting a wireless serial). Stops after --hours (default 24).
Each sample is one short shell command, so polling itself wakes the phone briefly every PERIOD s (PHYS-PROTOCOL.md).
Usage: b11_statelog.py SERIAL OUT.jsonl [--hours 24] [--period 5]
"""
import argparse, json, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
import lmdrv

P = lmdrv.CPKG


def sample_cmd(d):
    """One shell command per sample. The pid is the client process of the test user only (uid // 100000 == user)."""
    return ("p=; for q in $(pidof %s); do [ $(( $(stat -c %%u /proc/$q) / 100000 )) -eq %d ] && p=$q; done; echo pid=$p; "
            "if [ -n \"$p\" ]; then echo adj=$(cat /proc/$p/oom_score_adj 2>/dev/null); "
            "c=$(grep ^0:: /proc/$p/cgroup 2>/dev/null | cut -c4-); [ -n \"$c\" ] && echo freeze=$(cat /sys/fs/cgroup$c/cgroup.freeze 2>/dev/null); fi; "
            "echo bucket=$(%s); echo cur=$(am get-current-user); echo deep=$(dumpsys deviceidle get deep); echo light=$(dumpsys deviceidle get light); "
            "dumpsys battery | grep -E 'powered:|level:|Charge counter:'; dumpsys power | grep -m1 mWakefulness=") % (
            P, d.user, d.u("am get-standby-bucket %s" % P))


def parse(txt):
    kv = dict(re.findall(r"^(pid|adj|freeze|bucket|cur|deep|light)=(.*)$", txt, re.M))
    cc = re.search(r"Charge counter: (-?\d+)", txt); lvl = re.search(r"level: (\d+)", txt)
    wake = re.search(r"mWakefulness=(\w+)", txt)
    return {"alive": bool(kv.get("pid", "").strip()), "pid": kv.get("pid", "").strip() or None,
            "oom_score_adj": kv.get("adj"), "frozen": kv.get("freeze") or None, "bucket": kv.get("bucket"),
            "current_user": int(kv["cur"]) if kv.get("cur", "").strip().isdigit() else None,
            "doze_deep": kv.get("deep"), "doze_light": kv.get("light"),
            "plugged": bool(re.search(r"(AC|USB|Wireless|Dock) powered: true", txt)),
            "level": lvl and int(lvl.group(1)), "charge_uAh": cc and int(cc.group(1)), "wakefulness": wake and wake.group(1)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("serial"); ap.add_argument("out")
    ap.add_argument("--hours", type=float, default=24.0); ap.add_argument("--period", type=float, default=5.0)
    a = ap.parse_args()
    d = lmdrv.Dev(a.serial); static = {k: v for k, v in d.meta().items() if k != "plugged"}
    d.sh(d.u("am stopservice -n %s/.FgService" % P)); d.launch(); time.sleep(1); d.home()   # an ordinary background client
    t0 = time.monotonic(); end = t0 + a.hours * 3600; k = 0; CMD = sample_cmd(d)
    with lmdrv.open_new(a.out) as f:
        f.write(json.dumps({**static, "kind": "start", "t": time.time(), "hours": a.hours, "period_s": a.period,
                            "device_config": d.sh("dumpsys activity settings | grep -i freeze").strip()}) + "\n"); f.flush()
        while time.monotonic() < end:
            rec = {**static, "kind": "sample", "i": k, "t": time.time()}
            try:
                txt = d.sh(CMD, timeout=20, retries=0)
                if "pid=" not in txt:
                    raise RuntimeError("empty sample: %r" % txt[:120])
                rec.update(parse(txt))
                if rec["alive"] and rec["frozen"] is None:          # cgroup unreadable: ActivityManager's flag
                    rec["frozen"] = d.frozen(); rec["frozen_method"] = d.frozen_method
                else:
                    rec["frozen_method"] = "cgroup" if rec["frozen"] else None
            except Exception as e:
                rec["error"] = repr(e)[:300]
                if ":" in a.serial:
                    subprocess.run(lmdrv.ADB_CMD + ["connect", a.serial], capture_output=True, timeout=20)
            f.write(json.dumps(rec) + "\n"); f.flush(); k += 1
            # next tick on the fixed grid; ticks missed during a slow or failed call are skipped, not replayed
            time.sleep(max(0.0, t0 + (int((time.monotonic() - t0) // a.period) + 1) * a.period - time.monotonic()))
        f.write(json.dumps({**static, "kind": "end", "t": time.time(), "samples": k}) + "\n")


if __name__ == "__main__":
    main()

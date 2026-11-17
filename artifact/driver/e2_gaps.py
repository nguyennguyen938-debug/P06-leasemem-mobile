#!/usr/bin/env python3
"""E2: lifecycle-gap injection on a real Android 13 emulator.

Per trial (gap type G):
  setup -> settle (drain deferred notifications) -> client OBSERVE + trig RESET -> gap start(G)
  -> mutate each source with prob P_CHANGE (random kind) -> optional hold -> gap end(G)
  -> DECIDE early (+EARLY s) and late (+LATE s) -> read OS-trigger log.
The client evaluates event-only, Tether-style, global refresh, LeaseMem and the epoch ablation in-app;
TTL and the JobScheduler-trigger baseline are computed offline from the logged evidence.
Usage: e2_gaps.py SERIAL GAP N SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

SETTLE = 12.0
EARLY, LATE = 2.0, 14.0
P_CHANGE = 0.5
GAPS = ["none", "kill", "forcestop", "freeze", "doze", "reboot", "unregister", "perm"]
PKGS = [lmdrv.CPKG, lmdrv.TPKG]


def gap_start(d, g, log):
    if g == "none":
        return
    if g == "kill":
        d.home()
        for p in PKGS:
            d.sh("am kill %s" % p)
        time.sleep(0.5)
        for p in PKGS:
            if d.pid(p):                       # am kill only kills cached processes; fall back to SIGKILL
                log["sigkill_fallback_" + p] = True
                d.sh("kill -9 %s" % d.pid(p))
    elif g == "forcestop":
        for p in PKGS:
            d.sh("am force-stop %s" % p)
    elif g == "freeze":
        d.home()
        t0 = time.time()
        while time.time() - t0 < 25:
            st = frozen(d)
            if st == "1":
                break
            time.sleep(0.5)
        log["frozen_after_s"] = round(time.time() - t0, 2)
        log["frozen"] = frozen(d)
    elif g == "doze":
        d.home()
        d.sh("dumpsys battery unplug")
        for p in PKGS:
            d.sh("am set-standby-bucket %s restricted" % p)
        d.sh("dumpsys deviceidle force-idle deep")
        log["idle_state"] = d.sh("dumpsys deviceidle get deep").strip()
        log["bucket"] = d.sh("am get-standby-bucket %s" % lmdrv.CPKG).strip()
    elif g == "reboot":
        pass                                    # the reboot itself happens after the first mutations (below)
    elif g == "unregister":
        d.cmd("UNREGISTER")
    elif g == "perm":
        d.sh("pm revoke %s android.permission.READ_CONTACTS" % lmdrv.CPKG)
        d.sh("pm revoke %s android.permission.READ_CONTACTS" % lmdrv.TPKG)
        time.sleep(0.5)
        log["pid_after_revoke"] = d.pid()


def frozen(d):
    pid = d.pid()
    if not pid:
        return "dead"
    cg = d.sh("cat /proc/%s/cgroup" % pid)
    path = None
    for line in cg.splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
    if not path:
        return "?"
    return d.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>/dev/null" % path).strip() or "?"


def gap_end(d, g, log):
    if g in ("kill", "forcestop", "reboot", "perm"):
        if g == "perm":
            d.sh("pm grant %s android.permission.READ_CONTACTS" % lmdrv.CPKG)
            d.sh("pm grant %s android.permission.READ_CONTACTS" % lmdrv.TPKG)
        log["pid_before_relaunch"] = d.pid()
        d.launch()
        d.launch(lmdrv.TPKG)                    # a real app re-arms its trigger on start
    elif g == "doze":
        d.sh("dumpsys deviceidle unforce")
        d.sh("dumpsys battery reset")
        for p in PKGS:
            d.sh("am set-standby-bucket %s active" % p)
    elif g == "unregister":
        d.cmd("REGISTER")
    elif g == "freeze":
        log["frozen_at_end"] = frozen(d)


def main():
    serial, gap, n, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    assert gap in GAPS
    d = lmdrv.Dev(serial)
    rng = random.Random(seed)
    w = lmdrv.World(d, rng)
    d.launch(); d.launch(lmdrv.TPKG)
    with open(out, "a") as f:
        for t in range(n):
            log = {"trial": t, "gap": gap, "seed": seed, "serial": serial}
            try:
                if not d.pid():
                    d.launch()
                d.home()
                w.ensure_base()
                time.sleep(SETTLE)
                ob = d.cmd("OBSERVE")
                d.sh(": > /data/data/%s/files/trig.log" % lmdrv.TPKG)
                d.trig_cmd("RESET")
                log["t_obs"] = ob["t_recv"]; log["pid_obs"] = ob["pid"]; log["epoch_obs"] = ob["epoch"]
                log["t_gap_start"] = d.now_ms()
                gap_start(d, gap, log)
                plan = []
                for src in lmdrv.World.KINDS:
                    if rng.random() < P_CHANGE:
                        plan.append((src, rng.choice(lmdrv.World.KINDS[src])))
                rng.shuffle(plan)
                if gap == "reboot":
                    half = len(plan) // 2
                    muts = [w.mutate(s, k) for s, k in plan[:half]]
                    log["t_reboot"] = d.now_ms()
                    d.adb("reboot")
                    time.sleep(5)
                    log["boot_s"] = round(d.wait_boot(), 1)
                    d.adb("root"); time.sleep(3); d.wait_boot()
                    d.sh("appops set root WRITE_SMS allow")
                    muts += [w.mutate(s, k) for s, k in plan[half:]]
                else:
                    muts = [w.mutate(s, k) for s, k in plan]
                hold = rng.uniform(0, 4)
                time.sleep(hold)
                log["muts"] = muts; log["hold"] = round(hold, 2)
                log["t_gap_end"] = d.now_ms()
                gap_end(d, gap, log)
                time.sleep(EARLY)
                log["early"] = d.cmd("DECIDE")
                time.sleep(max(0, LATE - EARLY))
                log["late"] = d.cmd("DECIDE")
                log["trig"] = d.trig_log()
                log["pid_dec"] = log["late"]["pid"]
                f.write(json.dumps(log) + "\n"); f.flush()
                print("trial", gap, t, [(m["src"], m["kind"]) for m in muts], flush=True)
            except Exception as e:
                print("ERR", gap, t, repr(e), flush=True)
                log["error"] = repr(e)
                f.write(json.dumps(log) + "\n"); f.flush()
                # recover a sane state
                try:
                    if gap == "doze":
                        gap_end(d, gap, {})
                    d.sh("pm grant %s android.permission.READ_CONTACTS" % lmdrv.CPKG)
                    d.wait_boot(); d.adb("root"); time.sleep(2)
                    d.launch(); d.launch(lmdrv.TPKG)
                    if gap == "unregister":
                        d.cmd("REGISTER")
                except Exception as e2:
                    print("recover failed", repr(e2), flush=True)


if __name__ == "__main__":
    main()

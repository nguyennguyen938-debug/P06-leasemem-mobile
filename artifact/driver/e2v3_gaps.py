#!/usr/bin/env python3
"""E2 v3 (round-2 revision): lifecycle-gap injection, real Android emulator.

Changes vs. round 1 (e2_gaps.py): hold U(HOLD_LO, HOLD_HI) s (default 0-30 s) so change age at the early decision
spans both sides of ContentService's 10 s background deferral; the freezer state is verified before any mutation
(trials that do not freeze are marked invalid and skipped); Doze (force-idle deep) and the restricted standby bucket
are separate gaps; SIGKILL gap (for a foreground-service client that `am kill` cannot kill); optional foreground-
service client (--fg); long realistic gaps (longfreeze: default 600 s freezer debounce; longdoze: deep-idle states
stepped through idle and maintenance windows), and the client's oom_score_adj is logged at gap start.
Usage: e2v3_gaps.py SERIAL GAP N SEED OUT.jsonl [--fg] [--hold LO HI]
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

GAPS = ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "sigkill", "forcestop", "perm", "reboot",
        "longfreeze", "longdoze", "longdoze2"]
PKGS = [lmdrv.CPKG, lmdrv.TPKG]
EARLY, LATE = 2.0, 14.0
P_CHANGE = 0.5


def frozen(d):
    pid = d.pid()
    if not pid:
        return "dead"
    path = None
    for line in d.sh("cat /proc/%s/cgroup" % pid).splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
    return (d.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>/dev/null" % path).strip() or "?") if path else "?"


def start_fg(d):
    d.sh("am start-foreground-service -n %s/.FgService" % lmdrv.CPKG)
    time.sleep(0.8)


def idle_state(d):
    return d.sh("dumpsys deviceidle get deep").strip()


def step_until(d, target, maxsteps=12):
    for _ in range(maxsteps):
        if idle_state(d) == target:
            return True
        d.sh("dumpsys deviceidle step deep")
        time.sleep(0.3)
    return idle_state(d) == target


def mutate_plan(w, rng):
    plan = [(src, rng.choice(lmdrv.World.KINDS[src])) for src in lmdrv.World.KINDS if rng.random() < P_CHANGE]
    rng.shuffle(plan)
    return plan


def main():
    a = sys.argv[1:]
    serial, gap, n, seed, out = a[0], a[1], int(a[2]), int(a[3]), a[4]
    fg = "--fg" in a
    hold_lo, hold_hi = 0.0, 30.0
    if "--hold" in a:
        i = a.index("--hold"); hold_lo, hold_hi = float(a[i + 1]), float(a[i + 2])
    assert gap in GAPS
    d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
    if not fg:   # make sure no foreground service from an earlier run keeps the process in the FGS state
        d.sh("am stopservice -n %s/.FgService" % lmdrv.CPKG)
    d.launch(); d.launch(lmdrv.TPKG)
    if fg:
        start_fg(d)
    with open(out, "a") as f:
        for t in range(n):
            log = {"trial": t, "gap": gap, "seed": seed, "serial": serial, "fg": fg, "protocol": "v3"}
            try:
                if not d.pid():
                    d.launch()
                if fg:
                    start_fg(d)
                d.home()
                made = w.ensure_base().get("made", 1)
                time.sleep(12.0 if made else 2.0)
                ob = d.cmd("OBSERVE")
                d.sh(": > /data/data/%s/files/trig.log" % lmdrv.TPKG)
                d.trig_cmd("RESET")
                log.update({"t_obs": ob["t_recv"], "pid_obs": ob["pid"], "epoch_obs": ob["epoch"]})
                log["oom_adj_obs"] = d.sh("cat /proc/%s/oom_score_adj" % (d.pid() or "self")).strip()
                log["t_gap_start"] = d.now_ms()
                plan = mutate_plan(w, rng)
                muts = []
                # ---------------- gap start ----------------
                if gap in ("kill",):
                    d.home(); time.sleep(0.5)
                    log["oom_adj_kill"] = d.sh("cat /proc/%s/oom_score_adj" % (d.pid() or "self")).strip()
                    for p in PKGS:
                        d.sh("am kill %s" % p)
                    time.sleep(0.5)
                    log["alive_after_amkill"] = bool(d.pid())
                elif gap == "sigkill":
                    for p in PKGS:
                        if d.pid(p):
                            d.sh("kill -9 %s" % d.pid(p))
                elif gap == "forcestop":
                    for p in PKGS:
                        d.sh("am force-stop %s" % p)
                elif gap in ("freeze", "longfreeze"):
                    d.home()
                    t0 = time.time(); limit = 25 if gap == "freeze" else 900
                    while time.time() - t0 < limit and frozen(d) != "1":
                        time.sleep(0.5 if gap == "freeze" else 5)
                    log["frozen_after_s"] = round(time.time() - t0, 1)
                    log["frozen"] = frozen(d)
                    if log["frozen"] != "1":
                        log["invalid"] = "not_frozen"
                        f.write(json.dumps(log) + "\n"); f.flush()
                        print("INVALID not frozen", gap, t, flush=True)
                        continue
                elif gap == "dozeidle":
                    d.home(); d.sh("dumpsys battery unplug"); d.sh("dumpsys deviceidle force-idle deep")
                    log["idle_state"] = idle_state(d)
                elif gap == "bucket":
                    d.home()
                    for p in PKGS:
                        d.sh("am set-standby-bucket %s restricted" % p)
                    log["bucket"] = d.sh("am get-standby-bucket %s" % lmdrv.CPKG).strip()
                elif gap in ("longdoze", "longdoze2"):
                    d.home(); d.sh("dumpsys battery unplug"); d.sh("input keyevent KEYCODE_SLEEP")
                    d.sh("dumpsys deviceidle force-inactive")
                    log["reached_idle"] = step_until(d, "IDLE")
                elif gap == "unregister":
                    d.cmd("UNREGISTER")
                elif gap == "perm":
                    for p in PKGS:
                        d.sh("pm revoke %s android.permission.READ_CONTACTS" % p)
                    time.sleep(0.5)
                # ---------------- mutations during the gap ----------------
                if gap == "reboot":
                    half = len(plan) // 2
                    muts = [w.mutate(s, k) for s, k in plan[:half]]
                    log["t_reboot"] = d.now_ms()
                    d.adb("reboot"); time.sleep(5)
                    log["boot_s"] = round(d.wait_boot(), 1)
                    d.adb("root"); time.sleep(3); d.wait_boot()
                    d.sh("appops set root WRITE_SMS allow")
                    muts += [w.mutate(s, k) for s, k in plan[half:]]
                    hold = rng.uniform(hold_lo, hold_hi)
                elif gap == "longdoze2":
                    # verified version: both mutation batches are made only after the logged deep-idle state is IDLE
                    half = len(plan) // 2
                    log["freeze_debounce"] = d.sh("dumpsys activity settings | grep freeze_debounce").strip()
                    log["reached_idle_1"] = step_until(d, "IDLE"); log["state_m1"] = idle_state(d); log["frozen_m1"] = frozen(d)
                    muts = [w.mutate(s, k) for s, k in plan[:half]]
                    time.sleep(240)
                    d.sh("dumpsys deviceidle step deep"); time.sleep(1)
                    log["state_maint"] = idle_state(d)
                    time.sleep(30)
                    log["reached_idle_2"] = step_until(d, "IDLE"); log["state_m2"] = idle_state(d); log["frozen_m2"] = frozen(d)
                    muts += [w.mutate(s, k) for s, k in plan[half:]]
                    log["state_after_m2"] = idle_state(d)
                    time.sleep(300)
                    log["frozen_end_doze"] = frozen(d)
                    hold = 0.0
                elif gap == "longdoze":
                    half = len(plan) // 2
                    muts = [w.mutate(s, k) for s, k in plan[:half]]
                    log["state_m1"] = idle_state(d)
                    time.sleep(240)
                    d.sh("dumpsys deviceidle step deep")          # IDLE -> IDLE_MAINTENANCE
                    log["state_maint"] = idle_state(d)
                    time.sleep(30)
                    d.sh("dumpsys deviceidle step deep")          # back to IDLE
                    log["state_m2"] = idle_state(d)
                    muts += [w.mutate(s, k) for s, k in plan[half:]]
                    time.sleep(300)
                    hold = 0.0
                elif gap == "longfreeze":
                    muts = [w.mutate(s, k) for s, k in plan]
                    hold = 60.0
                else:
                    muts = [w.mutate(s, k) for s, k in plan]
                    hold = rng.uniform(hold_lo, hold_hi)
                time.sleep(hold)
                log["muts"] = muts; log["hold"] = round(hold, 2)
                if gap in ("freeze", "longfreeze"):
                    log["frozen_at_end"] = frozen(d)
                if gap in ("dozeidle", "longdoze", "longdoze2"):
                    log["idle_state_end"] = idle_state(d)
                log["t_gap_end"] = d.now_ms()
                # ---------------- gap end ----------------
                if gap in ("kill", "sigkill", "forcestop", "reboot", "perm"):
                    if gap == "perm":
                        for p in PKGS:
                            d.sh("pm grant %s android.permission.READ_CONTACTS" % p)
                    log["pid_before_relaunch"] = d.pid()
                    d.launch(); d.launch(lmdrv.TPKG)
                    if fg:
                        start_fg(d)
                elif gap in ("dozeidle", "longdoze", "longdoze2"):
                    d.sh("dumpsys deviceidle unforce"); d.sh("dumpsys battery reset"); d.sh("input keyevent KEYCODE_WAKEUP")
                elif gap == "bucket":
                    for p in PKGS:
                        d.sh("am set-standby-bucket %s active" % p)
                elif gap == "unregister":
                    d.cmd("REGISTER")
                time.sleep(EARLY)
                log["early"] = d.cmd("DECIDE")
                time.sleep(max(0, LATE - EARLY))
                log["late"] = d.cmd("DECIDE")
                log["trig"] = d.trig_log()
                f.write(json.dumps(log) + "\n"); f.flush()
                print("trial", gap, "fg" if fg else "bg", t, len(muts), flush=True)
            except Exception as e:
                print("ERR", gap, t, repr(e), flush=True)
                log["error"] = repr(e)
                f.write(json.dumps(log) + "\n"); f.flush()
                try:
                    d.sh("dumpsys deviceidle unforce"); d.sh("dumpsys battery reset"); d.sh("input keyevent KEYCODE_WAKEUP")
                    for p in PKGS:
                        d.sh("pm grant %s android.permission.READ_CONTACTS" % p)
                        d.sh("am set-standby-bucket %s active" % p)
                    d.wait_boot(); d.adb("root"); time.sleep(2)
                    d.launch(); d.launch(lmdrv.TPKG)
                    if gap == "unregister":
                        d.cmd("REGISTER")
                    if fg:
                        start_fg(d)
                except Exception as e2:
                    print("recover failed", repr(e2), flush=True)


if __name__ == "__main__":
    main()

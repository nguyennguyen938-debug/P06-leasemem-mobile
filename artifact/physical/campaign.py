#!/usr/bin/env python3
"""Physical-phone campaign runner: one entry point per plan task (B0 to B12) on the user's personal phone, inside
the Android user "P06 Test" (lmdrv enforces the isolation rules; PHYS-PROTOCOL.md sections 3 and 4).

Before the first step it records the device-wide settings the drivers may touch (freezer debounce and DeviceConfig
sync mode, P06's two Settings.Global keys, standby buckets of P06 apps) in build/phone-restore-state.json; after
every step, also a failed or stopped one, it restores them and resets battery and Doze overrides, the test user's
assistant role and READ_CONTACTS grants. If the runner itself dies, `campaign.py --restore` restores from that file.
While a driver runs, a watchdog reads the foreground user every 10 s and stops the run if it is not P06 Test (a
reboot pauses the watchdog until the user has switched back). Reboots need --allow-reboot (the user's consent for
this run); without it B2 skips its reboot gap and B0 its reboot probe.

Raw output goes to <out-root>/physical-<YYYYMMDD>/ (default out-root artifact/results; new files only); driver logs
to physical-<YYYYMMDD>/logs/; one line per command is appended to <out-root>/RUNLOG.md. Trial counts and seeds are
those of PLAN-dien-thoai-that.md section 4 and PHYS-PROTOCOL.md.

Usage: python physical/campaign.py TASK --serial SERIAL [--pilot] [--dry-run] [--night 1|2] [--allow-reboot]
                                   [--out-root DIR]
       python physical/campaign.py --restore --serial SERIAL
  TASK: setup B0 B1 B2 B3 B4 B5 B6 B7 B9 B10 B11 B12 cleanup   (--pilot: 2 trials per condition, for S2)
Environment: ANDROID_HOME (finds adb); P06_SERIALS = the phone's ro.serialno (lmdrv allowlist).
"""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path

A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver")); sys.path.insert(0, str(A / "revision"))
os.environ["P06_CAMPAIGN"] = "1"
import lmdrv

PY = sys.executable
STATE = Path(os.environ.get("P06_RESTORE_STATE") or A.parent / "build" / "phone-restore-state.json")
PAUSE = STATE.with_name(STATE.name + ".fg-pause")
APKS = {"client": "app/client/build/LeaseMemClient-v4.apk", "mut": "app/mut/build/LeaseMemMut.apk",
        "trig": "app/trig/build/LeaseMemTrig.apk", "assist": "app/assist/build/LeaseMemAssist.apk"}
PKGS = [lmdrv.CPKG, lmdrv.MPKG, lmdrv.TPKG, lmdrv.APKG]
GAPS = ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot"]   # B2
BUCKET = {"5": "exempted", "10": "active", "20": "working_set", "30": "frequent", "40": "rare", "45": "restricted", "50": "never"}
DEBOUNCE = ("device_config set_sync_disabled_for_tests until_reboot; "
            "device_config put activity_manager_native_boot freeze_debounce_timeout %d")


def steps(task, serial, out, hm, pilot, night, excluded, allow_reboot):
    """[(label, argv, pre-commands, main output file)] for one task; pre-commands are user-scoped via {u:...}."""
    D, P, R = str(A / "driver"), str(A / "physical"), str(A / "revision")
    n = lambda full: 2 if pilot else full
    # --pilot files carry "pilot" in their name (gaps-pilot-none-HHMM...): analyze_phys.py keeps them out of the main numbers
    t = lambda name: name.replace("-", "-pilot-", 1) if pilot and "-" in name else name + "-pilot" if pilot else name
    o = lambda name: str(out / ("%s-%s.jsonl" % (t(name), hm)))
    sfx = ("-pilot-" if pilot else "-") + hm   # passed as --suffix=<sfx>: a value starting with "-pilot" would read as an option
    stop_fgs = "{u:am stopservice -n %s/.FgService}" % lmdrv.CPKG
    if task in ("setup", "cleanup"):
        return []
    if task == "B0":
        return [("probe", [PY, P + "/b0_probe.py", serial, o("b0-probe")] + (["--allow-reboot"] if allow_reboot else []), [], o("b0-probe")),
                ("trial", [PY, D + "/e2v3_gaps.py", serial, "none", "1", "2611000", o("b0-trial-none")],
                 [stop_fgs, DEBOUNCE % 600000], o("b0-trial-none"))]
    if task == "B1":
        return [("deploy-" + src, [PY, str(A / "followup/deployment.py"), serial, "--out", o("deploy-" + src),
                                   "--source", src, "--n", str(n(20))] + (["--modes", "bg_unfrozen,fg"] if src != "contacts" else []),
                 [], o("deploy-" + src)) for src in ("contacts", "media", "calllog") if src not in excluded]
    if task == "B2":
        return [("gap-" + g, [PY, D + "/e2v3_gaps.py", serial, g, str(n(25)), str(2611201 + i), o("gaps-" + g)],
                 [stop_fgs, DEBOUNCE % (2000 if g == "freeze" else 600000)], o("gaps-" + g))
                for i, g in enumerate(GAPS) if g != "reboot" or allow_reboot]
    if task == "B3":
        return [("coverage", [PY, D + "/e1_coverage.py", serial, str(n(30)), "2611301", o("coverage")], [stop_fgs], o("coverage"))]
    if task == "B4":
        f = str(out / ("stock-%s%s.jsonl" % (serial.replace(":", "_"), sfx)))
        return [("stock", [PY, R + "/run.py", serial, "stock", "--n", str(n(20)), "--out-dir", str(out), "--suffix=" + sfx], [], f)]
    if task == "B5":
        return [("frozen", [PY, D + "/e9_frozen.py", serial, str(n(10)), "2611501", o("frozen"), "600"], [DEBOUNCE % 2000], o("frozen"))]
    if task == "B6":
        f = str(out / ("host-%s%s.jsonl" % (serial.replace(":", "_"), sfx)))
        return [("host", [PY, R + "/run.py", serial, "host", "--n", str(n(30)), "--arms", "refresh,validate,stamp,relay,memo",
                          "--out-dir", str(out), "--suffix=" + sfx], [], f)]
    if task == "B7":
        return [("continuous", [PY, P + "/b7_continuous.py", serial, o("continuous"), "--n", str(n(30))], [], o("continuous"))]
    if task == "B9":     # the boundary effect is a call-log row: needs the call log
        return [] if "calllog" in excluded else [
            ("boundary", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), "2611901", o("boundary")], [stop_fgs], o("boundary")),
            ("boundary-band", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), "2611902", o("boundary-band"), "band"],
             [stop_fgs], o("boundary-band"))]
    if task == "B10":
        return [("pitfalls", [PY, D + "/e6_pitfalls.py", serial, str(n(50)), "2611001", o("pitfalls")], [stop_fgs], o("pitfalls"))]
    if task == "B11":
        return [("statelog", [PY, P + "/b11_statelog.py", serial, o("statelog"), "--hours", "0.05" if pilot else "24"], [], o("statelog"))]
    if task == "B12":
        order = "on,off,on,off" if night == 1 else "off,on,off,on"
        pre = str(out / ("%s-%s" % (t("battery-night%d" % night), hm)))
        return [("battery", [PY, P + "/b12_battery.py", serial, pre, "--order", order] + (["--max-hours", "0.2", "--sample-min", "1"] if pilot else []),
                 [], pre + "-samples.jsonl")]
    raise SystemExit("unknown task " + task)


def run_pre(d, cmd):
    if cmd.startswith("{u:"):
        return d.sh(d.u(cmd[3:-1]))
    return d.sh(cmd)


def snapshot(d):
    """Device-wide values the drivers may change, read before the first change."""
    g = lambda c: d.sh(c, timeout=30).strip()
    return {"debounce": g("device_config get activity_manager_native_boot freeze_debounce_timeout"),
            "sync_disabled": g("device_config get_sync_disabled_for_tests"),
            "settings": {k: g("settings get global " + k) for k in ("lm_mode", "lm_target")},
            "buckets": {p: g(d.u("am get-standby-bucket %s" % p)) for p in PKGS}, "t": time.time()}


def restore(d, snap):
    """Put every device-wide value back; also clear battery and Doze overrides and the test user's assistant role.
    Without a snapshot (state file lost) it applies the platform defaults. Returns the commands that failed."""
    snap = snap or {"debounce": "null", "sync_disabled": "none", "settings": {"lm_mode": "null", "lm_target": "null"}, "buckets": {}}
    deb, sync = snap["debounce"], snap["sync_disabled"]
    cmds = ["dumpsys battery reset", "dumpsys deviceidle unforce",
            "device_config delete activity_manager_native_boot freeze_debounce_timeout" if deb in ("", "null")
            else "device_config put activity_manager_native_boot freeze_debounce_timeout %s" % deb,
            "device_config set_sync_disabled_for_tests %s" % (sync if sync in ("none", "persistent", "until_reboot") else "none")]
    cmds += ["settings delete global %s" % k if v in ("", "null") else "settings put global %s %s" % (k, v) for k, v in snap["settings"].items()]
    cmds += ["{u:am set-standby-bucket %s %s}" % (p, BUCKET[b]) for p, b in snap["buckets"].items() if b in BUCKET]
    cmds += ["{u:cmd role remove-role-holder android.app.role.ASSISTANT %s 0}" % lmdrv.APKG]
    cmds += ["{u:pm grant %s android.permission.READ_CONTACTS}" % p for p in (lmdrv.CPKG, lmdrv.TPKG)]
    failed = []
    for c in cmds:
        try:
            run_pre(d, c)
        except Exception as e:
            failed.append("%s: %r" % (c, e))
    return failed


def sha(rel):
    p = A / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else "missing"


def counts(path):
    try:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return "no output file"
    return "%d records, %d error, %d invalid" % (len(rows), sum("error" in r for r in rows), sum("invalid" in r for r in rows))


def runlog(out_root, line):
    p = Path(out_root) / "RUNLOG.md"; head = "## %s (physical phone)" % time.strftime("%Y-%m-%d")
    have = p.exists() and head in p.read_text(encoding="utf-8")
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if have else "\n" + head + "\n") + line + "\n")


def run_step(d, argv, log, env):
    """Run one driver; stop it if a successful read shows another foreground user (unless a reboot paused the check)."""
    with open(log, "x", encoding="utf-8") as lf:
        proc = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT, cwd=str(A), env=env)
        while True:
            try:
                return proc.wait(timeout=10), None
            except subprocess.TimeoutExpired:
                pass
            if d.emulator or PAUSE.exists():
                continue
            try:
                cur = d.current_user()
            except Exception:
                continue                                   # adb hiccup (wireless): not evidence of a user switch
            if cur is not None and cur != d.user:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return proc.returncode, "stopped: foreground user %s is not %r" % (cur, lmdrv.TEST_USER)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("task", nargs="?"); ap.add_argument("--serial", required=True)
    ap.add_argument("--pilot", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--night", type=int, default=1, choices=[1, 2]); ap.add_argument("--allow-reboot", action="store_true")
    ap.add_argument("--restore", action="store_true"); ap.add_argument("--out-root", default=str(A / "results"))
    a = ap.parse_args()
    out_root = Path(a.out_root).resolve()
    if ADB_IS_FAKE and out_root == (A / "results").resolve():
        raise SystemExit("the fake adb never writes to artifact/results; pass --out-root <scratch dir>")
    out = out_root / ("physical-" + time.strftime("%Y%m%d")); hm = time.strftime("%H%M")
    if a.dry_run:
        for label, argv, pre, f in steps(a.task, a.serial, out, hm, a.pilot, a.night, {"sms"}, a.allow_reboot):
            print("[%s] pre: %s\n    run: %s\n    out: %s" % (label, "; ".join(pre) or "-", " ".join(argv), f))
        print("(dry run assumes only SMS excluded; the call log is excluded too unless the test user has no_outgoing_calls)")
        return 0
    try:
        d = lmdrv.Dev(a.serial)
    except RuntimeError as e:
        raise SystemExit("ERROR: %s" % e)
    if a.restore:
        snap = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
        failed = restore(d, snap)
        if not failed and STATE.exists():
            STATE.unlink()
        runlog(out_root, "- %s restore: `campaign.py --restore` from %s; %s" % (
            time.strftime("%H:%M"), "snapshot" if snap else "platform defaults (no snapshot)", "ok" if not failed else "FAILED: %s" % failed))
        print("restore", "ok" if not failed else failed)
        return 1 if failed else 0
    if not a.task:
        raise SystemExit("give a TASK or --restore")
    missing = [k for k, v in APKS.items() if not (A / v).exists()]
    if missing:
        raise SystemExit("APKs not built: %s (run app/*/build.sh with JAVA_HOME and ANDROID_HOME)" % missing)
    if STATE.exists():
        raise SystemExit("an earlier run did not restore the phone's settings (%s); run `campaign.py --restore` first" % STATE)
    plan = steps(a.task, a.serial, out, hm, a.pilot, a.night, d.excluded, a.allow_reboot)
    meta = d.meta(); apk = " ".join("%s %s" % (k, sha(v)) for k, v in APKS.items())
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(snapshot(d)), encoding="utf-8"); snap = json.loads(STATE.read_text(encoding="utf-8"))
    env = dict(os.environ, P06_FG_PAUSE_FILE=str(PAUSE), **({"P06_ALLOW_REBOOT": "1"} if a.allow_reboot else {}))
    status, failed = 0, []
    try:
        if a.task == "cleanup":                 # end of the campaign: remove P06 apps from the test user only
            for p in PKGS:
                d.sh(d.u("pm uninstall %s" % p))
            runlog(out_root, "- %s cleanup: uninstalled %s from user %s" % (time.strftime("%H:%M"), ", ".join(PKGS), d.user))
            return 0
        sys.path.insert(0, str(A / "physical")); import b0_setup
        out.mkdir(parents=True, exist_ok=True)
        rec = b0_setup.setup(d, out)
        runlog(out_root, "- %s %s setup: `campaign.py %s` on %s (`%s`, user %s, excluded %s, foreign rows %s); APK sha256 %s" % (
            time.strftime("%H:%M"), a.task, a.task, meta["device"], meta["fingerprint"], d.user, sorted(d.excluded),
            rec["foreign_before"], apk))
        d.sh(d.u("am stopservice -n %s/.FgService" % lmdrv.CPKG))
        skipped = sorted({"gap reboot (no --allow-reboot)": a.task == "B2" and not a.allow_reboot, "B9 (call log excluded)": a.task == "B9" and not plan,
                          "B1 call log": a.task == "B1" and "calllog" in d.excluded} .items())
        for k, v in skipped:
            if v:
                runlog(out_root, "- %s %s skipped: %s" % (time.strftime("%H:%M"), a.task, k))
        (out / "logs").mkdir(parents=True, exist_ok=True)
        for label, argv, pre, f in plan:
            d.require_fg()
            for cmd in pre:
                run_pre(d, cmd)
            t0 = time.time(); log = out / "logs" / ("%s-%s-%s.log" % (a.task, label, hm))
            try:
                rc, stopped = run_step(d, argv, log, env)
            finally:
                failed = restore(d, snap)
            status = status or rc or (1 if stopped else 0)
            try:
                plugged = d.plugged()
            except Exception as e:
                plugged = "unknown (%s)" % type(e).__name__
            runlog(out_root, "- %s %s %s%s: `%s` on %s (`%s`, user %s, rooted=%s, plugged=%s); APK sha256 %s; %.1f min; exit %s; %s%s; restore %s; output `%s`, log `%s`" % (
                time.strftime("%H:%M"), a.task, label, " (pilot)" if a.pilot else "", " ".join(Path(x).name if i < 2 else x for i, x in enumerate(argv)),
                meta["device"], meta["fingerprint"], d.user, meta["rooted"], plugged, apk, (time.time() - t0) / 60, rc,
                counts(f), "; " + stopped if stopped else "", "ok" if not failed else "FAILED %s" % failed, Path(f).name, log.name))
            print(label, "exit", rc, counts(f), stopped or "", flush=True)
            if stopped or failed:
                break
    finally:
        failed = restore(d, snap)
        if not failed:
            STATE.unlink()
        else:
            print("RESTORE FAILED %s; state kept in %s; run `campaign.py --restore`" % (failed, STATE), flush=True)
    return status


ADB_IS_FAKE = lmdrv.ADB.endswith(".py")

if __name__ == "__main__":
    sys.exit(main())

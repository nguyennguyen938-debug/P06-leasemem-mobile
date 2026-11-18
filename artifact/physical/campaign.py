#!/usr/bin/env python3
"""Physical-phone campaign runner: one entry point per plan task (B0 to B12) on the user's personal phone, inside
the Android user "P06 Test" (lmdrv enforces the isolation rules; PHYS-PROTOCOL.md sections 3 and 4).

Before the first step it records the device-wide settings the drivers may touch (freezer debounce and DeviceConfig
sync mode, P06's two Settings.Global keys, standby buckets of P06 apps) in build/phone-restore-state.json; after
every step, also a failed or stopped one, it restores them and resets battery and Doze overrides, the test user's
assistant role and READ_CONTACTS grants, checking every command's exit status and reading every restored value back
against the snapshot; any failure goes to RUNLOG and keeps the state file. If the runner itself dies,
`campaign.py --restore` restores from that file.
While a driver runs, a watchdog reads the foreground user every 10 s and stops the run if it is not P06 Test (a
reboot pauses the watchdog until the user has switched back). Reboots need --allow-reboot (the user's consent for
this run); without it B2 skips its reboot gap and B0 its reboot probe.

Raw output goes to <out-root>/physical-<YYYYMMDD>/ (default out-root artifact/results; new files only); driver logs
to physical-<YYYYMMDD>/logs/; one line per command is appended to <out-root>/RUNLOG.md. Trial counts and seeds are
those of PLAN-dien-thoai-that.md section 4 and PHYS-PROTOCOL.md.

Usage: python physical/campaign.py TASK --serial SERIAL [--pilot] [--dry-run] [--night 1|2] [--allow-reboot]
                                   [--out-root DIR] [--only LABELS] [--trials N] [--part K] [--budget-min M]
       python physical/campaign.py --restore --serial SERIAL
  TASK: setup B0 B1 B2 B3 B4 B5 B6 B7 B9 B10 B11 B12 B13 cleanup   (--pilot: 2 trials per condition, for S2)
On AWS Device Farm (P06_TARGET=aws) one invocation is one Device Farm run of at most 150 min: artifact/aws/
devicefarm.py splits a task into runs with --only (step labels), --trials (trials per step), --part (seed offset
and file tag, so parts never share seeds or file names) and --budget-min (no new step starts after that many
minutes). Every run prepares the wiped phone itself (b0_setup.py). B11 and B12 are dropped on AWS: the phones are
always charging and a run lasts at most 150 min.
Environment: ANDROID_HOME (finds adb); P06_SERIALS = the phone's ro.serialno (lmdrv allowlist).
"""
import argparse, hashlib, json, os, re, subprocess, sys, time
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


def steps(task, serial, out, hm, pilot, night, excluded, allow_reboot, trials=None, part=0, tag=None):
    """[(label, argv, pre-commands, main output file)] for one task; pre-commands are user-scoped via {u:...}.
    trials overrides the trials per step; part K > 0 adds 1000*K to every seed and "-pK" to every file name."""
    D, P, R = str(A / "driver"), str(A / "physical"), str(A / "revision")
    n = lambda full: 2 if pilot else trials if trials else full
    sd = lambda base: str(base + 1000 * part)
    # --pilot files carry "pilot" in their name (gaps-pilot-none-HHMM...): analyze_phys.py keeps them out of the main numbers
    t = lambda name: (name.replace("-", "-pilot-", 1) if pilot and "-" in name else name + "-pilot" if pilot else name) + ("-p%d" % part if part else "")
    o = lambda name: str(out / ("%s-%s.jsonl" % (t(name), hm)))
    sfx = ("-pilot-" if pilot else "-") + ("p%d-" % part if part else "") + hm   # passed as --suffix=<sfx>: a value starting with "-" would read as an option
    stop_fgs = "{u:am stopservice -n %s/.FgService}" % lmdrv.CPKG
    if task in ("setup", "cleanup"):
        return []
    if task == "B0":
        return [("probe", [PY, P + "/b0_probe.py", serial, o("b0-probe")] + (["--allow-reboot"] if allow_reboot else []), [], o("b0-probe")),
                ("trial", [PY, D + "/e2v3_gaps.py", serial, "none", "1", sd(2611000), o("b0-trial-none")],
                 [stop_fgs, DEBOUNCE % 600000], o("b0-trial-none"))]
    if task == "B1":
        return [("deploy-" + src, [PY, str(A / "followup/deployment.py"), serial, "--out", o("deploy-" + src),
                                   "--source", src, "--n", str(n(20))] + (["--modes", "bg_unfrozen,fg"] if src != "contacts" else []),
                 [], o("deploy-" + src)) for src in ("contacts", "media", "calllog") if src not in excluded]
    if task == "B2":
        return [("gap-" + g, [PY, D + "/e2v3_gaps.py", serial, g, str(n(25)), sd(2611201 + i), o("gaps-" + g)],
                 [stop_fgs, DEBOUNCE % (2000 if g == "freeze" else 600000)], o("gaps-" + g))
                for i, g in enumerate(GAPS) if g != "reboot" or allow_reboot]
    if task == "B3":
        return [("coverage", [PY, D + "/e1_coverage.py", serial, str(n(30)), sd(2611301), o("coverage")], [stop_fgs], o("coverage"))]
    if task == "B4":
        f = str(out / ("stock-%s%s.jsonl" % (serial.replace(":", "_"), sfx)))
        return [("stock", [PY, R + "/run.py", serial, "stock", "--n", str(n(20)), "--out-dir", str(out), "--suffix=" + sfx], [], f)]
    if task == "B5":
        return [("frozen", [PY, D + "/e9_frozen.py", serial, str(n(10)), sd(2611501), o("frozen"), "600"], [DEBOUNCE % 2000], o("frozen"))]
    if task == "B6":
        f = str(out / ("host-%s%s.jsonl" % (serial.replace(":", "_"), sfx)))
        return [("host", [PY, R + "/run.py", serial, "host", "--n", str(n(30)), "--arms", "refresh,validate,stamp,relay,memo",
                          "--out-dir", str(out), "--suffix=" + sfx], [], f)]
    if task == "B7":
        return [("continuous", [PY, P + "/b7_continuous.py", serial, o("continuous"), "--n", str(n(30))], [], o("continuous"))]
    if task == "B1FD":   # B1 bg_freezer diagnosis (run 106d9bc0 never froze): 2 trials per launch variant, Contacts
        return [("freeze-diag", [PY, str(A / "followup/deployment.py"), serial, "--out", o("diag-b1-freeze"),
                                 "--source", "contacts", "--freeze-diag", "2"], [], o("diag-b1-freeze"))]
    if task == "B1F":    # B1 bg_freezer only (rerun after the diagnosis), Contacts
        return [("deploy-contacts-freezer", [PY, str(A / "followup/deployment.py"), serial, "--out", o("deploy-contacts-freezer"),
                                             "--source", "contacts", "--modes", "bg_freezer", "--n", str(n(20))], [], o("deploy-contacts-freezer"))]
    if task == "B9":     # the effect is a call-log row, or a Contacts Data row where the call log is excluded (AWS)
        return [
            ("boundary", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), sd(2611901), o("boundary")], [stop_fgs], o("boundary")),
            ("boundary-band", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), sd(2611902), o("boundary-band"), "band"],
             [stop_fgs], o("boundary-band"))]
    if task == "B10":
        return [("pitfalls", [PY, D + "/e6_pitfalls.py", serial, str(n(50)), sd(2611001), o("pitfalls")], [stop_fgs], o("pitfalls"))]
    if task in ("B13", "B14"):   # another model: B1 Contacts (4 deployments, 10 trials) and B2 with 5 main gaps (10 trials
        # each); files start with "b13-" (B14: "b13-<tag>-", one tag per model) so the main model's analyses never read them
        if task == "B14" and not tag:
            raise SystemExit("B14 needs --tag <model> (file names b13-<tag>-*)")
        b = "b13-" if task == "B13" else "b13-%s-" % tag
        return [(b + "deploy-contacts", [PY, str(A / "followup/deployment.py"), serial, "--out", o(b + "deploy-contacts"),
                                         "--source", "contacts", "--n", str(n(10))], [], o(b + "deploy-contacts"))] + [
            (b + "gap-" + g, [PY, D + "/e2v3_gaps.py", serial, g, str(n(10)), sd(2621301 + i), o(b + "gaps-" + g)],
             [stop_fgs, DEBOUNCE % (2000 if g == "freeze" else 600000)], o(b + "gaps-" + g))
            for i, g in enumerate(["none", "freeze", "dozeidle", "kill", "forcestop"])]
    if task == "B11":
        return [("statelog", [PY, P + "/b11_statelog.py", serial, o("statelog"), "--hours", "0.05" if pilot else "24"], [], o("statelog"))]
    if task == "B12":
        order = "on,off,on,off" if night == 1 else "off,on,off,on"
        pre = str(out / ("%s-%s" % (t("battery-night%d" % night), hm)))
        return [("battery", [PY, P + "/b12_battery.py", serial, pre, "--order", order] + (["--max-hours", "0.2", "--sample-min", "1"] if pilot else []),
                 [], pre + "-samples.jsonl")]
    raise SystemExit("unknown task " + task)


def run_pre(d, cmd, check=False):
    if cmd.startswith("{u:"):
        return d.sh(d.u(cmd[3:-1]), check=check, timeout=90)
    return d.sh(cmd, check=check, timeout=90)        # 90: a package dump may take up to its own 60 s


def snapshot(d):
    """Device-wide values the drivers may change, read before the first change."""
    g = lambda c: d.sh(c, timeout=30).strip()
    return {"debounce": g("device_config get activity_manager_native_boot freeze_debounce_timeout"),
            "sync_disabled": g("device_config get_sync_disabled_for_tests"),
            "settings": {k: g("settings get global " + k) for k in ("lm_mode", "lm_target")},
            "buckets": {p: g(d.u("am get-standby-bucket %s" % p)) for p in PKGS}, "t": time.time(),
            **({"freezer_setting": g("settings get global cached_apps_freezer")} if d.aws else {})}


def restore(d, snap):
    """Put every recorded device-wide value back, reset battery and Doze overrides, remove the test user's assistant
    role and re-grant READ_CONTACTS. Each command runs with its exit status checked; each restored value is then read
    back and compared with the snapshot (battery and Doze resets have no recorded value, so only their exit status is
    checked). Without a snapshot (state file lost) the platform defaults are the target. Returns what failed: an empty
    list means every command exited 0 and every read-back value matched."""
    snap = snap or {"debounce": "null", "sync_disabled": "none", "settings": {"lm_mode": "null", "lm_target": "null"}, "buckets": {}}
    deb = snap["debounce"] if snap["debounce"] not in ("",) else "null"
    sync = snap["sync_disabled"]
    is_ = lambda want: (lambda got: got == want)
    pkgs = set(re.findall(r"package:(\S+)", d.sh(d.u("pm list packages org.leasemem"), timeout=30)))
    # (command, read-back command or None, test of the read-back output, what was expected)
    todo = [("dumpsys battery reset", None, None, None), ("dumpsys deviceidle unforce", None, None, None),
            ("device_config delete activity_manager_native_boot freeze_debounce_timeout" if deb == "null"
             else "device_config put activity_manager_native_boot freeze_debounce_timeout %s" % deb,
             "device_config get activity_manager_native_boot freeze_debounce_timeout", is_(deb), deb)]
    if sync in ("none", "persistent", "until_reboot"):
        todo.append(("device_config set_sync_disabled_for_tests %s" % sync, "device_config get_sync_disabled_for_tests", is_(sync), sync))
    else:   # the phone did not report a sync mode: re-enable sync, nothing recorded to compare with
        todo.append(("device_config set_sync_disabled_for_tests none", None, None, None))
    for k, v in snap["settings"].items():
        v = v if v not in ("",) else "null"
        todo.append(("settings delete global %s" % k if v == "null" else "settings put global %s %s" % (k, v),
                     "settings get global %s" % k, is_(v), v))
    if d.aws and "freezer_setting" in snap:   # campaign turned the freezer on where the unit had it off
        fs = snap["freezer_setting"] if snap["freezer_setting"] not in ("",) else "null"
        todo.append(("settings delete global cached_apps_freezer" if fs == "null" else "settings put global cached_apps_freezer %s" % fs,
                     "settings get global cached_apps_freezer", is_(fs), fs))
    if d.aws:   # B10 moves the clock on AWS phones (cmd alarm set-time): automatic time is always back on at the end
        todo.append(("settings put global auto_time 1", "settings get global auto_time", is_("1"), "1"))
    for p, b in snap["buckets"].items():
        if b in BUCKET and p in pkgs:
            todo.append(("{u:am set-standby-bucket %s %s}" % (p, BUCKET[b]), "{u:am get-standby-bucket %s}" % p, is_(b), b))
    if lmdrv.APKG in pkgs:
        todo.append(("{u:cmd role remove-role-holder android.app.role.ASSISTANT %s 0}" % lmdrv.APKG,
                     "{u:cmd role get-role-holders android.app.role.ASSISTANT}", lambda got: lmdrv.APKG not in got, "no P06 holder"))
    for p in (lmdrv.CPKG, lmdrv.TPKG):
        if p in pkgs:
            todo.append(("{u:pm grant %s android.permission.READ_CONTACTS}" % p, lmdrv.DUMP_PKG % p,
                         lambda got: "android.permission.READ_CONTACTS: granted=true" in got, "READ_CONTACTS granted"))
    failed = []
    for cmd, back, ok, want in todo:
        try:
            run_pre(d, cmd, check=True)
        except Exception as e:
            failed.append("%s: exit error %s" % (cmd, str(e).strip()[:160])); continue
        if back:
            try:
                for attempt in range(3):     # a package dump can come back empty on a busy phone (B0 run 1c18f498)
                    got = run_pre(d, back, check=True).strip()
                    if ok(got):
                        break
                    time.sleep(2)
            except Exception as e:
                failed.append("%s: read-back error %s" % (back, str(e).strip()[:160])); continue
            if not ok(got):
                failed.append("%s: read back %r, expected %s" % (back, got[:80], want))
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
    ap.add_argument("--only", help="comma-separated step labels to run (one Device Farm run of a split task)")
    ap.add_argument("--trials", type=int, help="trials per step, overriding the plan (one part of a split task)")
    ap.add_argument("--part", type=int, default=0, help="part number: seed offset 1000*K and file tag -pK")
    ap.add_argument("--budget-min", type=float, help="start no new step after this many minutes (Device Farm timeout)")
    ap.add_argument("--tag", help="B14: model tag in the file names, b13-<tag>-*")
    a = ap.parse_args(); t_start = time.time()
    out_root = Path(a.out_root).resolve()
    if ADB_IS_FAKE and out_root == (A / "results").resolve():
        raise SystemExit("the fake adb never writes to artifact/results; pass --out-root <scratch dir>")
    out = out_root / ("physical-" + time.strftime("%Y%m%d")); hm = time.strftime("%H%M")
    if a.dry_run:
        for label, argv, pre, f in steps(a.task, a.serial, out, hm, a.pilot, a.night, set() if lmdrv.AWS else {"sms"},
                                         a.allow_reboot, a.trials, a.part, a.tag):
            if not a.only or label in a.only.split(","):
                print("[%s] pre: %s\n    run: %s\n    out: %s" % (label, "; ".join(pre) or "-", " ".join(argv), f))
        print("(dry run: AWS mode excludes nothing)" if lmdrv.AWS else
              "(dry run assumes only SMS excluded; the call log is excluded too unless the test user has no_outgoing_calls)")
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
    if d.aws and a.task in ("B11", "B12"):
        runlog(out_root, "- %s %s dropped: AWS Device Farm phones are always charging and a run lasts at most 150 min "
               "(no unplugged day, no battery drain); driver files kept" % (time.strftime("%H:%M"), a.task))
        print(a.task, "dropped on AWS", flush=True)
        return 0
    missing = [k for k, v in APKS.items() if not (A / v).exists()]
    if missing:
        raise SystemExit("APKs not built: %s (run app/*/build.sh with JAVA_HOME and ANDROID_HOME)" % missing)
    if STATE.exists():
        raise SystemExit("an earlier run did not restore the phone's settings (%s); run `campaign.py --restore` first" % STATE)
    plan = steps(a.task, a.serial, out, hm, a.pilot, a.night, d.excluded, a.allow_reboot, a.trials, a.part, a.tag)
    if a.only:
        plan = [p for p in plan if p[0] in a.only.split(",")]
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
        else:
            sys.path.insert(0, str(A / "physical")); import b0_setup
            out.mkdir(parents=True, exist_ok=True)
            rec = b0_setup.setup(d, out, strict=a.task != "B0")   # B0 probes even if the fixtures fail
            if d.aws:   # the freezer is off on some Device Farm units (B1 runs 106d9bc0, 5ec38290)
                fz = d.freezer_on()
                runlog(out_root, "- %s %s freezer on %s: use_freezer %s -> %s (cached_apps_freezer was %r)%s" % (
                    time.strftime("%H:%M"), a.task, meta.get("device_instance"), fz["use_freezer_before"], fz["use_freezer_after"],
                    fz["setting_before"], "; turned on by campaign.py" if fz["turned_on"] else ""))
                env.update(P06_USE_FREEZER_BEFORE=fz["use_freezer_before"], P06_USE_FREEZER=fz["use_freezer_after"])   # into every record
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
            for k, (label, argv, pre, f) in enumerate(plan):
                if a.budget_min is not None and (time.time() - t_start) / 60 > a.budget_min:
                    runlog(out_root, "- %s %s budget: %.0f min used of %.0f; not started: %s" % (time.strftime("%H:%M"),
                           a.task, (time.time() - t_start) / 60, a.budget_min, ", ".join(p[0] for p in plan[k:])))
                    status = status or 4
                    break
                d.require_fg()
                for cmd in pre:
                    run_pre(d, cmd)
                t0 = time.time(); log = out / "logs" / ("%s-%s-%s.log" % (a.task, label, hm))
                try:
                    rc, stopped = run_step(d, argv, log, env)
                finally:
                    failed = restore(d, snap)
                status = status or rc or (1 if stopped else 0) or (3 if failed else 0)
                try:
                    plugged = d.plugged()
                except Exception as e:
                    plugged = "unknown (%s)" % type(e).__name__
                runlog(out_root, "- %s %s %s%s: `%s` on %s (`%s`, user %s, rooted=%s, plugged=%s%s); APK sha256 %s; %.1f min; exit %s; %s%s; restore %s; output `%s`, log `%s`" % (
                    time.strftime("%H:%M"), a.task, label, " (pilot)" if a.pilot else "", " ".join(Path(x).name if i < 2 else x for i, x in enumerate(argv)),
                    meta["device"], meta["fingerprint"], d.user, meta["rooted"], plugged,
                    ", instance %s, run %s" % (meta["device_instance"], meta["run_arn"]) if d.aws else "", apk, (time.time() - t0) / 60, rc,
                    counts(f), "; " + stopped if stopped else "", "ok" if not failed else "FAILED %s" % failed, Path(f).name, log.name))
                print(label, "exit", rc, counts(f), stopped or "", flush=True)
                if stopped or (failed and not d.aws):     # a rented phone is wiped after the run: keep going, failure is logged
                    break
    finally:
        failed = restore(d, snap)
        if not failed:
            STATE.unlink()
        else:
            runlog(out_root, "- %s %s final restore FAILED %s; state kept in %s; run `campaign.py --restore`" % (
                time.strftime("%H:%M"), a.task, failed, STATE.name))
            print("RESTORE FAILED %s; state kept in %s; run `campaign.py --restore`" % (failed, STATE), flush=True)
            status = status or 3
    return status


ADB_IS_FAKE = lmdrv.ADB.endswith(".py")

if __name__ == "__main__":
    sys.exit(main())

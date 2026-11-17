#!/usr/bin/env python3
"""Physical-phone campaign runner: one entry point per plan task (B0 to B12) on the single test phone.

Each task expands to driver commands. Raw output goes to artifact/results/physical-<YYYYMMDD>/ (new files only, never
overwritten); driver stdout and stderr go to physical-<YYYYMMDD>/logs/. After each command one line is appended to
artifact/results/RUNLOG.md: command, device, fingerprint, rooted, APK sha256, records written, records with error or
marked invalid, exit code. Trial counts and seeds are those of PLAN-dien-thoai-that.md section 4 and PHYS-PROTOCOL.md.

Usage: python physical/campaign.py TASK --serial SERIAL [--pilot] [--dry-run] [--night 1|2]
  TASK: setup B0 B1 B2 B3 B4 B5 B6 B7 B9 B10 B11 B12   (--pilot: 2 trials per condition, for S2)
Environment: ANDROID_HOME (finds adb); P06_SERIALS = the test phone's ro.serialno (lmdrv allowlist). Before B0 the
user must have confirmed that the phone is a test phone; the runner never touches any other serial.
"""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path

A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver")); sys.path.insert(0, str(A / "revision"))
import lmdrv

PY = sys.executable
APKS = {"client": "app/client/build/LeaseMemClient-v4.apk", "mut": "app/mut/build/LeaseMemMut.apk",
        "trig": "app/trig/build/LeaseMemTrig.apk", "assist": "app/assist/build/LeaseMemAssist.apk"}
GAPS = ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot"]   # B2
STOP_FGS = "am stopservice -n %s/.FgService" % lmdrv.CPKG
DEBOUNCE = "device_config set_sync_disabled_for_tests until_reboot; device_config put activity_manager_native_boot freeze_debounce_timeout %d"
# B11 and B12 measure the phone as deployed: undo every override earlier tasks may have left behind.
DEFAULTS = ["dumpsys battery reset", "dumpsys deviceidle unforce", "settings put global auto_time 1",
            "device_config delete activity_manager_native_boot freeze_debounce_timeout",
            "device_config set_sync_disabled_for_tests none"]


def steps(task, serial, out, hm, pilot, night):
    """[(label, argv, pre-commands, main output file)] for one task."""
    D, P, R = str(A / "driver"), str(A / "physical"), str(A / "revision")
    n = lambda full: 2 if pilot else full
    o = lambda name: str(out / ("%s-%s.jsonl" % (name, hm)))
    if task == "setup":
        return []
    if task == "B0":
        return [("probe", [PY, P + "/b0_probe.py", serial, o("b0-probe"), "--destructive"], [], o("b0-probe")),
                ("trial", [PY, D + "/e2v3_gaps.py", serial, "none", "1", "2611000", o("b0-trial-none")],
                 [DEBOUNCE % 600000], o("b0-trial-none"))]
    if task == "B1":
        tag = "pilot-" if pilot else ""
        return [("deploy-" + src, [PY, str(A / "followup/deployment.py"), serial, "--out", o("deploy-%s%s" % (tag, src)),
                                   "--source", src, "--n", str(n(20))] + (["--modes", "bg_unfrozen,fg"] if src != "contacts" else []),
                 [], o("deploy-%s%s" % (tag, src))) for src in ("contacts", "media", "calllog")]
    if task == "B2":
        return [("gap-" + g, [PY, D + "/e2v3_gaps.py", serial, g, str(n(25)), str(2611201 + i), o("gaps-" + g)],
                 [STOP_FGS, DEBOUNCE % (2000 if g == "freeze" else 600000)], o("gaps-" + g)) for i, g in enumerate(GAPS)]
    if task == "B3":
        return [("coverage", [PY, D + "/e1_coverage.py", serial, str(n(30)), "2611301", o("coverage")], [STOP_FGS], o("coverage"))]
    if task == "B4":
        f = str(out / ("stock-%s-%s.jsonl" % (serial.replace(":", "_"), hm)))
        return [("stock", [PY, R + "/run.py", serial, "stock", "--n", str(n(20)), "--out-dir", str(out), "--suffix", "-" + hm], [], f)]
    if task == "B5":
        return [("frozen", [PY, D + "/e9_frozen.py", serial, str(n(10)), "2611501", o("frozen"), "600"], [DEBOUNCE % 2000], o("frozen"))]
    if task == "B6":
        f = str(out / ("host-%s-%s.jsonl" % (serial.replace(":", "_"), hm)))
        return [("host", [PY, R + "/run.py", serial, "host", "--n", str(n(30)), "--arms", "refresh,validate,stamp,relay,memo",
                          "--out-dir", str(out), "--suffix", "-" + hm], [], f)]
    if task == "B7":
        return [("continuous", [PY, P + "/b7_continuous.py", serial, o("continuous"), "--n", str(n(30))], [], o("continuous"))]
    if task == "B9":
        return [("boundary", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), "2611901", o("boundary")], [STOP_FGS], o("boundary")),
                ("boundary-band", [PY, D + "/e3v2_boundary.py", serial, str(n(100)), "2611902", o("boundary-band"), "band"],
                 [STOP_FGS], o("boundary-band"))]
    if task == "B10":
        return [("pitfalls", [PY, D + "/e6_pitfalls.py", serial, str(n(50)), "2611001", o("pitfalls")], [STOP_FGS], o("pitfalls"))]
    if task == "B11":
        return [("statelog", [PY, P + "/b11_statelog.py", serial, o("statelog"), "--hours", "0.05" if pilot else "24"],
                 DEFAULTS, o("statelog"))]
    if task == "B12":
        order = "on,off,on,off" if night == 1 else "off,on,off,on"
        pre = str(out / ("battery-night%d-%s" % (night, hm)))
        return [("battery", [PY, P + "/b12_battery.py", serial, pre, "--order", order] + (["--max-hours", "0.2", "--sample-min", "1"] if pilot else []),
                 DEFAULTS, pre + "-samples.jsonl")]
    raise SystemExit("unknown task " + task)


def sha(rel):
    p = A / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else "missing"


def counts(path):
    try:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return "no output file"
    return "%d records, %d error, %d invalid" % (len(rows), sum("error" in r for r in rows), sum("invalid" in r for r in rows))


def runlog(line):
    p = A / "results/RUNLOG.md"; head = "## %s (physical phone)" % time.strftime("%Y-%m-%d")
    have = head in p.read_text(encoding="utf-8")
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if have else "\n" + head + "\n") + line + "\n")


def prepare(serial, out):
    """Install client v4 and mutator, grant, write fixtures (run.setup), then trig; leave the client in the background."""
    from run import setup
    c, w = setup(serial, out); d = c.d
    r = d.adb("install", "-r", "-g", str(A / APKS["trig"]))
    if "Success" not in r:
        raise RuntimeError("trig install: " + r)
    d.sh(STOP_FGS)
    return d


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("task"); ap.add_argument("--serial", required=True)
    ap.add_argument("--pilot", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--night", type=int, default=1, choices=[1, 2]); a = ap.parse_args()
    out = A / "results" / ("physical-" + time.strftime("%Y%m%d")); hm = time.strftime("%H%M")
    plan = steps(a.task, a.serial, out, hm, a.pilot, a.night)
    if a.dry_run:
        for label, argv, pre, f in plan:
            print("[%s] pre: %s\n    run: %s\n    out: %s" % (label, "; ".join(pre) or "-", " ".join(argv), f))
        return 0
    missing = [k for k, v in APKS.items() if not (A / v).exists()]
    if missing:
        raise SystemExit("APKs not built: %s (run app/*/build.sh with JAVA_HOME and ANDROID_HOME)" % missing)
    try:
        d = lmdrv.Dev(a.serial)
    except RuntimeError as e:
        raise SystemExit("ERROR: %s" % e)
    meta = d.meta(); apk = " ".join("%s %s" % (k, sha(v)) for k, v in APKS.items())
    if a.task not in ("B1", "B4", "B6", "B7"):            # those call run.setup themselves
        d = prepare(a.serial, out)
        runlog("- %s %s setup: `campaign.py %s` on %s (`%s`, rooted=%s); APK sha256 %s" % (
            time.strftime("%H:%M"), a.task, a.task, meta["device"], meta["fingerprint"], meta["rooted"], apk))
    (out / "logs").mkdir(parents=True, exist_ok=True)
    status = 0
    for label, argv, pre, f in plan:
        for cmd in pre:
            d.sh(cmd)
        t0 = time.time(); log = out / "logs" / ("%s-%s-%s.log" % (a.task, label, hm))
        with open(log, "x", encoding="utf-8") as lf:
            rc = subprocess.run(argv, stdout=lf, stderr=subprocess.STDOUT, cwd=str(A)).returncode
        status = status or rc
        try:
            plugged = d.plugged()
        except Exception as e:
            plugged = "unknown (%s)" % type(e).__name__
        runlog("- %s %s %s%s: `%s` on %s (`%s`, rooted=%s, plugged=%s); APK sha256 %s; %.1f min; exit %d; %s; output `%s`, log `%s`" % (
            time.strftime("%H:%M"), a.task, label, " (pilot)" if a.pilot else "", " ".join(Path(x).name if i < 2 else x for i, x in enumerate(argv)),
            meta["device"], meta["fingerprint"], meta["rooted"], plugged, apk, (time.time() - t0) / 60, rc, counts(f),
            Path(f).relative_to(A), log.relative_to(A)))
        print(label, "exit", rc, counts(f), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())

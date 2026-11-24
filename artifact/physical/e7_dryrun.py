#!/usr/bin/env python3
"""E7: run physical/campaign.py end to end against the fake adb, with no phone.

Personal-phone mode (default): setup, B0 to B12, restore failure cases, restore and cleanup, as in E5 to E7.
AWS mode (--aws): the fake behaves like a wiped Device Farm phone (only user 0), lmdrv runs in AWS mode
(P06_TARGET=aws, DEVICEFARM_* variables of a fake run), and the runs cover setup, B0 to B13 including split parts
(--only, --trials, --part), B11 and B12 dropped, a budget stop, the user's blocked serial (refused before any adb
call) and a device that reports that serial. It then simulates the whole Device Farm path offline: aws/package.py
builds the test package, the zip is unpacked, the test phase of aws/testspec.yml runs from the unpacked package with
the fake adb, $DEVICEFARM_LOG_DIR is zipped like a Customer Artifacts file and aws/devicefarm.py extract() copies it
into a scratch results directory.
All output goes to OUT (default <repo>/build/e7-dryrun-<time>/), never to artifact/results: campaign.py refuses the
results directory when adb is the fake, and this script also checks that no artifact/results/physical-* entry changed.
Every task runs with --pilot (unless marked) and a virtual clock (P06_FAKE_TIME). Reports per command the exit code
against the expected one, records written, and from the fake adb log: commands sent, guard violations, unanswered
commands.
Usage: python physical/e7_dryrun.py [--aws] [OUT [TASK ...]]   (TASK or #marker limits the run, e.g. B4 B6)
"""
import importlib.util, io, json, os, shutil, socket, subprocess, sys, time, zipfile
from pathlib import Path
A = Path(__file__).resolve().parents[1]
AWS = "--aws" in sys.argv
LAB = "--lab" in sys.argv          # F6 group L: a wiped lab phone on USB (P06_TARGET=lab), fake LLM
ARGS = [x for x in sys.argv[1:] if x not in ("--aws", "--lab")]
OUT = Path(ARGS[0] if ARGS else A.parent / "build" / ("e7-%sdryrun-%s" % ("aws-" if AWS else "lab-" if LAB else "", time.strftime("%H%M%S")))).resolve()
RESULTS = A / "results"
assert RESULTS.resolve() not in OUT.parents and OUT != RESULTS.resolve(), "OUT must not be inside artifact/results"
OUT.mkdir(parents=True)
ENV = dict(os.environ, ADB=str(A / "physical" / "fake_adb.py"), P06_SERIALS="FAKE0001", P06_FAKE_TIME="1",
           FAKE_ADB_STATE=str(OUT / "fake-state.json"), FAKE_ADB_LOG=str(OUT / "fake-adb-log.jsonl"),
           P06_RESTORE_STATE=str(OUT / "phone-restore-state.json"), PYTHONIOENCODING="utf-8")
if AWS:
    ENV.update(FAKE_MODE="aws", P06_TARGET="aws", DEVICEFARM_DEVICE_UDID="FAKE0001",
               DEVICEFARM_RUN_ARN="arn:aws:devicefarm:us-west-2:000000000000:run:fake-project/fake-run",
               DEVICEFARM_DEVICE_ARN="arn:aws:devicefarm:us-west-2::device:FAKEDEVICE")
if LAB:
    ENV.update(FAKE_MODE="lab", P06_TARGET="lab", P06_LLM_FAKE="1")
RUNS = [("setup", []), ("B0", ["--allow-reboot"]), ("B1", []), ("B3", []), ("B2", ["--allow-reboot"]), ("B4", []),
        ("B9", []), ("B10", []), ("B5", []), ("B12", []), ("B11", []), ("B6", []), ("B7", []),
        ("B9", ["#calls-on"]), ("B2", ["#no-reboot-consent"]), ("--restore", []),
        ("B3", ["#restore-fails-loud"]), ("--restore", ["#after-loud"]), ("B3", ["#restore-fails-silent"]),
        ("--restore", ["#after-silent"]), ("cleanup", [])]
RUNS_AWS = [("setup", []), ("B0", ["--allow-reboot"]), ("B1", []), ("B3", []),
            ("B2", ["--allow-reboot", "--only", "gap-none,gap-freeze,gap-reboot", "--part", "1", "#split"]),
            ("B2", ["--only", "gap-dozeidle,gap-kill", "--part", "2", "#split"]), ("B4", []), ("B9", []), ("B10", []),
            ("B5", ["--trials", "1", "--part", "2", "#no-pilot"]), ("B13", ["--tag", "galaxys25"]), ("B13", ["--tag", "galaxys25", "--modes", "bg_unfrozen,fg,assistant", "#modes"]), ("B13", ["#no-tag"]), ("B0", ["--tag", "galaxys25"]),
            ("B6", []), ("B7", []), ("B11", ["#dropped"]), ("B12", ["#dropped"]), ("B3", ["--budget-min", "0", "#budget"]),
            ("B3", ["#serial=RFCXA0TTMPP", "#blocked"]), ("B3", ["#fake-serialno=RFCXA0TTMPP", "#alias-blocked"]),
            ("B3", ["#runas-fails"]), ("B1FD", []), ("B1F", []), ("CRESET", []), ("FLONG", ["--tag", "galaxys25"]), ("NFLAGS", ["--tag", "galaxys25"]), ("FSCREEN", ["--tag", "galaxys25"]), ("cleanup", [])]   # B3: its setup stops on a failed fixture (B0 keeps probing)
RUNS_AWS += [("G14", []), ("G15", []), ("G16", []), ("G17", []), ("G18", []), ("G19", []), ("G20", []),
             ("G19", ["--tag", "galaxys25"]), ("L2", ["#lab-only"]), ("L1", ["--tag", "pixel8aa17"]), ("SMSDIAG", ["--tag", "pixel8aa17"])]   # L1 runs on AWS too (SMS kept)
RUNS_LAB = [("setup", []), ("L1", []), ("L2", []), ("L3", ["--allow-reboot"]), ("L3", ["#no-reboot-l3"]), ("L4", []),
            ("G14", []), ("L1", ["#personal-data"]), ("cleanup", [])]
RUNS = RUNS_AWS if AWS else RUNS_LAB if LAB else RUNS
RUNS = [r for r in RUNS if not ARGS[1:] or r[0] in ARGS[1:] or set(r[1]) & set(ARGS[1:])]
# restore failure cases (review finding 6): the fake adb makes `settings delete global lm_mode` fail with exit 1
# (loud) or exit 0 without effect (silent). The campaign must log "final restore FAILED", keep the state file and
# exit 3; the following --restore (no injection) must then succeed from that state file.
INJECT = {"#restore-fails-loud": ("FAKE_FAIL", r"^settings delete global lm_mode$"),
          "#restore-fails-silent": ("FAKE_IGNORE", r"^settings delete global lm_mode$"),
          # B0 runs 7a89358f: the mutator answered but the driver read nothing through run-as. The timeout must carry
          # run-as's own message (runas_diag) so the cause shows in the Device Farm test spec output.
          "#runas-fails": ("FAKE_RUNAS_FAIL", "package not debuggable: org.leasemem.mut"),
          # F6 lab preflight: the phone reports a contact, an SMS, a call and a photo that are not P06 fixtures
          "#personal-data": ("FAKE_PERSONAL", "1")}
EXPECT_RC = {"#restore-fails-loud": 3, "#restore-fails-silent": 3, "#budget": 4, "#blocked": 1, "#alias-blocked": 1, "#no-tag": 1,
             "#runas-fails": 1, "#lab-only": 1, "#no-reboot-l3": 1, "#personal-data": 1}
EXPECT_OUT = {"#runas-fails": "run-as diagnosis: "}    # in the campaign's own output, with the injected message
# adb commands the fake may see: none for the blocked serial, get-state and getprop for the device reporting it
EXPECT_ADB_MAX = {"#blocked": 0, "#alias-blocked": 2, "#personal-data": 10}   # lab preflight: refused before any install
EXPECT_LOG = {"#dropped": "dropped:", "#budget": "budget:"}


def physical_listing():
    return sorted(str(p.relative_to(RESULTS)) for d in RESULTS.glob("physical-*") for p in [d, *d.rglob("*")])


def fake_log(env):
    p = Path(env["FAKE_ADB_LOG"])
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def run_one(task, flags):
    env = dict(ENV)
    if task == "B12" and not AWS:     # the fake phone reports a charger until a few battery reads after the start
        st = json.loads(Path(env["FAKE_ADB_STATE"]).read_text()) if Path(env["FAKE_ADB_STATE"]).exists() else {}
        env["FAKE_UNPLUG_AT"] = str(st.get("battery_calls", 0) + 6)
    serial = "FAKE0001"
    for fl in flags:
        if fl in INJECT:
            env[INJECT[fl][0]] = INJECT[fl][1]
        if fl.startswith("#serial="):
            serial = fl.split("=", 1)[1]
        if fl.startswith("#fake-serialno="):
            env["FAKE_SERIALNO"] = fl.split("=", 1)[1]
    if "#calls-on" in flags:
        env["FAKE_RESTRICTIONS"] = "no_sms"       # calls enabled for the test user: the call log must be excluded
    argv = [sys.executable, str(A / "physical" / "campaign.py")] + ([task] if task != "--restore" else ["--restore"]) + \
           ["--serial", serial, "--out-root", str(OUT)] + [f for f in flags if not f.startswith("#")] + \
           (["--pilot"] if task[:1] in ("B", "G", "L") and "#no-pilot" not in flags else [])
    n0 = len(fake_log(env))
    rl0 = len((OUT / "RUNLOG.md").read_text(encoding="utf-8")) if (OUT / "RUNLOG.md").exists() else 0
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=str(A), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        rc, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        rc, out = "timeout", ""
    tail = out.strip().splitlines()[-4:]
    log = fake_log(env)[n0:]
    new_log = (OUT / "RUNLOG.md").read_text(encoding="utf-8")[rl0:] if (OUT / "RUNLOG.md").exists() else ""
    want = next((EXPECT_RC[fl] for fl in flags if fl in EXPECT_RC), 0)
    adb_max = next((EXPECT_ADB_MAX[fl] for fl in flags if fl in EXPECT_ADB_MAX), None)
    need = [EXPECT_LOG[fl] for fl in flags if fl in EXPECT_LOG]
    state_kept = Path(env["P06_RESTORE_STATE"]).exists()
    ok = (rc == want and (("final restore FAILED" in new_log and state_kept) if want == 3 else not state_kept)
          and (adb_max is None or len(log) <= adb_max) and all(x in new_log for x in need)
          and all(EXPECT_OUT[fl] in out and INJECT[fl][1] in out for fl in flags if fl in EXPECT_OUT))
    return {"task": task, "flags": flags, "rc": rc, "expected_rc": want, "ok": ok, "state_kept": state_kept,
            "restore_failures_logged": [l for l in new_log.splitlines() if "FAILED" in l][:3], "seconds": round(time.time() - t0, 1),
            "adb_commands": len(log), "violations": [e["argv"] for e in log if e.get("violation")][:5],
            "n_violations": sum(1 for e in log if e.get("violation")),
            "unknown": sorted({" ".join(e["argv"])[:100] for e in log if e.get("unknown")})[:8], "tail": tail}


def package_sim():
    """aws/package.py -> unzip -> test phase of aws/testspec.yml from the unpacked package -> Customer Artifacts zip ->
    aws/devicefarm.py extract() into a scratch results directory."""
    def load(name):
        spec = importlib.util.spec_from_file_location(name, A / "aws" / (name + ".py"))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod
    info = load("package").build(OUT / "pkgbuild")
    pkg, log_dir = OUT / "pkg", OUT / "devicefarm-log"
    with zipfile.ZipFile(info["zip"]) as z:
        z.extractall(pkg); members = len(z.namelist())
    spec = Path(info["testspec"]).read_text(encoding="utf-8")
    test_cmd = spec.split("  test:")[1].split("- ", 1)[1].splitlines()[0].strip()
    env = dict(ENV, DEVICEFARM_TEST_PACKAGE_PATH=pkg.as_posix(), DEVICEFARM_LOG_DIR=log_dir.as_posix(),
               P06_ARTIFACT=(pkg / "tests/P06/artifact").as_posix(), P06_OUT=(log_dir / "p06").as_posix(),
               P06_TASK="B3", P06_ARGS="--pilot", P06_RESTORE_STATE=str(OUT / "pkg-restore-state.json"))
    (log_dir / "p06").mkdir(parents=True)
    n0 = len(fake_log(env)); t0 = time.time()
    p = subprocess.run(["bash", "-c", test_cmd], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    log = fake_log(env)[n0:]
    buf = io.BytesIO()                              # zip the log dir the way Device Farm returns customer artifacts
    with zipfile.ZipFile(buf, "w") as z:
        for f in log_dir.rglob("*"):
            if f.is_file():
                z.write(f, "Host_Machine_Files/$DEVICEFARM_LOG_DIR/" + f.relative_to(log_dir).as_posix())
    df = load("devicefarm")
    written, clashes, lines = df.extract(buf.getvalue(), OUT / "fetched-results")
    n, err, inst = df.records(written)
    recs = [json.loads(l) for w in written if w.suffix == ".jsonl" for l in w.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = (p.returncode == 0 and n > 0 and err == 0 and inst == ["FAKE0001"] and not clashes
          and all(r.get("run_arn") == ENV["DEVICEFARM_RUN_ARN"] for r in recs) and not any(e.get("violation") for e in log))
    return {"task": "package-sim", "flags": ["B3 --pilot from the unpacked package"], "rc": p.returncode, "expected_rc": 0, "ok": ok,
            "seconds": round(time.time() - t0, 1), "adb_commands": len(log), "n_violations": sum(1 for e in log if e.get("violation")),
            "unknown": sorted({" ".join(e["argv"])[:100] for e in log if e.get("unknown")})[:8], "state_kept": False,
            "restore_failures_logged": [], "violations": [], "tail": (p.stdout + p.stderr).strip().splitlines()[-3:] + [
                "package %d members, test command: %s" % (members, test_cmd),
                "fetched %d files, %d records, instances %s, runlog lines %d" % (len(written), n, inst, len(lines))]}


def show(r):
    print("%-11s %-34s rc=%-4s want=%-2s %-4s %6.1fs  adb=%-5d violations=%d unknown=%d" % (
        r["task"], " ".join(r["flags"])[:34], r["rc"], r["expected_rc"], "ok" if r["ok"] else "BAD", r["seconds"],
        r["adb_commands"], r["n_violations"], len(r["unknown"])), flush=True)
    for line in r["restore_failures_logged"]:
        print("            RUNLOG: " + line[:170], flush=True)
    for line in r["tail"]:
        print("            | " + line[:160], flush=True)


def main():
    before = physical_listing(); rows = []
    for task, flags in RUNS:
        rows.append(run_one(task, flags)); show(rows[-1])
    if AWS and (not ARGS[1:] or "#package" in ARGS[1:]):
        rows.append(package_sim()); show(rows[-1])
    try:
        with socket.create_connection(("127.0.0.1", 18764), timeout=2) as s:
            s.sendall(b'{"op":"__shutdown__"}\n')
    except OSError:
        pass
    after = physical_listing()
    summary = {"out": str(OUT), "aws": AWS, "runs": rows, "results_physical_unchanged": before == after,
               "runlog": (OUT / "RUNLOG.md").read_text(encoding="utf-8") if (OUT / "RUNLOG.md").exists() else None}
    (OUT / "e7-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("artifact/results/physical-* unchanged:", before == after)
    print("summary:", OUT / "e7-summary.json")
    return 0 if before == after and all(r["ok"] and not r["n_violations"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""E7: run physical/campaign.py from setup through B0 to B12, restore and cleanup against the fake adb, with no phone.
All output goes to OUT (default <repo>/build/e7-dryrun-<time>/), never to artifact/results: campaign.py refuses the
results directory when adb is the fake, and this script also checks that no artifact/results/physical-* entry changed.
Runs every task with --pilot and a virtual clock (P06_FAKE_TIME), so waits cost almost nothing. Reports per command
the exit code, records written, and from the fake adb log: commands sent, guard violations, unanswered commands.
Usage: python physical/e7_dryrun.py [OUT [TASK ...]]   (TASK limits the run, e.g. B4 B6)
"""
import json, os, socket, subprocess, sys, time
from pathlib import Path
A = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else A.parent / "build" / ("e7-dryrun-" + time.strftime("%H%M%S"))).resolve()
RESULTS = A / "results"
assert RESULTS.resolve() not in OUT.parents and OUT != RESULTS.resolve(), "OUT must not be inside artifact/results"
OUT.mkdir(parents=True)
ENV = dict(os.environ, ADB=str(A / "physical" / "fake_adb.py"), P06_SERIALS="FAKE0001", P06_FAKE_TIME="1",
           FAKE_ADB_STATE=str(OUT / "fake-state.json"), FAKE_ADB_LOG=str(OUT / "fake-adb-log.jsonl"),
           P06_RESTORE_STATE=str(OUT / "phone-restore-state.json"), PYTHONIOENCODING="utf-8")
RUNS = [("setup", []), ("B0", ["--allow-reboot"]), ("B1", []), ("B3", []), ("B2", ["--allow-reboot"]), ("B4", []),
        ("B9", []), ("B10", []), ("B5", []), ("B12", []), ("B11", []), ("B6", []), ("B7", []),
        ("B9", ["#calls-on"]), ("B2", ["#no-reboot-consent"]), ("--restore", []), ("cleanup", [])]
RUNS = [r for r in RUNS if not sys.argv[2:] or r[0] in sys.argv[2:]]


def physical_listing():
    return sorted(str(p.relative_to(RESULTS)) for d in RESULTS.glob("physical-*") for p in [d, *d.rglob("*")])


def main():
    before = physical_listing(); rows = []
    for task, flags in RUNS:
        env = dict(ENV)
        if task == "B12":     # the fake phone reports a charger until a few battery reads after the start
            st = json.loads(Path(env["FAKE_ADB_STATE"]).read_text()) if Path(env["FAKE_ADB_STATE"]).exists() else {}
            env["FAKE_UNPLUG_AT"] = str(st.get("battery_calls", 0) + 6)
        if "#calls-on" in flags:
            env["FAKE_RESTRICTIONS"] = "no_sms"       # calls enabled for the test user: the call log must be excluded
        argv = [sys.executable, str(A / "physical" / "campaign.py")] + ([task] if task != "--restore" else ["--restore"]) + \
               ["--serial", "FAKE0001", "--out-root", str(OUT)] + [f for f in flags if not f.startswith("#")] + \
               (["--pilot"] if task.startswith("B") else [])
        n0 = sum(1 for _ in open(env["FAKE_ADB_LOG"], encoding="utf-8")) if Path(env["FAKE_ADB_LOG"]).exists() else 0
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=str(A), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
            rc, tail = p.returncode, (p.stdout + p.stderr).strip().splitlines()[-4:]
        except subprocess.TimeoutExpired:
            rc, tail = "timeout", []
        log = [json.loads(l) for l in open(env["FAKE_ADB_LOG"], encoding="utf-8")][n0:] if Path(env["FAKE_ADB_LOG"]).exists() else []
        rows.append({"task": task, "flags": flags, "rc": rc, "seconds": round(time.time() - t0, 1), "adb_commands": len(log),
                     "violations": [e["argv"] for e in log if e.get("violation")][:5],
                     "n_violations": sum(1 for e in log if e.get("violation")),
                     "unknown": sorted({" ".join(e["argv"])[:100] for e in log if e.get("unknown")})[:8], "tail": tail})
        r = rows[-1]
        print("%-9s %-24s rc=%-7s %6.1fs  adb=%-5d violations=%d unknown=%d" % (task, " ".join(flags), r["rc"], r["seconds"],
              r["adb_commands"], r["n_violations"], len(r["unknown"])), flush=True)
        for line in tail:
            print("          | " + line[:150], flush=True)
    try:
        with socket.create_connection(("127.0.0.1", 18764), timeout=2) as s:
            s.sendall(b'{"op":"__shutdown__"}\n')
    except OSError:
        pass
    after = physical_listing()
    summary = {"out": str(OUT), "runs": rows, "results_physical_unchanged": before == after,
               "runlog": (OUT / "RUNLOG.md").read_text(encoding="utf-8") if (OUT / "RUNLOG.md").exists() else None}
    (OUT / "e7-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("artifact/results/physical-* unchanged:", before == after)
    print("summary:", OUT / "e7-summary.json")
    return 0 if before == after and all(r["rc"] == 0 and not r["n_violations"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

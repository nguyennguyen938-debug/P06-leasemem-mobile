#!/usr/bin/env python3
"""Drive the P06 physical campaign on AWS Device Farm (region us-west-2), from the user's Windows host.

boto3 is imported only when a command needs AWS, from D:/aws/pylib (installed there only with the user's consent);
credentials come from D:/aws/credentials and D:/aws/config through AWS_SHARED_CREDENTIALS_FILE and AWS_CONFIG_FILE and
are never printed or written anywhere. The only AWS resources touched are the Device Farm project named PROJECT and
its uploads and runs. Uploads are the test package and test spec built by aws/package.py (and, with --app, the client
APK): P06 code, APKs and nothing else.

Commands
  devices [--text T]                 list Android phones (model, OS, availability, ARN)
  project [--create]                 find the P06 project (create it only with --create)
  upload ZIP SPEC [--app APK]        upload the package, the spec (and the app); prints their ARNs
  plan TASK [--pilot] [--allow-reboot]
                                     split a task into runs of at most 150 min from aws/estimate.py (no AWS call)
  schedule TASK --device-arn A --package-arn P --spec-arn S [--app-arn X] [--pilot] [--allow-reboot] [--cap-usd C]
                                     schedule the planned runs: refuses if more than MAX_PARALLEL runs would be active
                                     or if minutes already used plus this estimate would pass the cost cap
  watch RUN_ARN [--every S]          poll until the run completes; prints status and device minutes
  fetch RUN_ARN                      download the Customer Artifacts into artifact/results/physical-<date>/
                                     (create-only: an existing file is never overwritten, a collision is reported)
                                     and append the run's RUNLOG lines and its device minutes to results/RUNLOG.md
  cost                               device minutes and USD of every run of the project
  stop RUN_ARN                       stop a run
  --selftest                         offline check of plan splitting and artifact extraction
"""
import argparse, io, json, math, os, re, sys, time, urllib.request, zipfile
from pathlib import Path

A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate

REGION, PROJECT = "us-west-2", "P06-leasemem"
JOB_TIMEOUT_MIN, MAX_PARALLEL, USD_PER_MIN = 150, 2, estimate.USD_PER_MIN
PYLIB, AWS_DIR = "D:/aws/pylib", "D:/aws"
# Python 3 test package of a custom environment, no app under test needed: the drivers install every APK themselves.
TEST_TYPE, PKG_TYPE, SPEC_TYPE = "APPIUM_WEB_PYTHON", "APPIUM_WEB_PYTHON_TEST_PACKAGE", "APPIUM_WEB_PYTHON_TEST_SPEC"
ACTIVE = {"PENDING", "PENDING_CONCURRENCY", "PENDING_DEVICE", "PROCESSING", "SCHEDULING", "PREPARING", "RUNNING", "STOPPING"}


def client():
    os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", AWS_DIR + "/credentials")
    os.environ.setdefault("AWS_CONFIG_FILE", AWS_DIR + "/config")
    if PYLIB not in sys.path:
        sys.path.insert(0, PYLIB)
    try:
        import boto3
    except ImportError:
        raise SystemExit("boto3 is not installed in %s (it is installed only after the user agrees)" % PYLIB)
    return boto3.client("devicefarm", region_name=REGION)


def project_arn(df, create=False):
    for p in df.list_projects()["projects"]:
        if p["name"] == PROJECT:
            return p["arn"]
    if not create:
        raise SystemExit("no Device Farm project named %s; run `devicefarm.py project --create`" % PROJECT)
    return df.create_project(name=PROJECT)["project"]["arn"]


# ---------------------------------------------------------------- plan (offline)
def plan_runs(task, pilot=False, allow_reboot=False):
    """[(P06_ARGS, estimated device minutes)] for one task: one run when the trial time fits RUN_BUDGET_MIN; B2 is
    split by gap (labels packed into runs), single-step tasks (B5) by trials with --part, so parts never share seeds."""
    flags = (["--pilot"] if pilot else []) + (["--allow-reboot"] if allow_reboot else [])
    budget = ["--budget-min", str(JOB_TIMEOUT_MIN - estimate.RUN_OVERHEAD_MIN - 10)]
    T, E = estimate.estimate()
    if task not in E or pilot or E[task]["trial_min"] <= estimate.RUN_BUDGET_MIN:
        if task not in E:
            m = 10.0                                            # setup, cleanup: no trials
        elif pilot:                                             # 2 trials per step
            m = sum(min(2, n) * (s or 0) for n, s in E[task]["steps"].values()) / 60 or E[task]["trial_min"]
        else:
            m = E[task]["trial_min"]
        return [(" ".join(flags + budget), round(m + estimate.RUN_OVERHEAD_MIN, 1))]
    if task == "B2":
        gaps = [g for g in estimate.PLAN["B2"] if allow_reboot or not g.endswith("/reboot")]
        items = sorted(((s.split("/")[1], estimate.PLAN["B2"][s] * (T[s][0] or 0) / 60) for s in gaps), key=lambda x: -x[1])
        bins = []
        for g, m in items:                                     # first fit decreasing
            for b in bins:
                if b[1] + m <= estimate.RUN_BUDGET_MIN:
                    b[0].append(g); b[1] += m; break
            else:
                bins.append([[g], m])
        return [(" ".join(flags + budget + ["--only", ",".join("gap-" + g for g in b[0])]), round(b[1] + estimate.RUN_OVERHEAD_MIN, 1)) for b in bins]
    steps = estimate.PLAN[task]
    if len(steps) != 1:
        raise SystemExit("%s needs %.0f min of trials and has several steps; split it by hand with --only" % (task, E[task]["trial_min"]))
    n = next(iter(steps.values())); k = math.ceil(E[task]["trial_min"] / estimate.RUN_BUDGET_MIN); per = math.ceil(n / k)
    return [(" ".join(flags + budget + ["--trials", str(min(per, n - i * per)), "--part", str(i + 1)]),
             round(E[task]["trial_min"] * min(per, n - i * per) / n + estimate.RUN_OVERHEAD_MIN, 1)) for i in range(k)]


# ---------------------------------------------------------------- artifacts (offline part)
RUNLOG = A / "results" / "RUNLOG.md"


def extract(zip_bytes, results_root):
    """Copy p06/physical-<date>/... members of a Customer Artifacts zip into results_root/physical-<date>/... with
    create-only writes. Returns (written paths, collisions, the run's own RUNLOG lines)."""
    written, clashes, lines = [], [], []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            m = re.search(r"(?:^|/)p06/(physical-\d{8}/.+)$", name)
            if m and not name.endswith("/"):
                dst = Path(results_root) / m.group(1)
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(dst, "xb") as f:
                        f.write(z.read(name))
                    written.append(dst)
                except FileExistsError:
                    clashes.append(str(dst))
            elif re.search(r"(?:^|/)p06/RUNLOG\.md$", name):
                lines += [l for l in z.read(name).decode("utf-8", "replace").splitlines() if l.startswith("- ")]
    return written, clashes, lines


def records(paths):
    n = err = 0; inst = set()
    for p in paths:
        if p.suffix == ".jsonl":
            for l in p.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l); n += 1; err += "error" in r
                    if r.get("device_instance"):
                        inst.add(r["device_instance"])
    return n, err, sorted(inst)


def append_runlog(text):
    head = "## %s (AWS Device Farm)" % time.strftime("%Y-%m-%d")
    have = RUNLOG.exists() and head in RUNLOG.read_text(encoding="utf-8")
    with open(RUNLOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if have else "\n" + head + "\n") + text.rstrip("\n") + "\n")


def minutes(run):
    dm = run.get("deviceMinutes") or {}
    return dm.get("total") or 0.0, dm.get("metered") or 0.0


# ---------------------------------------------------------------- AWS commands
def cmd_devices(a):
    df = client(); rows = []
    for page in df.get_paginator("list_devices").paginate(filters=[{"attribute": "PLATFORM", "operator": "EQUALS", "values": ["ANDROID"]}]):
        rows += page["devices"]
    for d in sorted(rows, key=lambda d: (d["manufacturer"], d["name"], d["os"])):
        if not a.text or a.text.lower() in (d["name"] + d["model"] + d["manufacturer"]).lower():
            print("%-12s %-28s Android %-6s %-10s %s" % (d["manufacturer"], d["name"], d["os"], d.get("availability", "?"), d["arn"]))


def cmd_project(a):
    print(project_arn(client(), a.create))


def wait_upload(df, arn):
    for _ in range(120):
        u = df.get_upload(arn=arn)["upload"]
        if u["status"] in ("SUCCEEDED", "FAILED"):
            return u
        time.sleep(5)
    raise SystemExit("upload %s still %s" % (arn, u["status"]))


def cmd_upload(a):
    df = client(); proj = project_arn(df)
    for path, typ in [(a.zip, PKG_TYPE), (a.spec, SPEC_TYPE)] + ([(a.app, "ANDROID_APP")] if a.app else []):
        u = df.create_upload(projectArn=proj, name=Path(path).name, type=typ)["upload"]
        req = urllib.request.Request(u["url"], data=Path(path).read_bytes(), method="PUT", headers={"Content-Type": "application/octet-stream"})
        urllib.request.urlopen(req, timeout=600).close()
        u = wait_upload(df, u["arn"])
        print("%-34s %-9s %s %s" % (typ, u["status"], u["arn"], u.get("metadata", "")[:200] if u["status"] == "FAILED" else ""))


def project_runs(df, proj):
    runs = []
    for page in df.get_paginator("list_runs").paginate(arn=proj):
        runs += page["runs"]
    return runs


def cmd_schedule(a):
    plan = plan_runs(a.task, a.pilot, a.allow_reboot)
    est = sum(m for _, m in plan)
    print("%s: %d run(s), estimate %.0f device min (%.2f USD)" % (a.task, len(plan), est, est * USD_PER_MIN))
    df = client(); proj = project_arn(df); runs = project_runs(df, proj)
    used = sum(minutes(r)[0] for r in runs)
    active = [r for r in runs if r["status"] in ACTIVE]
    if a.cap_usd is None:
        raise SystemExit("give --cap-usd (the cost cap the user set)")
    if (used + est) * USD_PER_MIN > a.cap_usd:
        raise SystemExit("cap: %.0f min used + %.0f estimated = %.2f USD > %.2f USD; ask the user" % (used, est, (used + est) * USD_PER_MIN, a.cap_usd))
    if len(active) + len(plan) > MAX_PARALLEL:
        raise SystemExit("%d run(s) active; at most %d in parallel, schedule fewer runs now" % (len(active), MAX_PARALLEL))
    for i, (args, m) in enumerate(plan, 1):
        name = "p06-%s-%d-of-%d-%s" % (a.task, i, len(plan), time.strftime("%Y%m%d-%H%M%S"))
        req = dict(projectArn=proj, name=name,
                   test={"type": TEST_TYPE, "testPackageArn": a.package_arn, "testSpecArn": a.spec_arn},
                   deviceSelectionConfiguration={"filters": [{"attribute": "ARN", "operator": "IN", "values": [a.device_arn]}], "maxDevices": 1},
                   executionConfiguration={"jobTimeoutMinutes": JOB_TIMEOUT_MIN, "videoCapture": False},
                   configuration={"environmentVariables": [{"name": "P06_TASK", "value": a.task}, {"name": "P06_ARGS", "value": args}]})
        if a.app_arn:
            req["appArn"] = a.app_arn
        run = df.schedule_run(**req)["run"]
        append_runlog("- %s AWS schedule %s run %d/%d `%s`: %s on device %s, estimate %.0f min; package %s, spec %s" % (
            time.strftime("%H:%M"), a.task, i, len(plan), args, run["arn"], a.device_arn, m, a.package_arn, a.spec_arn))
        print(run["arn"])


def cmd_watch(a):
    df = client()
    while True:
        r = df.get_run(arn=a.run_arn)["run"]; tot, met = minutes(r)
        print("%s %-10s %-8s device min %.1f (metered %.1f)" % (time.strftime("%H:%M"), r["status"], r.get("result", ""), tot, met), flush=True)
        if r["status"] == "COMPLETED":
            return
        time.sleep(a.every)


def cmd_fetch(a):
    df = client(); r = df.get_run(arn=a.run_arn)["run"]
    if r["status"] != "COMPLETED":
        raise SystemExit("run is %s; fetch after it completes" % r["status"])
    written, clashes, lines = [], [], []
    for page in df.get_paginator("list_artifacts").paginate(arn=a.run_arn, type="FILE"):
        for art in page["artifacts"]:
            if art["type"] == "CUSTOMER_ARTIFACT":
                with urllib.request.urlopen(art["url"], timeout=600) as f:
                    w, c, l = extract(f.read(), A / "results")
                written += w; clashes += c; lines += l
    n, err, inst = records(written); tot, met = minutes(r)
    append_runlog("- %s AWS fetch %s: %s %s, %.1f device min (metered %.1f, %.2f USD); %d files, %d records, %d with error, "
                  "instances %s; collisions %s" % (time.strftime("%H:%M"), a.run_arn, r["status"], r.get("result", ""), tot, met,
                                                   tot * USD_PER_MIN, len(written), n, err, inst, clashes or "none"))
    for l in lines:
        append_runlog("  " + l)
    print("%d files, %d records, %.1f device min, collisions %d" % (len(written), n, tot, len(clashes)))


def cmd_cost(a):
    df = client(); runs = project_runs(df, project_arn(df)); tot = sum(minutes(r)[0] for r in runs)
    for r in runs:
        print("%-50s %-10s %6.1f min" % (r["name"], r["status"], minutes(r)[0]))
    print("total %.1f device min, %.2f USD at %.2f/min" % (tot, tot * USD_PER_MIN, USD_PER_MIN))


def cmd_stop(a):
    print(client().stop_run(arn=a.run_arn)["run"]["status"])


def selftest():
    p = plan_runs("B2", allow_reboot=True)
    assert len(p) >= 2 and all(m <= JOB_TIMEOUT_MIN for _, m in p), p
    gaps = sorted(g for args, _ in p for g in args.split("--only ")[1].split(","))
    assert gaps == sorted("gap-" + s.split("/")[1] for s in estimate.PLAN["B2"]), gaps
    assert not any("gap-reboot" in args for args, _ in plan_runs("B2"))
    b5 = plan_runs("B5")
    assert [x.split("--part ")[1] for x, _ in b5] == [str(i) for i in range(1, len(b5) + 1)] and len(b5) >= 2, b5
    assert sum(int(x.split("--trials ")[1].split()[0]) for x, _ in b5) == 10
    assert len(plan_runs("B1", pilot=True)) == 1
    t = A.parent / "build" / ("devicefarm-selftest-" + time.strftime("%Y%m%d-%H%M%S"))   # repo build/, never the system temp
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/physical-20261120/gaps-none-1200.jsonl",
                   json.dumps({"trial": 0, "device_instance": "U1", "run_arn": "arn:x"}) + "\n")
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/physical-20261120/logs/B2-gap-none-1200.log", "ok")
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/RUNLOG.md", "## x\n- 12:00 B2 gap-none: ...\n")
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/other.txt", "not ours")
    w, c, l = extract(buf.getvalue(), t)
    assert len(w) == 2 and not c and l == ["- 12:00 B2 gap-none: ..."], (w, c, l)
    assert records(w) == (1, 0, ["U1"])
    w2, c2, _ = extract(buf.getvalue(), t)        # a second fetch never overwrites
    assert not w2 and len(c2) == 2, (w2, c2)
    print("devicefarm selftest ok")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("devices"); s.add_argument("--text"); s.set_defaults(f=cmd_devices)
    s = sp.add_parser("project"); s.add_argument("--create", action="store_true"); s.set_defaults(f=cmd_project)
    s = sp.add_parser("upload"); s.add_argument("zip"); s.add_argument("spec"); s.add_argument("--app"); s.set_defaults(f=cmd_upload)
    s = sp.add_parser("plan"); s.add_argument("task"); s.add_argument("--pilot", action="store_true"); s.add_argument("--allow-reboot", action="store_true")
    s.set_defaults(f=lambda a: [print("%-90s ~%.0f min" % (x, m)) for x, m in plan_runs(a.task, a.pilot, a.allow_reboot)])
    s = sp.add_parser("schedule"); s.add_argument("task"); s.add_argument("--device-arn", required=True); s.add_argument("--package-arn", required=True)
    s.add_argument("--spec-arn", required=True); s.add_argument("--app-arn"); s.add_argument("--pilot", action="store_true")
    s.add_argument("--allow-reboot", action="store_true"); s.add_argument("--cap-usd", type=float); s.set_defaults(f=cmd_schedule)
    s = sp.add_parser("watch"); s.add_argument("run_arn"); s.add_argument("--every", type=int, default=60); s.set_defaults(f=cmd_watch)
    s = sp.add_parser("fetch"); s.add_argument("run_arn"); s.set_defaults(f=cmd_fetch)
    s = sp.add_parser("cost"); s.set_defaults(f=cmd_cost)
    s = sp.add_parser("stop"); s.add_argument("run_arn"); s.set_defaults(f=cmd_stop)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Drive the P06 physical campaign on AWS Device Farm from the user's Windows host, through the AWS CLI only.

Rules (CLAUDE.md of the project): every AWS call is `aws devicefarm <op> ... --profile devicefarm --region us-west-2`
(the profile has root rights, so no other AWS service is ever called, no SDK, no `aws configure`, no credentials
printed or copied); files go up and down through the presigned URLs that `aws devicefarm` returns (standard urllib).
A request is passed as `--cli-input-json`, so its member names are the Device Farm API names. If the CLI reports an
expired login, the command stops and asks the user to run `aws login --profile devicefarm --region us-west-2`.

Minutes: the P06 cap is CAP_MIN = 300 device minutes in total. artifact/results/aws-minutes.jsonl (append-only) gets
one "scheduled" line per run (its execution timeout) and one "final" line with Device Farm's deviceMinutes (total,
metered, unmetered). A run counts with its final total, or with its timeout while it has no final line. `run`
refuses a run if used + reserved + its timeout > CAP_MIN. The timeout is set close to the estimate (at most 150 min).
Every run is watched: when it errors, is interrupted (Ctrl-C), overruns its timeout, or the runner ends before it
completes, `stop-run` is called at once and the status is read back (STOPPING or COMPLETED).

Commands
  devices [--text T]                 list Android phones (model, OS, availability, ARN)
  upload FILE TYPE [FILE TYPE ...]   create-upload, PUT through the presigned URL, wait for SUCCEEDED or FAILED
  plan TASK [--pilot] [--allow-reboot]
                                     split a task into runs of at most 150 min from aws/estimate.py (no AWS call)
  run TASK --device D --app-arn A --package-arn P --spec-arn S [--timeout M] [--pilot] [--allow-reboot]
          [--args "..."]             schedule one run, watch it, stop it if needed, record minutes, fetch
  watch RUN_ARN [--timeout M]        watch a run (stops it on Ctrl-C, error or overrun) and record its minutes
  fetch RUN_ARN                      Customer Artifacts into artifact/results/physical-<date>/ (create-only)
  minutes                            the minute ledger: used, reserved by open runs, left under the cap
  stop RUN_ARN                       stop-run and read the status back
  --selftest                         offline check of plan splitting, timeouts and artifact extraction
Devices: pixel8 (main), pixel9 (backup), s25 (B13), or a device ARN.
"""
import argparse, io, json, math, os, re, subprocess, sys, time, urllib.request, zipfile
from pathlib import Path

A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate

AWS_CLI = os.environ.get("P06_AWS_CLI", "C:/Program Files/Amazon/AWSCLIV2/aws")   # tests point this at aws/fake_aws.py
PROFILE, REGION = "devicefarm", "us-west-2"
PROJECT_ARN = "arn:aws:devicefarm:us-west-2:478825889366:project:83e7e695-4f56-4afc-bca4-cb04dea963ec"
DEVICES = {"pixel8": "arn:aws:devicefarm:us-west-2::device:DE5BD47FF3BD42C3A14BF7A6EFB1BFE7",    # Pixel 8, Android 15
           "pixel9": "arn:aws:devicefarm:us-west-2::device:BCDA2B2CE0B54ABEA1F8B34A54A2752C",    # Pixel 9, Android 15
           "s25": "arn:aws:devicefarm:us-west-2::device:69977E819F314BD481F194580E8EFC16"}       # Galaxy S25, B13
MAX_TIMEOUT, CAP_MIN, MAX_PARALLEL, USD_PER_MIN = 150, 300.0, 2, estimate.USD_PER_MIN
# Python custom environment with the client APK as the app under test; the drivers also install every APK themselves
TEST_TYPE, PKG_TYPE, SPEC_TYPE, APP_TYPE = "APPIUM_PYTHON", "APPIUM_PYTHON_TEST_PACKAGE", "APPIUM_PYTHON_TEST_SPEC", "ANDROID_APP"
ACTIVE = {"PENDING", "PENDING_CONCURRENCY", "PENDING_DEVICE", "PROCESSING", "SCHEDULING", "PREPARING", "RUNNING", "STOPPING"}
RESULTS = Path(os.environ.get("P06_DF_RESULTS") or A / "results")       # tests point this at a scratch directory
LEDGER = RESULTS / "aws-minutes.jsonl"
RUNLOG = RESULTS / "RUNLOG.md"
EXPIRED = re.compile(r"expired|ExpiredToken|aws login|Unable to locate credentials|InvalidClientTokenId|SSO session", re.I)


class AwsError(RuntimeError):
    pass


def aws(op, **req):
    """One `aws devicefarm <op>` call; req is the API request (camelCase members). Returns the parsed JSON."""
    exe = [sys.executable, AWS_CLI] if AWS_CLI.endswith(".py") else [AWS_CLI]
    argv = exe + ["devicefarm", op] + (["--cli-input-json", json.dumps(req)] if req else []) + \
        ["--profile", PROFILE, "--region", REGION, "--output", "json"]
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        if EXPIRED.search(err):
            raise SystemExit("AWS login expired or missing: the user runs `aws login --profile devicefarm --region us-west-2`; "
                             "nothing else was done")
        raise AwsError("aws devicefarm %s failed: %s" % (op, err[:400]))
    return json.loads(p.stdout) if p.stdout.strip() else {}


# ---------------------------------------------------------------- minute ledger (append-only)
def ledger():
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()] if LEDGER.exists() else []


def ledger_add(rec):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(dict(rec, t=time.strftime("%Y-%m-%dT%H:%M:%S"))) + "\n")


def minutes_used():
    """(final device minutes, minutes reserved by runs without a final line = their timeout)."""
    rows = ledger(); final = {r["run_arn"]: r for r in rows if r.get("kind") == "final"}
    used = sum((r.get("device_minutes") or {}).get("total") or 0.0 for r in final.values())
    reserved = sum(r["timeout_min"] for r in rows if r.get("kind") == "scheduled" and r["run_arn"] not in final)
    return used, reserved


# ---------------------------------------------------------------- plan (offline)
def plan_runs(task, pilot=False, allow_reboot=False):
    """[(P06_ARGS, estimated device minutes)] for one task: one run when the trial time fits RUN_BUDGET_MIN; B2 is
    split by gap (labels packed into runs), single-step tasks (B5) by trials with --part, so parts never share seeds."""
    flags = (["--pilot"] if pilot else []) + (["--allow-reboot"] if allow_reboot else [])
    T, E = estimate.estimate()
    if task not in E or pilot or E[task]["trial_min"] <= estimate.RUN_BUDGET_MIN:
        if task not in E:
            m = 10.0                                            # setup, cleanup: no trials
        elif pilot:                                             # 2 trials per step
            m = sum(min(2, n) * (s or 0) for n, s in E[task]["steps"].values()) / 60 or E[task]["trial_min"]
        else:
            m = E[task]["trial_min"]
        return [(" ".join(flags), round(m + estimate.RUN_OVERHEAD_MIN, 1))]
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
        return [(" ".join(flags + ["--only", ",".join("gap-" + g for g in b[0])]), round(b[1] + estimate.RUN_OVERHEAD_MIN, 1)) for b in bins]
    steps = estimate.PLAN[task]
    if len(steps) != 1:
        raise SystemExit("%s needs %.0f min of trials and has several steps; split it by hand with --only" % (task, E[task]["trial_min"]))
    n = next(iter(steps.values())); k = math.ceil(E[task]["trial_min"] / estimate.RUN_BUDGET_MIN); per = math.ceil(n / k)
    return [(" ".join(flags + ["--trials", str(min(per, n - i * per)), "--part", str(i + 1)]),
             round(E[task]["trial_min"] * min(per, n - i * per) / n + estimate.RUN_OVERHEAD_MIN, 1)) for i in range(k)]


def timeout_for(est_min):
    """Execution timeout close to the estimate: 20 % and 3 min of slack, at most MAX_TIMEOUT."""
    return int(min(MAX_TIMEOUT, math.ceil(est_min * 1.2 + 3)))


# ---------------------------------------------------------------- artifacts (offline part)
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
    RUNLOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNLOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if have else "\n" + head + "\n") + text.rstrip("\n") + "\n")


def dm(run):
    d = run.get("deviceMinutes") or {}
    return {"total": d.get("total") or 0.0, "metered": d.get("metered") or 0.0, "unmetered": d.get("unmetered") or 0.0}


# ---------------------------------------------------------------- AWS commands
def cmd_devices(a):
    for d in sorted(aws("list-devices", filters=[{"attribute": "PLATFORM", "operator": "EQUALS", "values": ["ANDROID"]}])["devices"],
                    key=lambda d: (d["manufacturer"], d["name"], d["os"])):
        if not a.text or a.text.lower() in (d["name"] + d["model"] + d["manufacturer"]).lower():
            print("%-12s %-28s Android %-6s %-10s %s" % (d["manufacturer"], d["name"], d["os"], d.get("availability", "?"), d["arn"]))


def upload(path, typ):
    u = aws("create-upload", projectArn=PROJECT_ARN, name=Path(path).name, type=typ)["upload"]
    req = urllib.request.Request(u["url"], data=Path(path).read_bytes(), method="PUT", headers={"Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=600).close()
    for _ in range(120):
        u = aws("get-upload", arn=u["arn"])["upload"]
        if u["status"] in ("SUCCEEDED", "FAILED"):
            return u
        time.sleep(5)
    raise SystemExit("upload %s still %s after 10 min" % (u["arn"], u["status"]))


def cmd_upload(a):
    for path, typ in zip(a.items[0::2], a.items[1::2]):
        u = upload(path, typ)
        print("%-28s %-9s %s %s" % (typ, u["status"], u["arn"], (u.get("metadata") or "")[:300] if u["status"] == "FAILED" else ""), flush=True)
        append_runlog("- %s AWS upload `%s` as %s: %s %s (0 device min)" % (time.strftime("%H:%M"), Path(path).name, typ, u["status"], u["arn"]))


def stop_and_check(run_arn, why):
    """stop-run at once, then read the status back; returns it (STOPPING or COMPLETED expected)."""
    try:
        aws("stop-run", arn=run_arn)
    except AwsError as e:                       # a run that already completed cannot be stopped
        print("stop-run:", str(e)[:200], flush=True)
    st = aws("get-run", arn=run_arn)["run"]["status"]
    append_runlog("- %s AWS stop %s (%s): status %s" % (time.strftime("%H:%M"), run_arn, why, st))
    print("stopped (%s): status %s" % (why, st), flush=True)
    return st


def watch(run_arn, timeout_min, every=30):
    """Poll until COMPLETED. On an errored result or an overrun of timeout + 10 min: stop-run at once. Ctrl-C
    propagates to the caller, which stops the run."""
    t0 = time.time(); stopped = False
    while True:
        r = aws("get-run", arn=run_arn)["run"]; d = dm(r)
        print("%s %-10s %-8s device min %.1f" % (time.strftime("%H:%M"), r["status"], r.get("result", ""), d["total"]), flush=True)
        if r["status"] == "COMPLETED":
            return r
        if not stopped and (r.get("result") in ("ERRORED", "FAILED", "STOPPED") or (time.time() - t0) / 60 > timeout_min + 10):
            stop_and_check(run_arn, "result %s" % r.get("result") if r.get("result") in ("ERRORED", "FAILED", "STOPPED")
                           else "overran %d min" % timeout_min)
            stopped = True
        time.sleep(every)


def record_final(run_arn, r, task=None):
    d = dm(r); ledger_add({"kind": "final", "run_arn": run_arn, "task": task, "status": r["status"], "result": r.get("result"),
                           "device_minutes": d})
    used, reserved = minutes_used()
    append_runlog("- %s AWS minutes %s: total %.2f, metered %.2f, unmetered %.2f device min; P06 used %.1f of %.0f" % (
        time.strftime("%H:%M"), run_arn, d["total"], d["metered"], d["unmetered"], used, CAP_MIN))
    print("device minutes %.2f (metered %.2f, unmetered %.2f); P06 used %.1f of %.0f" % (d["total"], d["metered"], d["unmetered"], used, CAP_MIN), flush=True)


def fetch(run_arn):
    written, clashes, lines = [], [], []
    for art in aws("list-artifacts", arn=run_arn, type="FILE")["artifacts"]:
        if art["type"] == "CUSTOMER_ARTIFACT":
            with urllib.request.urlopen(art["url"], timeout=600) as f:
                w, c, l = extract(f.read(), RESULTS)
            written += w; clashes += c; lines += l
    n, err, inst = records(written)
    append_runlog("- %s AWS fetch %s: %d files, %d records, %d with error, instances %s; collisions %s" % (
        time.strftime("%H:%M"), run_arn, len(written), n, err, inst, clashes or "none"))
    for l in lines:
        append_runlog("  " + l)
    print("%d files, %d records, collisions %d" % (len(written), n, len(clashes)), flush=True)


def cmd_run(a):
    device = DEVICES.get(a.device, a.device)
    if a.args:
        args, est = a.args, a.estimate or 30.0
    else:
        plan = plan_runs(a.task, a.pilot, a.allow_reboot)
        if len(plan) != 1:
            raise SystemExit("%s needs %d runs; give each one's --args from `plan`" % (a.task, len(plan)))
        args, est = plan[0]
        est = a.estimate or est
    timeout = a.timeout or timeout_for(est)
    if timeout > MAX_TIMEOUT:
        raise SystemExit("timeout %d > %d min" % (timeout, MAX_TIMEOUT))
    used, reserved = minutes_used()
    if used + reserved + timeout > CAP_MIN:
        raise SystemExit("cap: %.1f used + %.0f reserved + %d timeout > %.0f device min; ask the user" % (used, reserved, timeout, CAP_MIN))
    active = [r for r in aws("list-runs", arn=PROJECT_ARN)["runs"] if r["status"] in ACTIVE]
    if len(active) >= MAX_PARALLEL:
        raise SystemExit("%d run(s) already active; at most %d in parallel" % (len(active), MAX_PARALLEL))
    p06_args = " ".join(x for x in [args, "--budget-min %d" % max(1, timeout - 4)] if x)
    name = "p06-%s-%s" % (a.task, time.strftime("%Y%m%d-%H%M%S"))
    run = aws("schedule-run", projectArn=PROJECT_ARN, appArn=a.app_arn, name=name,
              test={"type": TEST_TYPE, "testPackageArn": a.package_arn, "testSpecArn": a.spec_arn},
              deviceSelectionConfiguration={"filters": [{"attribute": "ARN", "operator": "IN", "values": [device]}], "maxDevices": 1},
              executionConfiguration={"jobTimeoutMinutes": timeout, "videoCapture": False},
              configuration={"environmentVariables": [{"name": "P06_TASK", "value": a.task}, {"name": "P06_ARGS", "value": p06_args}]})["run"]
    ledger_add({"kind": "scheduled", "run_arn": run["arn"], "task": a.task, "args": p06_args, "device_arn": device,
                "timeout_min": timeout, "estimate_min": est})
    append_runlog("- %s AWS schedule %s `%s` on %s: %s; timeout %d min (estimate %.0f); P06 used %.1f + reserved %.0f of %.0f" % (
        time.strftime("%H:%M"), a.task, p06_args, device, run["arn"], timeout, est, used, reserved + timeout, CAP_MIN))
    print("scheduled", run["arn"], "timeout", timeout, flush=True)
    r = None
    try:
        r = watch(run["arn"], timeout)
    finally:          # Ctrl-C or any error of the runner: the run is stopped before the runner exits
        if r is None:
            stop_and_check(run["arn"], "runner ended before completion")
            r = aws("get-run", arn=run["arn"])["run"]
        record_final(run["arn"], r, a.task)
    fetch(run["arn"])


def cmd_watch(a):
    r = None
    try:
        r = watch(a.run_arn, a.timeout)
    finally:
        if r is None:
            stop_and_check(a.run_arn, "watcher ended before completion")
            r = aws("get-run", arn=a.run_arn)["run"]
        record_final(a.run_arn, r)


def cmd_minutes(a):
    used, reserved = minutes_used()
    print("P06 device minutes: used %.1f, reserved by open runs %.0f, left %.1f of %.0f" % (used, reserved, CAP_MIN - used - reserved, CAP_MIN))


def selftest():
    p = plan_runs("B2", allow_reboot=True)
    assert len(p) >= 2 and all(m <= MAX_TIMEOUT for _, m in p), p
    gaps = sorted(g for args, _ in p for g in args.split("--only ")[1].split(","))
    assert gaps == sorted("gap-" + s.split("/")[1] for s in estimate.PLAN["B2"]), gaps
    assert not any("gap-reboot" in args for args, _ in plan_runs("B2"))
    b5 = plan_runs("B5")
    assert [x.split("--part ")[1] for x, _ in b5] == [str(i) for i in range(1, len(b5) + 1)] and len(b5) >= 2, b5
    assert sum(int(x.split("--trials ")[1].split()[0]) for x, _ in b5) == 10
    assert len(plan_runs("B1", pilot=True)) == 1
    assert timeout_for(15) == 21 and timeout_for(400) == MAX_TIMEOUT
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
    s = sp.add_parser("upload"); s.add_argument("items", nargs="+", help="FILE TYPE pairs"); s.set_defaults(f=cmd_upload)
    s = sp.add_parser("plan"); s.add_argument("task"); s.add_argument("--pilot", action="store_true"); s.add_argument("--allow-reboot", action="store_true")
    # printed as ready-to-paste run options; --args needs the "=" form because its value starts with "--"
    s.set_defaults(f=lambda a: [print('--args="%s" --estimate %.0f   (timeout %d)' % (x, m, timeout_for(m))) for x, m in plan_runs(a.task, a.pilot, a.allow_reboot)])
    s = sp.add_parser("run"); s.add_argument("task"); s.add_argument("--device", default="pixel8"); s.add_argument("--app-arn", required=True)
    s.add_argument("--package-arn", required=True); s.add_argument("--spec-arn", required=True); s.add_argument("--timeout", type=int)
    s.add_argument("--estimate", type=float); s.add_argument("--args", default="", help='P06_ARGS of one planned run, written --args="..." (see plan)')
    s.add_argument("--pilot", action="store_true"); s.add_argument("--allow-reboot", action="store_true"); s.set_defaults(f=cmd_run)
    s = sp.add_parser("watch"); s.add_argument("run_arn"); s.add_argument("--timeout", type=int, default=MAX_TIMEOUT); s.set_defaults(f=cmd_watch)
    s = sp.add_parser("fetch"); s.add_argument("run_arn"); s.set_defaults(f=lambda a: fetch(a.run_arn))
    s = sp.add_parser("minutes"); s.set_defaults(f=cmd_minutes)
    s = sp.add_parser("stop"); s.add_argument("run_arn"); s.set_defaults(f=lambda a: stop_and_check(a.run_arn, "requested"))
    a = ap.parse_args()
    if a.cmd == "upload" and len(a.items) % 2:
        raise SystemExit("upload takes FILE TYPE pairs")
    a.f(a)


if __name__ == "__main__":
    main()

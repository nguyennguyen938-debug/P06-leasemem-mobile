#!/usr/bin/env python3
"""Offline test of aws/devicefarm.py against aws/fake_aws.py: no network, no AWS account, no credentials.

The fake checks every `aws devicefarm` call (service, profile, region, argument shape) and validates every request
against the Device Farm service model of the installed botocore (offline data files). Covered: upload of the three
files through presigned PUT URLs (a local HTTP server), a full B0 run (schedule-run with P06_TASK/P06_ARGS, Pixel 8 by
ARN, a 25-min timeout; watch until COMPLETED; minutes into the ledger and RUNLOG; fetch of the Customer Artifacts),
the parallel-run limit counting only P06 runs, the free-minute check before a run (another project's run and a remote
access session held against the free minutes; no schedule-run when too few are left), the free-minute check after a
run (metered minutes taken from the free minutes pass; metered minutes billed to the card stop every open P06 run),
stop-run on Ctrl-C and on an errored result, and the expired-login stop. Everything is written under build/devicefarm-test-<stamp>/.
Run: python aws/test_devicefarm.py
"""
import http.server, io, json, os, sys, threading, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = HERE.parents[1] / "build" / ("devicefarm-test-" + time.strftime("%Y%m%d-%H%M%S"))   # repo build/, never the system temp
TMP.mkdir(parents=True)
puts = []


class Put(http.server.BaseHTTPRequestHandler):
    def do_PUT(self):
        puts.append((self.path, len(self.rfile.read(int(self.headers["Content-Length"])))))
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Put)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(P06_AWS_CLI=str(HERE / "fake_aws.py"), P06_DF_RESULTS=str(TMP / "results"),
                  FAKE_AWS_STATE=str(TMP / "fake-aws-state.json"), FAKE_AWS_LOG=str(TMP / "fake-aws-log.jsonl"),
                  FAKE_AWS_PUT_URL="http://127.0.0.1:%d/put/" % srv.server_address[1])
sys.path.insert(0, str(HERE))
import devicefarm as df
import types
from fake_aws import OTHER
df.time.sleep = lambda s: None                     # no waiting between polls
calls = lambda: [json.loads(l) for l in open(os.environ["FAKE_AWS_LOG"], encoding="utf-8")] if Path(os.environ["FAKE_AWS_LOG"]).exists() else []
state = lambda: json.loads(Path(os.environ["FAKE_AWS_STATE"]).read_text())
save = lambda st: Path(os.environ["FAKE_AWS_STATE"]).write_text(json.dumps(st))
scheduled = lambda n0: [c for c in calls()[n0:] if c.get("op") == "ScheduleRun"]
ARGS = dict(task="B0", device="pixel8", app_arn="arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/app",
            package_arn="arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/pkg",
            spec_arn="arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/spec",
            timeout=25, estimate=15.0, args="--allow-reboot", pilot=False, allow_reboot=False)


def ns(**kw):
    return types.SimpleNamespace(**dict(ARGS, **kw))


def artifact_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/physical-20261120/b0-probe-1200.jsonl",
                   json.dumps({"probe": "identity", "ok": True, "device_instance": "UNIT1", "run_arn": "arn:run"}) + "\n")
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/RUNLOG.md", "- 12:00 B0 probe: ...\n")
    p = TMP / "customer-artifacts.zip"; p.write_bytes(buf.getvalue()); return p


def test_upload():
    files = []
    for name in ("LeaseMemClient-v4.apk", "p06-tests.zip", "p06-testspec.yml"):
        (TMP / name).write_bytes(b"x" * 10); files.append(TMP / name)
    df.cmd_upload(types.SimpleNamespace(items=[str(files[0]), df.APP_TYPE, str(files[1]), df.PKG_TYPE, str(files[2]), df.SPEC_TYPE]))
    ups = [c for c in calls() if c.get("op") == "CreateUpload"]
    assert [c["request"]["type"] for c in ups] == ["ANDROID_APP", "APPIUM_PYTHON_TEST_PACKAGE", "APPIUM_PYTHON_TEST_SPEC"], ups
    assert len(puts) == 3 and all(n == 10 for _, n in puts), puts
    assert df.RUNLOG.read_text(encoding="utf-8").count("AWS upload") == 3


def test_run_b0():
    os.environ["FAKE_AWS_ARTIFACT_ZIP"] = str(artifact_zip())
    os.environ["FAKE_AWS_METERED"] = "2.5"            # metered minutes come out of the free minutes: no alarm
    df.cmd_run(ns())
    del os.environ["FAKE_AWS_METERED"]
    sched = [c for c in calls() if c.get("op") == "ScheduleRun"]
    assert len(sched) == 1 and not sched[0]["model_errors"], sched
    r = sched[0]["request"]
    assert r["executionConfiguration"]["jobTimeoutMinutes"] == 25 and r["test"]["type"] == "APPIUM_PYTHON"
    assert r["deviceSelectionConfiguration"]["filters"][0]["values"] == [df.DEVICES["pixel8"]]
    env = {e["name"]: e["value"] for e in r["configuration"]["environmentVariables"]}
    assert env == {"P06_TASK": "B0", "P06_ARGS": "--allow-reboot --budget-min 21"}, env
    led = df.ledger()
    assert [x["kind"] for x in led] == ["scheduled", "final", "free"] and led[1]["device_minutes"]["total"] == 7.5, led
    assert led[0]["free_before"] == 988.37 and led[2]["after"] == 985.87 and led[2]["ok"], led
    assert df.minutes_used() == (7.5, 0)
    assert (df.RESULTS / "physical-20261120" / "b0-probe-1200.jsonl").exists()
    log = df.RUNLOG.read_text(encoding="utf-8")
    assert "AWS schedule B0" in log and "AWS minutes" in log and "AWS fetch" in log and "  - 12:00 B0 probe" in log, log


def test_parallel_and_free():
    n0 = len(calls()); st = state()
    # MAX_PARALLEL P06 runs and two runs of another project in the shared Device Farm project: only the P06 ones count
    seeded = {"arn:%s" % k: {"name": k, "status": "RUNNING", "polls": 0, "stopped": False}
              for k in ["p06-B%d-x" % i for i in range(df.MAX_PARALLEL)] + ["pilot-p01-a36-android15", "pilot-p01-x"]}
    st["runs"].update(seeded); save(st)
    try:
        df.cmd_run(ns()); raise AssertionError("parallel limit not enforced")
    except SystemExit as e:
        assert str(e).startswith("%d P06 run(s) already active" % df.MAX_PARALLEL), e
    st["runs"] = {k: v for k, v in st["runs"].items() if k not in seeded}
    # too few free minutes: another project's open run (60 min) and a remote access session (150) count against them
    st.update(free=200.0, other_runs={"arn:other-1": {"name": "pilot-p01-a36-android15", "status": "RUNNING", "jobTimeoutMinutes": 60}},
              sessions={OTHER: [{"arn": "arn:ras-1", "name": "ras", "status": "RUNNING"}]}); save(st)
    try:
        df.cmd_run(ns()); raise AssertionError("free-minute check not enforced")
    except SystemExit as e:
        assert str(e).startswith("free minutes: 200.00 remaining - 210 that 2 open run(s)") and "not sent" in str(e), e
    assert not scheduled(n0)
    st["sessions"] = {}; save(st)                     # 200 - 60 - 25 = 115 >= 30: the run goes
    df.cmd_run(ns())
    assert len(scheduled(n0)) == 1 and df.ledger()[-1] == dict(df.ledger()[-1], kind="free", ok=True)
    st = state(); st.pop("other_runs"); st["free"] = 988.37; save(st)


def test_card():
    """Metered minutes billed to the card (free minutes do not drop): every open P06 run is stopped."""
    st = state(); st["runs"]["arn:p06-B3-open"] = {"name": "p06-B3-open", "status": "RUNNING", "polls": 0, "stopped": False}; save(st)
    os.environ.update(FAKE_AWS_METERED="5", FAKE_AWS_CARD="1")
    try:
        df.cmd_run(ns()); raise AssertionError("card billing not detected")
    except SystemExit as e:
        assert "tell the Orchestrator now" in str(e), e
    finally:
        del os.environ["FAKE_AWS_METERED"], os.environ["FAKE_AWS_CARD"]
    assert "arn:p06-B3-open" in [c["request"]["arn"] for c in calls() if c.get("op") == "StopRun"]
    last = df.ledger()[-1]
    assert last["kind"] == "free" and not last["ok"] and last["metered"] == 5.0, last
    assert "MISMATCH, every open P06 run stopped" in df.RUNLOG.read_text(encoding="utf-8")


def test_stop_paths():
    real_watch = df.watch

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    df.watch = interrupted
    try:
        df.cmd_run(ns()); raise AssertionError("Ctrl-C not propagated")
    except KeyboardInterrupt:
        pass
    df.watch = real_watch
    last = [c for c in calls() if c.get("op") in ("ScheduleRun", "StopRun")][-2:]
    assert [c["op"] for c in last] == ["ScheduleRun", "StopRun"], last
    assert df.ledger()[-1]["kind"] == "final" and df.ledger()[-1]["status"] in ("STOPPING", "COMPLETED")
    os.environ["FAKE_AWS_RESULT"] = "ERRORED"
    df.cmd_run(ns())
    del os.environ["FAKE_AWS_RESULT"]
    assert [c["op"] for c in calls() if c.get("op") in ("ScheduleRun", "StopRun")][-2:] == ["ScheduleRun", "StopRun"]


def test_expired():
    os.environ["FAKE_AWS_EXPIRED"] = "1"
    try:
        df.cmd_minutes(None); df.cmd_devices(types.SimpleNamespace(text=None)); raise AssertionError("expiry not detected")
    except SystemExit as e:
        assert "aws login --profile devicefarm --region us-west-2" in str(e), e
    finally:
        del os.environ["FAKE_AWS_EXPIRED"]


if __name__ == "__main__":
    for t in (test_upload, test_run_b0, test_parallel_and_free, test_card, test_stop_paths, test_expired):
        t(); print("ok", t.__name__, flush=True)
    bad = [c for c in calls() if c.get("model_errors")]
    assert not bad, bad
    assert all(c["argv"][-6:] == ["--profile", "devicefarm", "--region", "us-west-2", "--output", "json"] for c in calls() if "op" in c)
    print("devicefarm CLI tests ok: %d aws devicefarm calls, 0 model errors (botocore Device Farm model); %s" % (len(calls()), TMP))

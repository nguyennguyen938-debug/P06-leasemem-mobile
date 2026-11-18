#!/usr/bin/env python3
"""Offline test of aws/devicefarm.py with botocore's Stubber: no network, no AWS account, no real credentials.

Every request devicefarm.py builds (ListProjects, ListRuns, CreateUpload, GetUpload, ScheduleRun, GetRun,
ListArtifacts) is validated against the Device Farm API model shipped with botocore, and every response it reads
comes from the stub. Covers: upload (presigned PUT), schedule (two B2 runs with P06_TASK/P06_ARGS, 150-min timeout,
one device by ARN), the cost-cap and parallel-run refusals, fetch (Customer Artifacts zip into a scratch results
directory, RUNLOG lines, device minutes) and cost. RUNLOG and results go to build/devicefarm-test-<stamp>/ only.
Run: PYTHONPATH=D:/aws/pylib python aws/test_devicefarm.py
"""
import io, json, os, sys, time, types, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TMP = HERE.parents[1] / "build" / ("devicefarm-test-" + time.strftime("%Y%m%d-%H%M%S"))   # repo build/, never the system temp
TMP.mkdir(parents=True)
# never read the user's real AWS files: point both at paths that do not exist
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = str(TMP / "no-credentials")
os.environ["AWS_CONFIG_FILE"] = str(TMP / "no-config")
import boto3
from botocore.stub import Stubber, ANY
import devicefarm as df

PROJ = "arn:aws:devicefarm:us-west-2:123456789012:project:00000000-0000-0000-0000-000000000001"
DEV = "arn:aws:devicefarm:us-west-2::device:0123456789ABCDEF0123456789ABCDEF"
PKG = "arn:aws:devicefarm:us-west-2:123456789012:upload:00000000-0000-0000-0000-000000000001/package"
SPEC = "arn:aws:devicefarm:us-west-2:123456789012:upload:00000000-0000-0000-0000-000000000001/spec"
RUN = "arn:aws:devicefarm:us-west-2:123456789012:run:00000000-0000-0000-0000-000000000001/run1"

client = boto3.client("devicefarm", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing")
stub = Stubber(client)
df.client = lambda: client
df.RUNLOG = TMP / "RUNLOG.md"
df.A = TMP / "artifact"
puts, downloads = [], {}


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def fake_urlopen(req, timeout=None):
    if hasattr(req, "get_method"):
        puts.append((req.full_url, req.get_method(), len(req.data))); return Resp(b"")
    return Resp(downloads[req])


df.urllib.request.urlopen = fake_urlopen
projects = {"projects": [{"name": "P06-leasemem", "arn": PROJ}]}


def run_cmd(f, **kw):
    f(types.SimpleNamespace(**kw))


def test_upload():
    zp, sp = TMP / "p.zip", TMP / "s.yml"; zp.write_bytes(b"PK"); sp.write_text("version: 0.1\n")
    stub.add_response("list_projects", projects, {})
    for name, typ, arn in [("p.zip", df.PKG_TYPE, PKG), ("s.yml", df.SPEC_TYPE, SPEC)]:
        stub.add_response("create_upload", {"upload": {"arn": arn, "url": "https://example.invalid/" + name, "status": "INITIALIZED"}},
                          {"projectArn": PROJ, "name": name, "type": typ})
        stub.add_response("get_upload", {"upload": {"arn": arn, "status": "SUCCEEDED"}}, {"arn": arn})
    with stub:
        run_cmd(df.cmd_upload, zip=str(zp), spec=str(sp), app=None)
    assert [p[1] for p in puts] == ["PUT", "PUT"], puts


def test_schedule():
    plan = df.plan_runs("B2", allow_reboot=True)
    stub.add_response("list_projects", projects, {})
    stub.add_response("list_runs", {"runs": []}, {"arn": PROJ})
    for args, _ in plan:
        stub.add_response("schedule_run", {"run": {"arn": RUN, "name": "x", "status": "SCHEDULING"}}, {
            "projectArn": PROJ, "name": ANY,
            "test": {"type": df.TEST_TYPE, "testPackageArn": PKG, "testSpecArn": SPEC},
            "deviceSelectionConfiguration": {"filters": [{"attribute": "ARN", "operator": "IN", "values": [DEV]}], "maxDevices": 1},
            "executionConfiguration": {"jobTimeoutMinutes": 150, "videoCapture": False},
            "configuration": {"environmentVariables": [{"name": "P06_TASK", "value": "B2"}, {"name": "P06_ARGS", "value": args}]}})
    with stub:
        run_cmd(df.cmd_schedule, task="B2", pilot=False, allow_reboot=True, cap_usd=300.0, device_arn=DEV,
                package_arn=PKG, spec_arn=SPEC, app_arn=None)
    log = df.RUNLOG.read_text(encoding="utf-8")
    assert log.count("AWS schedule B2") == len(plan) == 2 and RUN in log, log


def test_refusals():
    used = {"runs": [{"arn": RUN, "name": "old", "status": "COMPLETED", "deviceMinutes": {"total": 1800.0, "metered": 1800.0}}]}
    stub.add_response("list_projects", projects, {}); stub.add_response("list_runs", used, {"arn": PROJ})
    try:
        with stub:
            run_cmd(df.cmd_schedule, task="B3", pilot=False, allow_reboot=False, cap_usd=300.0, device_arn=DEV,
                    package_arn=PKG, spec_arn=SPEC, app_arn=None)
        raise AssertionError("cap not enforced")
    except SystemExit as e:
        assert "cap" in str(e), e
    busy = {"runs": [{"arn": RUN, "name": "a", "status": "RUNNING"}, {"arn": RUN, "name": "b", "status": "PENDING"}]}
    stub.add_response("list_projects", projects, {}); stub.add_response("list_runs", busy, {"arn": PROJ})
    try:
        with stub:
            run_cmd(df.cmd_schedule, task="B3", pilot=False, allow_reboot=False, cap_usd=300.0, device_arn=DEV,
                    package_arn=PKG, spec_arn=SPEC, app_arn=None)
        raise AssertionError("parallel limit not enforced")
    except SystemExit as e:
        assert "parallel" in str(e), e


def test_fetch_and_cost():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/physical-20261120/coverage-1200.jsonl",
                   json.dumps({"trial": 0, "device_instance": "R5XYZ", "run_arn": RUN}) + "\n")
        z.writestr("Host_Machine_Files/$DEVICEFARM_LOG_DIR/p06/RUNLOG.md", "- 12:00 B3 coverage: ...\n")
    downloads["https://example.invalid/customer.zip"] = buf.getvalue()
    done = {"run": {"arn": RUN, "status": "COMPLETED", "result": "PASSED", "deviceMinutes": {"total": 21.5, "metered": 21.5}}}
    stub.add_response("get_run", done, {"arn": RUN})
    stub.add_response("list_artifacts", {"artifacts": [{"arn": RUN + "/a1", "name": "Customer Artifacts", "type": "CUSTOMER_ARTIFACT",
                                                        "extension": "zip", "url": "https://example.invalid/customer.zip"}]},
                      {"arn": RUN, "type": "FILE"})
    with stub:
        run_cmd(df.cmd_fetch, run_arn=RUN)
    out = df.A / "results" / "physical-20261120" / "coverage-1200.jsonl"
    assert out.exists(), out
    log = df.RUNLOG.read_text(encoding="utf-8")
    assert "AWS fetch" in log and "21.5 device min" in log and "R5XYZ" in log and "  - 12:00 B3 coverage" in log, log
    stub.add_response("list_projects", projects, {})
    stub.add_response("list_runs", {"runs": [{"arn": RUN, "name": "p06-B3", "status": "COMPLETED", "deviceMinutes": {"total": 21.5}}]}, {"arn": PROJ})
    with stub:
        run_cmd(df.cmd_cost)


if __name__ == "__main__":
    for t in (test_upload, test_schedule, test_refusals, test_fetch_and_cost):
        t()
    stub.assert_no_pending_responses()
    print("devicefarm stub tests ok (requests validated against botocore's Device Farm model; temp dir %s)" % TMP)

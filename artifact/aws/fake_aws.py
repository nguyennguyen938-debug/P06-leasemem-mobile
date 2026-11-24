#!/usr/bin/env python3
"""A fake `aws` CLI for aws/test_devicefarm.py: no network, no credentials.

It accepts only `aws devicefarm <op> [--cli-input-json J] --profile devicefarm --region us-west-2 --output json`
(any other service, profile, region or argument shape exits 2), checks the request of every call against the
Device Farm service model shipped with botocore (member names, required members, types, enum values; the model is
read from the installed botocore data files, offline), and answers with fixed responses that keep a little state in
$FAKE_AWS_STATE: uploads (served through a local PUT URL given by $FAKE_AWS_PUT_URL), runs that complete after two
get-run polls, stop-run, list-artifacts pointing at $FAKE_AWS_ARTIFACT_ZIP, the account's free minutes (state "free",
988.37 at first; a completing run takes its metered minutes from them), a second project ("other_runs") and remote
access sessions ("sessions"). Every call is appended to $FAKE_AWS_LOG.
Fault injection: FAKE_AWS_EXPIRED=1 answers like an expired login; FAKE_AWS_RESULT=ERRORED makes a running run report
that result; FAKE_AWS_UPLOAD_FAIL=<name suffix> makes that upload FAILED; FAKE_AWS_METERED=<min> is the metered part
of a completed run (default 0); FAKE_AWS_CARD=1 bills those metered minutes to the card (free minutes do not drop).
"""
import gzip, json, os, re, sys, time
from pathlib import Path

PROJECT = "arn:aws:devicefarm:us-west-2:478825889366:project:83e7e695-4f56-4afc-bca4-cb04dea963ec"
OTHER = "arn:aws:devicefarm:us-west-2:478825889366:project:00000000-0000-0000-0000-0000000000p1"   # another project
STATE = Path(os.environ.get("FAKE_AWS_STATE", "fake-aws-state.json"))
LOG = Path(os.environ.get("FAKE_AWS_LOG", "fake-aws-log.jsonl"))


def model():
    for root in [os.environ.get("FAKE_AWS_BOTOCORE", ""), "D:/aws/pylib"] + sys.path:
        for p in sorted(Path(root or ".").glob("botocore/data/devicefarm/*/service-2.json*")):
            raw = p.read_bytes()
            return json.loads(gzip.decompress(raw) if p.suffix == ".gz" else raw)
    raise SystemExit("botocore Device Farm model not found")


def check(M, shape, value, path, errs):
    s = M["shapes"][shape]; t = s["type"]
    if t == "structure":
        if not isinstance(value, dict):
            return errs.append("%s: expected an object" % path)
        for k in value:
            if k not in s["members"]:
                errs.append("%s: unknown member %r" % (path, k))
        for k in s.get("required", []):
            if k not in value:
                errs.append("%s: missing required %r" % (path, k))
        for k, v in value.items():
            if k in s["members"]:
                check(M, s["members"][k]["shape"], v, path + "." + k, errs)
    elif t == "list":
        if not isinstance(value, list):
            return errs.append("%s: expected a list" % path)
        for i, v in enumerate(value):
            check(M, s["member"]["shape"], v, "%s[%d]" % (path, i), errs)
    elif t == "map":
        if not isinstance(value, dict):
            return errs.append("%s: expected a map" % path)
        for k, v in value.items():
            check(M, s["value"]["shape"], v, "%s[%s]" % (path, k), errs)
    elif t == "string":
        if not isinstance(value, str):
            errs.append("%s: expected a string" % path)
        elif "enum" in s and value not in s["enum"]:
            errs.append("%s: %r not in %s" % (path, value, s["enum"]))
    elif t in ("integer", "long"):
        if not isinstance(value, int) or isinstance(value, bool):
            errs.append("%s: expected an integer" % path)
    elif t == "boolean":
        if not isinstance(value, bool):
            errs.append("%s: expected a boolean" % path)
    elif t in ("double", "float"):
        if not isinstance(value, (int, float)):
            errs.append("%s: expected a number" % path)


def load():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"uploads": {}, "runs": {}, "n": 0}


def answer(op, req, st):
    if op == "ListDevices":
        return {"devices": [{"arn": "arn:aws:devicefarm:us-west-2::device:DE5BD47FF3BD42C3A14BF7A6EFB1BFE7", "name": "Google Pixel 8",
                             "manufacturer": "Google", "model": "Google Pixel 8", "os": "15", "availability": "HIGHLY_AVAILABLE"}]}
    if op == "CreateUpload":
        st["n"] += 1; arn = "arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/%08d" % st["n"]
        st["uploads"][arn] = {"name": req["name"], "type": req["type"]}
        return {"upload": {"arn": arn, "name": req["name"], "type": req["type"], "status": "INITIALIZED",
                           "url": os.environ.get("FAKE_AWS_PUT_URL", "http://127.0.0.1:9/") + "%08d" % st["n"]}}
    if op == "GetUpload":
        u = st["uploads"][req["arn"]]; bad = os.environ.get("FAKE_AWS_UPLOAD_FAIL")
        failed = bool(bad) and u["name"].endswith(bad)
        return {"upload": {"arn": req["arn"], "name": u["name"], "type": u["type"], "status": "FAILED" if failed else "SUCCEEDED",
                           **({"metadata": '{"errorMessage": "fake validation failure"}'} if failed else {})}}
    if op == "GetAccountSettings":
        return {"accountSettings": {"awsAccountNumber": "478825889366", "maxJobTimeoutMinutes": 150,
                                    "trialMinutes": {"total": 1000.0, "remaining": st.get("free", 988.37)}}}
    if op == "ListProjects":
        return {"projects": [{"arn": PROJECT, "name": "mobisys-thu-nghiem"}, {"arn": OTHER, "name": "other"}]}
    if op == "ListRemoteAccessSessions":
        return {"remoteAccessSessions": st.get("sessions", {}).get(req["arn"], [])}
    if op == "ListRuns":
        runs = st["runs"] if req["arn"] == PROJECT else st.get("other_runs", {})
        return {"runs": [dict(arn=a, **r) for a, r in runs.items()]}
    if op == "ScheduleRun":
        st["n"] += 1; arn = "arn:aws:devicefarm:us-west-2:478825889366:run:83e7e695-4f56-4afc-bca4-cb04dea963ec/%08d" % st["n"]
        st["runs"][arn] = {"name": req["name"], "status": "SCHEDULING", "polls": 0, "stopped": False,
                           "jobTimeoutMinutes": req["executionConfiguration"]["jobTimeoutMinutes"], "totalJobs": 1}
        return {"run": {"arn": arn, "name": req["name"], "status": "SCHEDULING"}}
    if op == "GetRun":
        r = st["runs"][req["arn"]]; r["polls"] += 1
        if r["stopped"]:
            r.update(status="COMPLETED" if r["polls"] > 1 else "STOPPING", result="STOPPED")
        elif r["polls"] >= 3:
            r.update(status="COMPLETED", result="PASSED")
        else:
            r.update(status="RUNNING", result=os.environ.get("FAKE_AWS_RESULT", "PENDING"))
        out = {k: v for k, v in r.items() if k in ("name", "status", "result")}
        if r["status"] == "COMPLETED":
            m = float(os.environ.get("FAKE_AWS_METERED", "0"))
            out["deviceMinutes"] = {"total": 7.5, "metered": m, "unmetered": 7.5 - m}
            if not r.get("billed"):          # metered minutes come out of the free minutes, unless billed to the card
                r["billed"] = True
                if not os.environ.get("FAKE_AWS_CARD"):
                    st["free"] = round(st.get("free", 988.37) - m, 2)
        return {"run": dict(arn=req["arn"], **out)}
    if op == "StopRun":
        r = st["runs"][req["arn"]]
        if r["status"] == "COMPLETED":
            raise ValueError("An error occurred (ArgumentException) when calling the StopRun operation: run already completed")
        r.update(stopped=True, polls=0, status="STOPPING")
        return {"run": {"arn": req["arn"], "status": "STOPPING"}}
    if op == "ListArtifacts":
        z = os.environ.get("FAKE_AWS_ARTIFACT_ZIP")
        return {"artifacts": [{"arn": req["arn"] + "/00000/00000/00000", "name": "Customer Artifacts", "type": "CUSTOMER_ARTIFACT",
                               "extension": "zip", "url": Path(z).resolve().as_uri()}] if z else []}
    raise ValueError("operation %s is not answered by the fake" % op)


def main(argv):
    entry = {"argv": argv}
    try:
        if argv[:1] != ["devicefarm"] or len(argv) < 2:
            raise SystemExit(("only `aws devicefarm ...` is allowed", 2))
        op_cli, rest = argv[1], argv[2:]
        tail = ["--profile", os.environ.get("FAKE_AWS_PROFILE", "devicefarm"), "--region", "us-west-2", "--output", "json"]
        if rest[-6:] != tail:
            raise SystemExit(("every call must end with %s" % " ".join(tail), 2))
        rest = rest[:-6]
        req = {}
        if rest:
            if rest[0] != "--cli-input-json" or len(rest) != 2:
                raise SystemExit(("only --cli-input-json is expected, got %s" % rest, 2))
            req = json.loads(rest[1])
        if os.environ.get("FAKE_AWS_EXPIRED"):
            raise SystemExit(("Error when retrieving token from sso: Token has expired and refresh failed", 255))
        M = model(); op = "".join(w.capitalize() for w in op_cli.split("-"))
        if op not in M["operations"]:
            raise SystemExit(("unknown devicefarm operation %s" % op_cli, 252))
        errs = []
        check(M, M["operations"][op]["input"]["shape"], req, op, errs) if "input" in M["operations"][op] else None
        entry.update(op=op, request=req, model_errors=errs)
        if errs:
            raise SystemExit(("Parameter validation failed:\n" + "\n".join(errs), 252))
        st = load(); out = answer(op, req, st); STATE.write_text(json.dumps(st), encoding="utf-8")
        entry["ok"] = True
        print(json.dumps(out))
        return 0
    except SystemExit as e:
        msg, code = e.code if isinstance(e.code, tuple) else (str(e.code), 1)
        entry.update(error=msg, rc=code); sys.stderr.write("\n" + msg + "\n")
        return code
    except ValueError as e:
        entry.update(error=str(e), rc=254); sys.stderr.write("\n" + str(e) + "\n")
        return 254
    finally:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

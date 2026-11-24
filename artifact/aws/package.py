#!/usr/bin/env python3
"""Build the Device Farm test package from an allowlist only: P06 driver code and the four APKs. Nothing else of the
host goes to AWS (no results, no logs, no credentials); the fixtures are written on the phone by the mutator app.

Layout (Python 3 test package of a custom test environment): requirements.txt (pytest only, for Device Farm's
package check; the drivers use only the standard library and the test spec installs nothing), tests/test_p06_entry.py (Device Farm requires a test* file; it only checks that the entry point
is present) and tests/P06/artifact/<path> for every allowlisted file, so the drivers' relative imports and
paths work unchanged on the test host. Writes build/aws/p06-tests-<stamp>.zip, a manifest with the SHA-256 of every
member, and a copy of testspec.yml; refuses to build if a member looks like an AWS key or is not allowlisted.
Usage: python aws/package.py [OUT_DIR]
"""
import hashlib, json, re, sys, time, zipfile
from pathlib import Path

A = Path(__file__).resolve().parents[1]
FILES = ["driver/lmdrv.py", "driver/e1_coverage.py", "driver/e2v3_gaps.py", "driver/e3v2_boundary.py",
         "driver/e6_pitfalls.py", "driver/e9_frozen.py", "revision/run.py", "followup/deployment.py",
         "physical/campaign.py", "physical/b0_setup.py", "physical/b0_probe.py", "physical/b7_continuous.py", "physical/contacts_reset.py", "physical/freeze_long.py", "physical/notify_flags.py", "physical/freeze_screenoff.py", "physical/phys_cost.py", "physical/phys_fgcost.py", "physical/phys_host.py", "physical/sms_diag.py",
         "app/client/build/LeaseMemClient-v4.apk", "app/mut/build/LeaseMemMut.apk", "app/trig/build/LeaseMemTrig.apk",
         "app/assist/build/LeaseMemAssist.apk"]
# Device Farm rejects a Python test package without a file named test* in tests/
# (APPIUM_PYTHON_TEST_PACKAGE_INVALID_TEST_FILE_NAME, seen on the first upload, 2026-11-18). P06's test spec runs
# physical/campaign.py directly; this file only names the entry point and is never run by the spec.
ENTRY_TEST = ('''"""Device Farm needs a test* file in tests/. P06's test spec runs tests/P06/artifact/physical/campaign.py."""
import os


def test_campaign_entry_point_present():
    assert os.path.isfile(os.path.join(os.path.dirname(__file__), "P06", "artifact", "physical", "campaign.py"))
''')
# Device Farm also rejects an empty requirements.txt (APPIUM_PYTHON_TEST_PACKAGE_REQUIREMENTS_TXT_FILE_EMPTY, second
# upload) and checks the pytest version and that pytest collects the tests. The drivers need only the standard library
# and P06's test spec installs nothing from this file.
REQUIREMENTS = "pytest==8.3.4\n"
SECRET = re.compile(rb"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key|aws_session_token", re.I)


def build(out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zpath, manifest = out_dir / ("p06-tests-%s.zip" % stamp), {}
    missing = [f for f in FILES if not (A / f).is_file()]
    if missing:
        raise SystemExit("missing (build the APKs first): %s" % missing)
    for f in FILES:
        b = (A / f).read_bytes()
        if not f.endswith(".apk") and SECRET.search(b):
            raise SystemExit("%s contains something that looks like an AWS credential; not packaged" % f)
        manifest["tests/P06/artifact/" + f] = hashlib.sha256(b).hexdigest()
    with zipfile.ZipFile(zpath, "x", zipfile.ZIP_DEFLATED) as z:
        z.writestr("requirements.txt", REQUIREMENTS)
        z.writestr("tests/test_p06_entry.py", ENTRY_TEST)
        for f in FILES:
            z.write(A / f, "tests/P06/artifact/" + f)
    with zipfile.ZipFile(zpath) as z:      # the zip holds exactly the allowlist
        names = set(z.namelist())
    extra = {"requirements.txt", "tests/test_p06_entry.py"}
    assert names == set(manifest) | extra, names ^ (set(manifest) | extra)
    spec = out_dir / ("p06-testspec-%s.yml" % stamp)
    spec.write_bytes((A / "aws/testspec.yml").read_bytes())
    info = {"zip": str(zpath), "zip_sha256": hashlib.sha256(zpath.read_bytes()).hexdigest(), "testspec": str(spec),
            "testspec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(), "members": manifest}
    (out_dir / ("p06-tests-%s.manifest.json" % stamp)).write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


if __name__ == "__main__":
    info = build(sys.argv[1] if len(sys.argv) > 1 else A.parent / "build" / "aws")
    print(json.dumps({k: v for k, v in info.items() if k != "members"}, indent=1))
    print("%d members" % len(info["members"]))

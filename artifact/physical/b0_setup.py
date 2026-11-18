#!/usr/bin/env python3
"""B0 setup on the personal phone: check and prepare the test user only. Never creates, switches or edits a user.

1. The Android user named "P06 Test" exists, is not user 0, is in the foreground and unlocked (lmdrv.Dev checks).
2. Its user restrictions are read on the phone (only its own block of `dumpsys user` leaves the phone): with
   no_outgoing_calls its call history is its own and the call log is used; SMS is never used (lmdrv).
3. The test user must hold no data that P06 did not write: for each provider the drivers touch, count rows in the
   test user that are not P06 fixtures (projection _id only; only the count is kept). Any such row stops the setup,
   because it would mean the user is in use or shares data with the owner.
4. Install the P06 apps with --user, grant permissions and appops in that user, write each app's excluded sources,
   and write the fixtures through the mutator app inside the test user.
On AWS Device Farm (lmdrv AWS mode) the phone is wiped before every run: the same steps run in user 0 with every
source, the foreign-row counts are recorded but do not stop the setup, and nothing personal exists on the device.
Usage (through campaign.py): b0_setup.py SERIAL OUT_DIR
"""
import hashlib, json, random, re, sys, time
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver"))
import lmdrv

APPS = [(lmdrv.CPKG, "app/client/build/LeaseMemClient-v4.apk"), (lmdrv.MPKG, "app/mut/build/LeaseMemMut.apk"),
        (lmdrv.TPKG, "app/trig/build/LeaseMemTrig.apk"), (lmdrv.APKG, "app/assist/build/LeaseMemAssist.apk")]
# rows in the test user that are not P06 fixtures (fixtures: names "LM ...", numbers +1666..., Pictures/lm/)
FOREIGN = {"contacts": ("content://com.android.contacts/raw_contacts", "deleted=0 AND display_name NOT LIKE 'LM %'"),
           "calllog": ("content://call_log/calls", "number NOT LIKE '+1666%'"),
           "calendar": ("content://com.android.calendar/events", "title NOT LIKE 'LM %'"),
           "media": ("content://media/external/images/media", "relative_path IS NOT 'Pictures/lm/'")}


def foreign_rows(d):
    """source -> number of rows in the test user that P06 did not write (None if the query failed)."""
    out = {}
    for src, (uri, where) in FOREIGN.items():
        if src in d.excluded:
            continue
        txt = d.sh(d.u('content query --uri %s --projection _id --where "%s"' % (uri, where)), timeout=30)
        out[src] = len(re.findall(r"^Row: ", txt, re.M)) if ("Row:" in txt or "No result" in txt) else None
    return out


def setup(d, out_dir, strict=True):
    """strict=False (B0): a failed fixture step is recorded, not raised, so the probes still run and say what fails."""
    w = lmdrv.World(d, random.Random(20261119))
    rec = {**d.meta(), "kind": "setup", "t": time.time(), "restrictions": sorted(d.restrictions)}
    rec["foreign_before"] = foreign_rows(d) if not d.emulator else None
    # a personal phone's test user must be empty; a wiped rented phone (AWS) holds nothing personal, counts are kept
    if not d.aws and rec["foreign_before"] and any(v != 0 for v in rec["foreign_before"].values()):
        raise RuntimeError("the test user holds rows P06 did not write %s; stop (PHYS-PROTOCOL.md section 3)"
                           % rec["foreign_before"])
    rec["install"] = d.provision([(p, A / apk) for p, apk in APPS])
    rec["apks"] = {apk: hashlib.sha256((A / apk).read_bytes()).hexdigest() for _, apk in APPS}
    try:
        rec["fixtures"] = w.ensure_base()
    except Exception as e:
        if strict:
            raise
        rec["fixtures"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:1500])}
        print("fixtures failed, B0 continues: %s" % rec["fixtures"]["error"], flush=True)
    rec["foreign_after"] = foreign_rows(d) if not d.emulator else None
    rec["packages"] = d.sh(d.u("pm list packages org.leasemem")).split()
    with lmdrv.open_new(str(Path(out_dir) / ("setup-%s.json" % time.strftime("%H%M%S")))) as f:
        f.write(json.dumps(rec, indent=2))
    return rec


if __name__ == "__main__":
    r = setup(lmdrv.Dev(sys.argv[1]), sys.argv[2])
    print(json.dumps({k: r[k] for k in ("user_id", "excluded_sources", "foreign_before", "foreign_after", "packages")}))

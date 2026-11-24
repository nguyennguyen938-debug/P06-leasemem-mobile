#!/usr/bin/env python3
"""F6 L1 diagnosis (25/11), AWS mode with SMS kept (campaign.py SMSDIAG): why did every SMS `_id` reuse trial of run
3d940867 (Pixel 8a, Android 17) fail with an empty `content://sms` query right after the mutator's insert, although
the mutator held the SMS role? Writes and deletes rows in the SMS provider only; nothing is ever sent.

Stages, each one record (exp=sms_diag): before the role, after `cmd role add-role-holder android.app.role.SMS`, and
after `am force-stop` of the mutator (a process started before the grant). In each stage: the SMS role holders, the
mutator's app ops (`appops get`), its SMS permission lines (`dumpsys package`), one mutator insert (`mutate sms
insert`), the rows the shell sees (`content query --uri content://sms`), and one `sms_reuse` call (its `did` or its
error). The campaign's final restore gives the SMS role back to the holder it recorded before the run.
Usage: sms_diag.py SERIAL OUT.jsonl
"""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "revision"))
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
c, w = setup(serial, Path(out).parent); d = c.d
if not d.aws or "sms" in d.excluded:
    raise SystemExit("sms_diag.py needs AWS or lab mode with SMS kept (campaign.py SMSDIAG)")
M = lmdrv.MPKG


def stage(name):
    r = {**d.meta(), "serial": serial, "exp": "sms_diag", "stage": name}
    r["role_holders"] = d.sh(d.u("cmd role get-role-holders android.app.role.SMS")).strip()
    r["appops"] = [l.strip() for l in d.sh(d.u("appops get %s" % M)).splitlines() if re.search(r"SMS|MMS", l)]
    r["perms"] = [l.strip() for l in d.sh(lmdrv.DUMP_PKG % M, timeout=90).splitlines() if "SMS" in l][:12]
    try:
        r["insert"] = d.mut("mutate", "sms", "insert", extra="--es tag %d" % (int(time.time()) % 100000))
    except Exception as e:
        r["insert_error"] = repr(e)
    time.sleep(0.5)
    q = d.sh(d.u("content query --uri content://sms --projection _id:address:type:body"))
    r["shell_rows"] = q.count("Row:"); r["shell_out"] = q.strip()[:600]
    try:
        r["sms_reuse"] = d.mut("sms_reuse")
    except Exception as e:
        r["sms_reuse_error"] = repr(e)
    return r


with lmdrv.open_new(out) as f:
    put = lambda r: (f.write(json.dumps(r) + "\n"), f.flush(), print(r["stage"], r["role_holders"], r["shell_rows"],
                                                                     (r.get("sms_reuse") or {}).get("did"), (r.get("sms_reuse") or {}).get("err"), flush=True))
    put(stage("before_role"))
    add = d.sh(d.u("cmd role add-role-holder android.app.role.SMS %s 0" % M)).strip(); time.sleep(2)
    r = stage("after_role"); r["role_add_out"] = add; put(r)
    d.sh(d.u("am force-stop %s" % M)); time.sleep(1)
    put(stage("after_force_stop"))

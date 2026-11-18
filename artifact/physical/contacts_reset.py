#!/usr/bin/env python3
"""Contacts reset on a rented phone (AWS mode): the `contacts_reset` case of revision/supplement.py, with every
user-scoped command built by Dev.u() for the guard. Each trial writes the fixtures, records the client's stock
evidence for Contacts, clears the Contacts provider of user 0 (`pm clear --user 0 com.android.providers.contacts`, the
one `pm clear` the guard allows, AWS mode only), writes the fixtures again, restarts the client with its foreground
service, records the evidence again and asks the v4 client to validate c.dana. 20 trials as on each emulator
(results/revision-20261115/supplement-final-emulator-562*.jsonl).
Usage: contacts_reset.py SERIAL OUT.jsonl [N]
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "revision"))
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
c, w = setup(serial, Path(out).parent); d = c.d
if not d.aws:
    raise SystemExit("contacts_reset.py clears the Contacts provider: AWS mode only (a wiped rented phone)")
with lmdrv.open_new(out) as f:
    for i in range(n):
        r = {**d.meta(), "serial": serial, "trial": i, "case": "contacts_reset"}
        try:
            w.ensure_base()
            r["before"] = c.call("stock_evidence", source="contacts")
            r["reset_result"] = d.sh(d.u("pm clear com.android.providers.contacts")).strip()
            time.sleep(.3); w.ensure_base(); d.launch(); time.sleep(.2)
            d.sh(d.u("am start-foreground-service -n org.leasemem.client/.FgService"))
            r["after"] = c.call("stock_evidence", source="contacts")
            r["verdict"] = c.call("validate", fact="c.dana", certificate={"schema": 4})
        except Exception as e:
            r["error"] = repr(e)
        f.write(json.dumps(r) + "\n"); f.flush()
        print(i, r.get("error", "ok"), flush=True)

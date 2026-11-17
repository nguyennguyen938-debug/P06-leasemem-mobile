#!/usr/bin/env python3
"""E3 v2 (round-2 revision): validation vs. commitment with changes timed relative to the boundary check.

The client validates Dana's number at receipt, then at an absolute device time AT re-validates (mode bnd) or not
(mode obs) and performs an external effect: it inserts an outgoing call-log row carrying the number it used.
The mutator app sleeps on-device until AT+delta and then edits Dana's number, so the change can land before the
boundary check, inside the check-to-effect residual, or after the effect. delta is drawn from a mixture that
covers the whole planning window and densely the last 150 ms before / 60 ms after AT.
Usage: e3v2_boundary.py SERIAL N_BND_CHANGE SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, nb, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
BAND = len(sys.argv) > 5 and sys.argv[5] == "band"   # all boundary changes drawn in [-10, +40] ms around the check
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
LEAD = 2500
plan = [("bnd", 1)] * nb + ([] if BAND else [("obs", 1)] * max(20, nb // 4) + [("bnd", 0)] * 20 + [("obs", 0)] * 20)
rng.shuffle(plan)
with open(out, "a") as fo:
    for i, (mode, change) in enumerate(plan):
        rec = {"i": i, "fact": "c.dana", "mode": mode, "change": change, "seed": seed, "protocol": "v2", "band": BAND}
        try:
            w.ensure_base(); time.sleep(1.0)
            d.cmd("OBSERVE")
            rid = "e3v2_%d_%d" % (seed, i)
            d.sh("rm -f %s/res_%s.json" % (lmdrv.FILES, rid))
            at = d.now_ms() + LEAD
            rec["at"] = at
            d.sh("am broadcast -n %s/.Cmd --es cmd ACT --es id %s --es fact c.dana --es mode %s --el at %d" % (lmdrv.CPKG, rid, mode, at))
            if change:
                if BAND and mode == "bnd":
                    delta = rng.uniform(-10, 40)
                elif mode == "obs" or rng.random() < 0.5:
                    delta = rng.uniform(-2000, -150)
                else:
                    delta = rng.uniform(-150, 60)
                rec["delta_planned_ms"] = round(delta, 1)
                rec["mut"] = d.mut("mutate_at", "contacts", "update",
                                   extra="--es tag %d%03d --el at %d" % (int(time.time()) % 100000, i % 1000, int(at + delta)))
            res = None
            t0 = time.time()
            while time.time() - t0 < 15:
                s = d.sh("cat %s/res_%s.json 2>/dev/null" % (lmdrv.FILES, rid))
                if s.startswith("{") and "effect_end" in s:
                    res = json.loads(s); break
                time.sleep(0.2)
            rec["res"] = res
            fo.write(json.dumps(rec) + "\n"); fo.flush()
            print(i, mode, change, rec.get("delta_planned_ms"), None if res is None else res.get("stale"), flush=True)
        except Exception as e:
            rec["error"] = repr(e); fo.write(json.dumps(rec) + "\n"); fo.flush()
            print("ERR", i, repr(e), flush=True); d.launch()

#!/usr/bin/env python3
"""E3 v2 (round-2 revision): validation vs. commitment with changes timed relative to the boundary check.

The client validates Dana's number at receipt, then at an absolute device time AT re-validates (mode bnd) or not
(mode obs) and performs an external effect: it inserts an outgoing call-log row carrying the number it used.
The mutator app sleeps on-device until AT+delta and then edits Dana's number, so the change can land before the
boundary check, inside the check-to-effect residual, or after the effect. delta is drawn from a mixture that
covers the whole planning window and densely the last 150 ms before / 60 ms after AT.
Effect store: the call log where it can be written (the emulators); otherwise ("calllog" excluded, AWS Device Farm,
where call-log inserts are dropped) a Data row of the separate, non-aggregated raw contact "P06 Effect Log" (client
ACT with `--es effect contacts`). Every record carries effect_store, the effect row read back from the provider
(effect_row: number, command id, wall ms) and Dana's raw-contact VERSION before the command and after the result
(dana_version_before/after): on trials without a change they must be equal, i.e. the effect never touches Dana.
dana_number_before is Dana's phone number read from the provider just before the command.
Usage: e3v2_boundary.py SERIAL N_BND_CHANGE SEED OUT.jsonl
"""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, nb, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
BAND = len(sys.argv) > 5 and sys.argv[5] == "band"   # all boundary changes drawn in [-10, +40] ms around the check
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
LEAD = 2500
EFFECT = "contacts" if "calllog" in d.excluded else "calllog"
EFFECT_MIME = "vnd.android.cursor.item/vnd.org.leasemem.effect"


def dana_version():
    return dana_raw()[1]


def dana_raw():
    """(raw contact ids, versions) of LM Dana, comma-joined, or (None, None)."""
    o = d.sh(d.u("content query --uri content://com.android.contacts/raw_contacts --projection _id:version "
                 "--where \"display_name='LM Dana' AND deleted=0\""), timeout=30)
    rows = re.findall(r"_id=(\d+), version=(\d+)", o)
    return (",".join(r[0] for r in rows), ",".join(r[1] for r in rows)) if rows else (None, None)


def dana_number(raw_ids):
    if not raw_ids:
        return None
    o = d.sh(d.u("content query --uri content://com.android.contacts/data --projection data1 "
                 "--where \"mimetype='vnd.android.cursor.item/phone_v2' AND raw_contact_id IN (%s)\"" % raw_ids), timeout=30)
    n = re.findall(r"data1=([^,\n]*)", o)
    return ",".join(x.strip() for x in n) if n else None


def effect_row(rid):
    if EFFECT != "contacts":
        return None
    o = d.sh(d.u("content query --uri content://com.android.contacts/data --projection data1:data2:data3:raw_contact_id "
                 "--where \"mimetype='%s' AND data2='%s'\"" % (EFFECT_MIME, rid)), timeout=30)
    m = re.search(r"data1=([^,]*), data2=([^,]*), data3=([^,]*), raw_contact_id=(\S+)", o)
    return {"number": m.group(1), "id": m.group(2), "wall_ms": int(m.group(3)), "raw_contact_id": m.group(4)} if m else {"raw": o.strip()[:200]}

plan = [("bnd", 1)] * nb + ([] if BAND else [("obs", 1)] * max(20, nb // 4) + [("bnd", 0)] * 20 + [("obs", 0)] * 20)
rng.shuffle(plan)
with lmdrv.open_new(out) as fo:
    for i, (mode, change) in enumerate(plan):
        rec = {**d.meta(), "i": i, "fact": "c.dana", "mode": mode, "change": change, "seed": seed, "protocol": "v2", "band": BAND,
               "effect_store": EFFECT}
        try:
            w.ensure_base(); time.sleep(1.0)
            d.cmd("OBSERVE")
            rid = "e3v2_%d_%d" % (seed, i)
            d.rm(lmdrv.CPKG, "files/res_%s.json" % rid)
            ids, rec["dana_version_before"] = dana_raw()
            rec["dana_number_before"] = dana_number(ids)
            at = d.now_ms() + LEAD
            rec["at"] = at
            d.sh(d.u("am broadcast -n %s/.Cmd --es cmd ACT --es id %s --es fact c.dana --es mode %s --el at %d --es effect %s"
                     % (lmdrv.CPKG, rid, mode, at, EFFECT)))
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
                s = d.cat(lmdrv.CPKG, "files/res_%s.json" % rid)
                if s.startswith("{") and "effect_end" in s:
                    res = json.loads(s); break
                time.sleep(0.2)
            rec["res"] = res
            rec["effect_row"] = effect_row(rid)
            rec["dana_version_after"] = dana_version()
            rec["dana_version_unchanged"] = rec["dana_version_before"] == rec["dana_version_after"]
            fo.write(json.dumps(rec) + "\n"); fo.flush()
            print(i, mode, change, rec.get("delta_planned_ms"), None if res is None else res.get("stale"),
                  "dana_version_unchanged" if rec["dana_version_unchanged"] else "dana_version_changed", flush=True)
        except Exception as e:
            rec["error"] = repr(e); fo.write(json.dumps(rec) + "\n"); fo.flush()
            print("ERR", i, repr(e), flush=True); d.launch()

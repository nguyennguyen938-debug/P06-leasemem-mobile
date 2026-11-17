#!/usr/bin/env python3
"""E12: how do validation, refresh and the action-boundary window scale with source size? (real emulator)

Grows the Contacts database (raw contacts named "LM bulk ..." so that they also enter the aggregate fact c.set)
and the MediaStore folder Pictures/lm (images "bulk_*", which enter the aggregate m.latest) step by step. At each
size it runs R decisions without any change and R decisions after one change (a Contacts edit and a MediaStore insert),
recording LeaseMem's per-source validation time (VERSION-map and timestamp adapters for Contacts), the provider
refresh time of every fact, and R action-boundary checks (ACT, mode bnd, no change).
Usage: e12_scale.py SERIAL R SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, R, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.sh("am stopservice -n %s/.FgService" % lmdrv.CPKG)
d.launch()
LEVELS = [("contacts", 0), ("contacts", 100), ("contacts", 1000), ("contacts", 5000), ("media", 1000), ("media", 10000)]
if len(sys.argv) > 5:          # resume: only these levels, e.g. "media:10000"
    LEVELS = [(x.split(":")[0], int(x.split(":")[1])) for x in sys.argv[5].split(",")]


def _count(uri, where):
    out = d.sh("content query --uri '%s' --projection _id --where \"%s\"" % (uri, where), timeout=180)
    return sum(1 for l in out.splitlines() if l.startswith("Row:"))


# rows already added by earlier (possibly interrupted) runs count towards the target
added = {"contacts": _count("content://com.android.contacts/raw_contacts", "deleted=0 AND display_name LIKE 'LM bulk%'"),
         "media": _count("content://media/external_primary/images/media", "_display_name LIKE 'bulk%'")}
print("already added", added, flush=True)


def grow(src, target):
    while added[src] < target:
        k = min(500 if src == "contacts" else 200, target - added[src])
        if src == "contacts":
            d.mut("bulk_contacts", str(k), "LM bulk%d" % added[src], timeout=120)
        else:
            d.mut("bulk_images", str(k), "bulk%d" % added[src], timeout=300)
        added[src] += k


def count(uri, where):
    out = d.sh("content query --uri '%s' --projection _id --where \"%s\"" % (uri, where))
    return sum(1 for l in out.splitlines() if l.startswith("Row:"))


with open(out, "a") as f:
    w.ensure_base()
    for src, target in LEVELS:
        grow(src, target)
        time.sleep(15)
        n_raw = count("content://com.android.contacts/raw_contacts", "deleted=0")
        n_img = count("content://media/external_primary/images/media", "relative_path='Pictures/lm/'")
        for i in range(2 * R):
            change = i % 2 == 1
            w.ensure_base(); time.sleep(1.5)
            d.cmd("OBSERVE", timeout=120)
            if change:
                w.mutate("contacts", "update"); w.mutate("media", "insert"); time.sleep(1.0)
            D = d.cmd("DECIDE", timeout=120)
            rec = {"level": "%s+%d" % (src, target), "raw_contacts": n_raw, "images": n_img, "change": change,
                   "lm_cost": {k: v for k, v in D["lm_cost"].items() if isinstance(v, dict)},
                   "lmts_contacts": (D.get("lmts_cost") or {}).get("contacts"),
                   "refresh_ns": {k: v["refresh_ns"] for k, v in D["facts"].items() if v["src"] != "derived"},
                   "lm_miss": sum(1 for v in D["facts"].values() if v["mem"] != v["truth"] and v["lm"] == "FRESH")}
            f.write(json.dumps(rec) + "\n"); f.flush()
        for i in range(R):
            w.ensure_base(); time.sleep(1.0)
            d.cmd("OBSERVE", timeout=120)
            rid = "sc%d_%d_%d" % (seed, target, i)
            d.sh("rm -f %s/res_%s.json" % (lmdrv.FILES, rid))
            at = d.now_ms() + 1500
            d.sh("am broadcast -n %s/.Cmd --es cmd ACT --es id %s --es fact c.dana --es mode bnd --el at %d" % (lmdrv.CPKG, rid, at))
            res = None; t0 = time.time()
            while time.time() - t0 < 60:
                s = d.sh("cat %s/res_%s.json 2>/dev/null" % (lmdrv.FILES, rid))
                if s.startswith("{") and "effect_end" in s:
                    res = json.loads(s); break
                time.sleep(0.2)
            if res:
                f.write(json.dumps({"level": "%s+%d" % (src, target), "raw_contacts": n_raw, "images": n_img, "act": True,
                                    "check_ms": res["check2_end"] - res["check2_start"], "effect_ms": res["effect_end"] - res["effect_start"],
                                    "check_to_effect_ms": res["effect_end"] - res["check2_start"]}) + "\n"); f.flush()
        print("level", src, target, "raw", n_raw, "img", n_img, flush=True)

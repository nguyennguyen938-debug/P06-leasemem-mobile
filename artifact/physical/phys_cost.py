#!/usr/bin/env python3
"""G14 and G15 (F6), a rented or lab phone: per-use cost per source, and cost vs. source size. Port of driver/e12_scale.py
(emulator Tables cost and scale) to the phone rules: every user-scoped command through Dev.u(), app files through
Dev.cat/rm, the ACT effect in Contacts where the call log is excluded (as driver/e3v2_boundary.py).

  persource (G14): R rounds; each round takes, for every source the device keeps (Contacts, MediaStore, Calendar,
      Settings, files, plus SMS and call log in lab mode) and for "none", one decision: fixtures, OBSERVE, one
      mutation of that source by another app (none: no mutation), DECIDE. Records the client's StampCheck cost per
      source (lm_cost, and lmts_cost for the Contacts timestamp adapter) and the provider refresh time of every fact.
  scale (G15): as e12. Grows Contacts (raw contacts "LM bulk ...", in the aggregate c.set) and MediaStore (Pictures/lm
      "bulk*", in m.latest) level by level; at each level R decisions without a change and R after one Contacts edit
      and one MediaStore insert, then R action-boundary checks (ACT, mode bnd, no change): check-to-effect.
Usage: phys_cost.py SERIAL OUT.jsonl persource R SEED
       phys_cost.py SERIAL OUT.jsonl scale R SEED [LEVELS]   LEVELS e.g. contacts:1000,contacts:10000,media:10000
"""
import json, random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
import lmdrv

serial, out, mode, R, seed = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
LEVELS = [("contacts", 0), ("contacts", 1000), ("contacts", 5000), ("contacts", 10000), ("media", 1000), ("media", 10000)]
if len(sys.argv) > 6:
    LEVELS = [(x.split(":")[0], int(x.split(":")[1])) for x in sys.argv[6].split(",")]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
EFFECT = "contacts" if "calllog" in d.excluded else "calllog"
d.sh(d.u("am stopservice -n %s/.FgService" % lmdrv.CPKG)); d.launch()
CR = ("content://com.android.contacts/raw_contacts", "deleted=0 AND display_name LIKE 'LM bulk%'")
IM = ("content://media/external_primary/images/media", "_display_name LIKE 'bulk%'")


def count(uri, where, timeout=180):
    o = d.sh(d.u('content query --uri %s --projection _id --where "%s"' % (uri, where)), timeout=timeout)
    return o.count("Row:")


def decide(level, change_src, extra):
    w.ensure_base(); time.sleep(1.5)
    d.cmd("OBSERVE", timeout=120)
    muts = []
    for src, kind in change_src:
        muts.append(w.mutate(src, kind))
    if muts:
        time.sleep(1.0)
    D = d.cmd("DECIDE", timeout=120)
    return {**d.meta(), "serial": serial, "exp": "phys_cost", "mode": mode, "level": level, **extra,
            "change": [m["src"] for m in muts], "muts": muts,
            "costs": {k: v for k, v in D.items() if k.endswith("cost")},   # lm_cost, lmts_cost and any other *_cost the client reports
            "refresh_ns": {k: v.get("refresh_ns") for k, v in D["facts"].items() if v.get("src") != "derived"},
            "fact_src": {k: v.get("src") for k, v in D["facts"].items()},
            "lm_miss": sum(1 for v in D["facts"].values() if v.get("mem") != v.get("truth") and v.get("lm") == "FRESH")}


def act(level, extra, i):
    w.ensure_base(); time.sleep(1.0)
    d.cmd("OBSERVE", timeout=120)
    rid = "pc%d_%s_%d" % (seed, level.replace("+", "_").replace(":", "_"), i)
    d.rm(lmdrv.CPKG, "files/res_%s.json" % rid)
    at = d.now_ms() + 1500
    d.sh(d.u("am broadcast -n %s/.Cmd --es cmd ACT --es id %s --es fact c.dana --es mode bnd --el at %d --es effect %s --es validator hist"
             % (lmdrv.CPKG, rid, at, EFFECT)))
    res, t0 = None, time.time()
    while time.time() - t0 < 60:
        s = d.cat(lmdrv.CPKG, "files/res_%s.json" % rid)
        if s.startswith("{") and "effect_end" in s:
            res = json.loads(s); break
        time.sleep(0.2)
    r = {**d.meta(), "serial": serial, "exp": "phys_cost_act", "mode": mode, "level": level, **extra, "act": True, "effect_store": EFFECT}
    if res:
        r.update(check_ms=res["check2_end"] - res["check2_start"], effect_ms=res["effect_end"] - res["effect_start"],
                 check_to_effect_ms=res["effect_end"] - res["check2_start"])
    else:
        r["error"] = "no ACT result in 60 s"
    return r


with lmdrv.open_new(out) as f:
    def put(r):
        f.write(json.dumps(r) + "\n"); f.flush()
    w.ensure_base()
    if mode == "persource":
        srcs = sorted(w.kinds) + ["none"]
        for r in range(R):
            for src in srcs:
                try:
                    kind = None if src == "none" else "update" if "update" in w.kinds[src] else w.kinds[src][0]
                    rec = decide("base", [(src, kind)] if kind else [], {"round": r, "source": src})
                except Exception as e:
                    rec = {**d.meta(), "serial": serial, "exp": "phys_cost", "mode": mode, "round": r, "source": src, "error": repr(e)}
                put(rec); print("round", r, src, rec.get("error", "ok")[:100], flush=True)
    elif mode == "scale":
        added = {"contacts": count(*CR), "media": count(*IM)}
        for src, target in LEVELS:
            t_grow = time.time()
            while added[src] < target:
                k = min(500 if src == "contacts" else 200, target - added[src])
                if src == "contacts":
                    d.mut("bulk_contacts", str(k), "LM bulk%d" % added[src], timeout=180)
                else:
                    d.mut("bulk_images", str(k), "bulk%d" % added[src], timeout=400)
                added[src] += k
            grow_s = round(time.time() - t_grow, 1); time.sleep(15)
            level = "%s+%d" % (src, target)
            extra = {"raw_contacts": count("content://com.android.contacts/raw_contacts", "deleted=0"),
                     "images": count("content://media/external_primary/images/media", "relative_path='Pictures/lm/'"),
                     "grow_s": grow_s}
            for i in range(2 * R):
                change = [("contacts", "update"), ("media", "insert")] if i % 2 else []
                try:
                    rec = decide(level, change, dict(extra, i=i))
                except Exception as e:
                    rec = {**d.meta(), "serial": serial, "exp": "phys_cost", "mode": mode, "level": level, "i": i, "error": repr(e)}
                put(rec)
            for i in range(R):
                try:
                    put(act(level, extra, i))
                except Exception as e:
                    put({**d.meta(), "serial": serial, "exp": "phys_cost_act", "mode": mode, "level": level, "i": i, "error": repr(e)})
            print("level", level, extra, flush=True)
    else:
        raise SystemExit("mode is persource or scale")
d.sh(d.u("am stopservice -n %s/.FgService" % lmdrv.CPKG))

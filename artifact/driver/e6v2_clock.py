#!/usr/bin/env python3
"""E6 v2 (round 2): wall-clock set-back against both Contacts adapters.
Same protocol as the clock part of e6_pitfalls.py (observe; set the clock back 1 h; edit Dana's number; restore the
clock before (transient) or after (persistent) the decision). The v3 client evaluates the clock-free RawContacts
VERSION adapter (lm) and the timestamp adapter with its clock guard (lmts) on the same decision.
Usage: e6v2_clock.py SERIAL N SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv
serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
d.sh("settings put global auto_time 0")
with open(out, "a") as fo:
    for i in range(n):
        variant = "transient" if i % 2 == 0 else "persistent"
        w.ensure_base(); time.sleep(1.0)
        d.cmd("OBSERVE")
        d.sh("date @%d" % ((d.now_ms() - 3600 * 1000) // 1000))
        m = w.mutate("contacts", "update")
        if variant == "transient":
            d.sh("date @%d" % ((d.now_ms() + 3600 * 1000) // 1000 + 1))
        time.sleep(0.5)
        dec = d.cmd("DECIDE")
        if variant == "persistent":
            d.sh("date @%d" % ((d.now_ms() + 3600 * 1000) // 1000 + 1))
        f = dec["facts"]["c.dana"]
        rec = {"exp": "clock_v2", "i": i, "variant": variant, "clock_jump": dec.get("clock_jump"),
               "lm_ver": f["lm"], "lm_ts": f["lmts"], "stale_if_used": f["mem"] != f["truth"],
               "wm_obs": dec["wm_obs"], "wm_now": dec["wm_now"], "mut": m,
               "reason_ver": dec["lm_cost"]["contacts"]["reason"], "reason_ts": dec["lmts_cost"]["contacts"]["reason"]}
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(variant, rec["lm_ver"], rec["lm_ts"], rec["stale_if_used"], flush=True)
d.sh("settings put global auto_time 1")

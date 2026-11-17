#!/usr/bin/env python3
"""E6: evidence pitfalls (real emulator).
 (a) SMS row-id reuse: delete the newest SMS, insert another; does the new row get the deleted id?
 (b) FUSE mtime granularity: append to a file twice within a second; does mtime advance?
 (c) wall-clock set-back: observe; set the clock back; update a contact; restore (transient) or not (persistent);
     does the contact timestamp watermark advance, and does the client's clock guard flag it?
Usage: e6_pitfalls.py SERIAL N SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
with open(out, "a") as fo:
    w.ensure_base()
    for i in range(n):
        r = d.mut("sms_reuse"); fo.write(json.dumps({"exp": "sms_reuse", "i": i, "res": r}) + "\n")
    for i in range(n):
        r = d.mut("file_touch_same_second", extra="--es tag %d" % i)
        r2 = d.mut("file_touch_same_second", extra="--es tag %db" % i)
        fo.write(json.dumps({"exp": "mtime", "i": i, "res": [r, r2]}) + "\n")
        time.sleep(rng.uniform(0.05, 1.2))
    d.sh("settings put global auto_time 0")
    for i in range(n):
        variant = "transient" if i % 2 == 0 else "persistent"
        w.ensure_base(); time.sleep(1.0)
        ob = d.cmd("OBSERVE")
        now = d.now_ms()
        back = now - 3600 * 1000                         # one hour back
        d.sh("date @%d" % (back // 1000))
        m = w.mutate("contacts", "update")
        if variant == "transient":
            d.sh("date @%d" % ((d.now_ms() + 3600 * 1000) // 1000 + 1))
        time.sleep(0.5)
        dec = d.cmd("DECIDE")
        if variant == "persistent":
            d.sh("date @%d" % ((d.now_ms() + 3600 * 1000) // 1000 + 1))
        f = dec["facts"]["c.dana"]
        rec = {"exp": "clock", "i": i, "variant": variant, "wm_obs": dec["wm_obs"].get("contacts"), "wm_now": dec["wm_now"].get("contacts"),
               "clock_jump": dec.get("clock_jump"), "lm": f["lm"], "stale_if_used": f["mem"] != f["truth"], "reason": dec["lm_cost"]["contacts"]["reason"], "mut": m}
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(rec["variant"], rec["lm"], rec["reason"], rec["stale_if_used"], flush=True)
    d.sh("settings put global auto_time 1")

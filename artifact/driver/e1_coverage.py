#!/usr/bin/env python3
"""E1: which sources expose durable change evidence? (real emulator)

Per trial: client alive in background; PROBE candidate evidence; mutate every source with a random kind
(or leave it unchanged: kind 'none'); wait SETTLE s; PROBE again. Records candidate changes, fact changes and
the ContentObserver/FileObserver events the client received (with device timestamps).
Usage: e1_coverage.py SERIAL N_TRIALS SEED OUT.jsonl [fg]
"""
import json, random, sys, time
sys.path.insert(0, __import__("os").path.dirname(__file__))
import lmdrv

serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
fg = len(sys.argv) > 5 and sys.argv[5] == "fg"
SETTLE = 13.0
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
if fg:
    d.sh(d.u("am start -n %s/.Main --ez stay true" % lmdrv.CPKG))
with lmdrv.open_new(out) as f:
    for t in range(n):
        try:
            w.ensure_base(); time.sleep(SETTLE)
            d.cmd("OBSERVE")                       # clears the client's event list
            p0 = d.cmd("PROBE")
            muts = []
            for src in w.kinds:
                kinds = ["none"] + w.kinds[src]
                k = rng.choice(kinds)
                if k == "none":
                    muts.append({"src": src, "kind": "none"}); continue
                muts.append(w.mutate(src, k))
            time.sleep(SETTLE)
            p1 = d.cmd("PROBE")
            ev = d.cmd("DECIDE")                  # carries the event list with device timestamps
            rec = {**d.meta(), "trial": t, "seed": seed, "serial": serial, "fg": fg, "muts": muts, "p0": p0["probe"], "p1": p1["probe"],
                   "events": ev.get("events"), "pid0": p0["pid"], "pid1": p1["pid"], "oom_adj": d.sh("cat /proc/%s/oom_score_adj" % (d.pid() or "self")).strip()}
            f.write(json.dumps(rec) + "\n"); f.flush()
            print("trial", t, [(m["src"], m["kind"]) for m in muts], flush=True)
        except Exception as e:
            print("ERR trial", t, repr(e), flush=True)
            f.write(json.dumps({"trial": t, "error": repr(e)}) + "\n"); f.flush()
            d.launch()

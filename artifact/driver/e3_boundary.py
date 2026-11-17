#!/usr/bin/env python3
"""E3: re-observation is not enough unless coupled to the action boundary (real emulator).

Per trial: OBSERVE; send ACT(fact, mode, delay D). The client validates the fact with LeaseMem at t_r, waits D
(standing in for planning/LLM latency), then either acts directly (mode 'obs') or re-validates at the action
boundary first (mode 'bnd'). In 'change' trials the driver mutates the fact's source at a uniform random offset
inside the planning window. Outcome: did the action use a value different from the source at action time?
Usage: e3_boundary.py SERIAL N_PER_CELL SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
D = 3000
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.launch()
cells = [(f, m, c) for f in ("c.dana", "s.latest") for m in ("obs", "bnd") for c in (1, 1, 0)]  # 2:1 change:control
plan = []
for _ in range(n):
    plan += cells
rng.shuffle(plan)
MUT = {"c.dana": ("contacts", "update"), "s.latest": ("sms", "insert")}
with open(out, "a") as fo:
    for i, (fact, mode, change) in enumerate(plan):
        rec = {"i": i, "fact": fact, "mode": mode, "change": change, "delay": D, "seed": seed}
        try:
            w.ensure_base(); time.sleep(1.5)
            d.cmd("OBSERVE")
            off = rng.uniform(0.3, D / 1000.0 - 0.4)
            rec["offset_planned"] = round(off, 3)
            # send ACT without waiting for its (delayed) result
            d.seq += 1
            rid = "a%d_%d" % (seed, i)
            d.sh("rm -f %s/res_%s.json" % (lmdrv.FILES, rid))
            t_send = time.time()
            d.sh("am broadcast -n %s/.Cmd --es cmd ACT --es id %s --es fact %s --es mode %s --el delay %d" % (lmdrv.CPKG, rid, fact, mode, D))
            if change:
                time.sleep(max(0, off - (time.time() - t_send)))
                rec["mut"] = w.mutate(*MUT[fact])
            t0 = time.time(); res = None
            while time.time() - t0 < D / 1000.0 + 15:
                s = d.sh("cat %s/res_%s.json 2>/dev/null" % (lmdrv.FILES, rid))
                if s.startswith("{") and "t_act" in s:
                    res = json.loads(s); break
                time.sleep(0.2)
            rec["res"] = res
            fo.write(json.dumps(rec) + "\n"); fo.flush()
            print(i, fact, mode, change, None if res is None else res.get("stale"), flush=True)
        except Exception as e:
            rec["error"] = repr(e); fo.write(json.dumps(rec) + "\n"); fo.flush()
            print("ERR", i, repr(e), flush=True); d.launch()

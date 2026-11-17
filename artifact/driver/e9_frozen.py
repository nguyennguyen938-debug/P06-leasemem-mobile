#!/usr/bin/env python3
"""E9: are change notifications to a frozen process lost or only delayed? (real emulator)

Per trial: observe; send the client to the background and wait until its cgroup is frozen (requires the short
freezer debounce, set live with DeviceConfig sync disabled); then, while it stays frozen for FROZEN_S seconds after
the first change, another app mutates sources every ~STEP s (inserts and updates only, so the loop is sustainable;
>=100 notifications per trial). The frozen state is sampled during the loop. The gap ends with a DECIDE broadcast
(which thaws the process); decisions at +2 s, +14 s and +120 s record every callback received.
Usage: e9_frozen.py SERIAL N SEED OUT.jsonl [FROZEN_S]
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv
from e2v3_gaps import frozen

serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
FROZEN_S = float(sys.argv[5]) if len(sys.argv) > 5 else 600.0
STEP = 3.0
KINDS = {"contacts": ["update", "insert"], "sms": ["insert", "update"], "calllog": ["insert", "update"],
         "media": ["insert", "update"], "calendar": ["update", "insert"], "settings": ["update"], "files": ["update", "insert"]}
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
d.sh("am stopservice -n %s/.FgService" % lmdrv.CPKG)
d.launch()
with lmdrv.open_new(out) as f:
    for t in range(n):
        log = {**d.meta(), "trial": t, "gap": "frozen_long", "seed": seed, "serial": serial, "frozen_target_s": FROZEN_S, "protocol": "v3"}
        try:
            if not d.pid():
                d.launch()
            d.home()
            w.ensure_base(); time.sleep(16.0)          # > Android 15's ~13.5 s deferral, so setup callbacks drain
            ob = d.cmd("OBSERVE")
            log.update({"t_obs": ob["t_recv"], "pid_obs": ob["pid"], "epoch_obs": ob["epoch"]})
            d.home()
            t0 = time.time()
            while time.time() - t0 < 25 and frozen(d) != "1":
                time.sleep(0.5)
            log["frozen_after_s"] = round(time.time() - t0, 1)
            log["frozen"] = frozen(d); log["frozen_method"] = d.frozen_method
            if log["frozen"] != "1":
                log["invalid"] = "not_frozen"
                f.write(json.dumps(log) + "\n"); f.flush(); print("INVALID not frozen", t, flush=True); continue
            log["t_gap_start"] = d.now_ms()
            muts, samples = [], []
            t_first = None
            while True:
                src = rng.choice(list(KINDS)); kind = rng.choice(KINDS[src])
                m = w.mutate(src, kind); muts.append(m)
                if t_first is None:
                    t_first = m["t_pre"]
                if len(muts) % 10 == 0:
                    samples.append([d.now_ms(), frozen(d), d.pid()])
                if d.now_ms() - t_first >= FROZEN_S * 1000:
                    break
                time.sleep(STEP)
            log["muts"] = muts; log["frozen_samples"] = samples
            log["frozen_at_end"] = frozen(d); log["pid_at_end"] = d.pid()
            log["t_first_mut"] = t_first; log["t_gap_end"] = d.now_ms()
            log["frozen_with_pending_s"] = round((log["t_gap_end"] - t_first) / 1000.0, 1)
            time.sleep(2.0); log["early"] = d.cmd("DECIDE", timeout=60)
            time.sleep(12.0); log["late"] = d.cmd("DECIDE", timeout=60)
            time.sleep(106.0); log["vlate"] = d.cmd("DECIDE", timeout=60)
            f.write(json.dumps(log) + "\n"); f.flush()
            print("trial", t, "muts", len(muts), "frozen_end", log["frozen_at_end"], flush=True)
        except Exception as e:
            print("ERR", t, repr(e), flush=True)
            log["error"] = repr(e); f.write(json.dumps(log) + "\n"); f.flush()
            try:
                d.wait_boot(); d.adb("root"); time.sleep(2); d.launch()
            except Exception as e2:
                print("recover failed", repr(e2), flush=True)

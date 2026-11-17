#!/usr/bin/env python3
"""Phase-3 smoke test for LeaseMem-Mobile: mechanism-level, standard library only, seeded, ~1 s.

NOT real data. Simulates sources whose rows change as a Poisson process, a memory process that is absent for
random intervals (notifications lost), optional 10 s delivery deferral, and four policies. Checks the direction
of the paper's hypotheses under the paper's own assumptions.
"""
import math
import random

SEED = 20261108
rng = random.Random(SEED)


def run(policy, p_absent=0.5, lam=1 / 120.0, defer=10.0, decide_delay=2.0, trials=4000, watermark_ok=True, ttl=30.0):
    stale = changed = refresh = 0
    for _ in range(trials):
        gap = rng.uniform(5, 60)
        absent = rng.random() < p_absent
        # change times during [0, gap]
        t, changes = 0.0, []
        while True:
            t += rng.expovariate(lam)
            if t > gap:
                break
            changes.append(t)
        tdec = gap + decide_delay
        did_change = bool(changes)
        changed += did_change
        if policy == "event":
            delivered = (not absent) and any(c + defer <= tdec for c in changes)
            use_mem = not delivered
        elif policy == "ttl":
            use_mem = tdec < ttl
        elif policy == "global":
            use_mem = False
        elif policy == "leasemem":
            # watermark moves on every change (A2); if broken (watermark_ok False) it misses half of changes
            moved = did_change if watermark_ok else any(rng.random() < 0.5 for _ in changes)
            use_mem = not moved
        refresh += not use_mem
        if use_mem and did_change:
            stale += 1
    return stale / max(1, changed), refresh / trials


def boundary(delay, lam=1 / 20.0, trials=20000, resid=0.001):
    st_obs = st_bnd = 0
    for _ in range(trials):
        t = rng.expovariate(lam)
        st_obs += t < delay
        st_bnd += t < resid
    return st_obs / trials, st_bnd / trials, 1 - math.exp(-lam * delay)


rows = []
ev = run("event")
lm = run("leasemem")
gl = run("global")
ttl = run("ttl")
rows.append(("H1", "event-only misses changes made while absent / undelivered", "miss=%.3f" % ev[0], ev[0] > 0.3))
rows.append(("H2", "LeaseMem with monotone change-revealing watermark misses none", "miss=%.3f" % lm[0], lm[0] == 0.0))
rows.append(("H3", "LeaseMem refreshes less than global refresh", "refresh lm=%.3f gl=%.3f" % (lm[1], gl[1]), lm[1] < gl[1]))
ev0 = run("event", p_absent=0.0, decide_delay=2.0)
ev14 = run("event", p_absent=0.0, decide_delay=14.0)
rows.append(("H4", "deferred delivery makes event-only stale even without a gap (early > late)", "early=%.3f late=%.3f" % (ev0[0], ev14[0]), ev0[0] > ev14[0]))
bad = run("leasemem", watermark_ok=False)
rows.append(("H5", "soundness depends on A2: a non-revealing watermark misses changes", "miss=%.3f" % bad[0], bad[0] > 0))
o, b, theo = boundary(3.0)
rows.append(("H6", "validation without boundary re-check is stale ~1-exp(-lambda d)", "obs=%.3f theory=%.3f bnd=%.4f" % (o, theo, b), abs(o - theo) < 0.02 and b < 0.01))
rows.append(("H7", "TTL trades misses for refreshes (no TTL gives both low)", "ttl30 miss=%.3f refresh=%.3f" % ttl, ttl[0] > 0 or ttl[1] > 0.9))
print("seed", SEED)
for h, claim, obs, ok in rows:
    print("%-3s %-80s %-34s %s" % (h, claim, obs, "HOLDS" if ok else "DOES-NOT-HOLD"))

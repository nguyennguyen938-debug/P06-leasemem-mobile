# P06 LeaseMem-Mobile — Phase 3 smoke test

**Date:** 2026-11-08. **Script:** `others/smoke/smoke_test.py`. It uses only the Python standard library, is seeded (20261108), and runs in under 0.1 s. Console output: `others/smoke/smoke_output.txt`.

## What this is

This is a mechanism-level check of the hypotheses' *direction* under the paper's own modelling assumptions. **It is not real data.** In the model, each source changes as a Poisson process (rate 1/120 s). The memory process is absent with probability 0.5 for a uniform 5–60 s gap, and notifications sent during absence are lost. Live notifications are deferred by 10 s, mirroring ContentService's background delay. A decision follows the gap by 2 s ("early") or 14 s ("late"). All headline numbers in the paper come instead from the real emulator runs (`artifact/results/raw/`).

## Verdicts

| Hyp. | Claim | Toy setup | Observed | Verdict |
|---|---|---|---|---|
| H1 | Event-only invalidation misses changes made while the process is absent or before delivery | p_absent=0.5, defer 10 s | miss = 0.605 | HOLDS |
| H2 | LeaseMem with a monotone, change-revealing watermark misses none | A1–A2 satisfied | miss = 0.000 | HOLDS |
| H3 | LeaseMem refreshes less than global refresh | same | refresh 0.238 vs 1.000 | HOLDS |
| H4 | Deferred delivery makes event-only stale even with no gap (early > late) | p_absent=0 | 0.236 vs 0.000 | HOLDS |
| H5 | Soundness depends on A2; a watermark that misses changes is unsound | watermark moves w.p. 0.5 per change | miss = 0.473 | HOLDS |
| H6 | Validation without a boundary re-check is stale w.p. 1−e^(−λd) | λ=1/20 s, d=3 s | 0.139 vs theory 0.139; boundary 0.0001 | HOLDS |
| H7 | A fixed TTL trades misses for refreshes | TTL 30 s | miss 0.229, refresh 0.591 | HOLDS |

## Console output

```
seed 20261108
H1  event-only misses changes made while absent / undelivered                        miss=0.605                         HOLDS
H2  LeaseMem with monotone change-revealing watermark misses none                    miss=0.000                         HOLDS
H3  LeaseMem refreshes less than global refresh                                      refresh lm=0.238 gl=1.000          HOLDS
H4  deferred delivery makes event-only stale even without a gap (early > late)       early=0.236 late=0.000             HOLDS
H5  soundness depends on A2: a non-revealing watermark misses changes                miss=0.473                         HOLDS
H6  validation without boundary re-check is stale ~1-exp(-lambda d)                  obs=0.139 theory=0.139 bnd=0.0001  HOLDS
H7  TTL trades misses for refreshes (no TTL gives both low)                          ttl30 miss=0.229 refresh=0.591     HOLDS
```

## Caveats

- H2 and H3 hold by construction once A1–A2 are assumed. The real question is which Android sources satisfy A1–A2, and that is answered only by the emulator measurement (E1, E6).
- H3 counts refreshes, not milliseconds. On the real emulator, a provider refresh costs only tens of milliseconds, so LeaseMem's validation is **not** cheaper than global provider refresh (see the paper's §7 cost results). A saving appears only when re-observation is expensive, as with GUI re-observation.
- H4 shows deferral in the model. The 10 s delay itself is a measured platform fact (E1, Figure `fig:latency`), confirmed in AOSP source.

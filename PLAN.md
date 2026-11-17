# PLAN — P06 LeaseMem-Mobile (MobiSys 2027)

Venue: MobiSys 2027, `\documentclass[sigconf,review,anonymous]{acmart}`, 12-page body limit. Abstract registration Nov 27 and submission Dec 4, 2026 (AoE).

## Question
Can a mobile agent/app memory tell "nothing changed" from "the process was absent and missed the changes"? Where it can, at what cost? Where it cannot, what should it do?

## Artifact inventory (every table/figure → producing experiment/script)

| Label | Content | Experiment | Producer |
|---|---|---|---|
| fig:overview | cartoon overview (no data) | — | `manuscript/figures/fig1-overview.tex` |
| tab:coverage | durable evidence per source × mutation | E1 (`driver/e1_coverage.py`, bg 80 trials) | `analyze.e1` → `render.tab_coverage` |
| fig:latency | notification delay CDF (bg) | E1 | `render.lat_cdf` |
| tab:gaps | gap taxonomy (survival, notifications early/late, trigger, exit records) | E2 (`driver/e2_gaps.py`, 8 gaps × 50) | `analyze.e2` → `render.tab_gaps` |
| tab:aw | AndroidWorld store census | E5 (`scripts/aw_census.py`) | `render.tab_aw` |
| tab:facts | fact catalogue (static description of inputs) | — | `sections/07-evaluation.tex` |
| tab:policy | missed changes per gap × policy (early/late) | E2 | `render.policy` |
| fig:miss | bar: missed changes, late, Wilson CIs | E2 | `render.policy` |
| fig:ttl | line: TTL sweep | E2 timestamps (offline replay) | `render.ttl` |
| tab:cost | per-source refresh/validate ms, GUI s | E2 + E4 (`driver/e4_gui_cost.py`) | `render.tab_cost` |
| tab:boundary | validation vs boundary | E3 (`driver/e3_boundary.py`, 300 trials) | `render.tab_boundary` |
| RQ4 macros | SMS id reuse, mtime granularity, clock | E6 (`driver/e6_pitfalls.py`) | `render.scalars` |
| tab:sig, tab:labels | Fisher/Holm; LeaseMem verdict mix | E2 | `render.tab_sig/tab_labels` |

## Data
Synthetic but real-platform: the mutator app writes contacts, SMS, call log, calendar (local account), settings, MediaStore images and shared files on emulators we own. No personal data. AndroidWorld checkout pinned at 55ddaf5e (read-only, shared-android).

## Baselines
Fixed TTL (5–300 s); event-only (ContentObserver/FileObserver, persisted flags); Tether-style dependency propagation driven by delivered events; event-only + JobScheduler content trigger; global refresh; LeaseMem; LeaseMem-epoch (ablation).

## Metrics & protocol
Missed-change rate (stale critical decisions / changed uses), refresh rate, unnecessary refresh, provider ms per decision, GUI s per re-observation, LeaseMem verdict mix (FRESH/CHANGED/UNKNOWN). Wilson 95% CIs; bootstrap CIs for medians (2,000 resamples, fixed seed); Fisher exact test with Holm correction. 50 trials per gap; E3 has 50 change trials per (fact, placement).

## Pipeline
1. `driver/run_e2_5622.sh`, `driver/run_5620.sh`, `driver/run_5622_b.sh` (emulator batches)
2. `scripts/aw_census.py`
3. `make all` (analyze → render → paper)

## Compute/timeline
Two emulator instances (5620/5622), about 7 h of wall time on 2026-11-08. Paper revision rounds follow the external reviews.

## Risks
Host sleep pauses emulators (mitigated by exclusion rule + caffeinate). OEM/version differences (only API 33 emulator). No field frequency data for gaps (stated as limitation).

## Definition of done / honesty gate
Every number in the PDF is generated from the run (`make all`); no `??` placeholders; 0 undefined refs; body ≤ 12 pages; negative results (no latency win over provider refresh; transient clock set-back undetected) are kept in the paper.

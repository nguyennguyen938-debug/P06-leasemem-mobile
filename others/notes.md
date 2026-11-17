# P06 (EvCheck; working name LeaseMem-Mobile) — claim → evidence ledger

All numbers in the PDF come from `manuscript/generated/macros.tex` and the `tab_*`/`fig_*` files, which `artifact/scripts/render.py` writes from `artifact/results/derived/*.csv`. `analyze.py` produces those CSVs from the raw emulator logs in `artifact/results/raw/*.jsonl`. Do not hand-edit numbers.

| # | Claim (where) | Evidence | Source file(s) | Status |
|---|---|---|---|---|
| C1 | MediaStore generation moves on insert/rename/delete; it is volume-wide, so it also moves when unrelated files change (§3, Tab. coverage) | E1 candidate counts | `e1_candidates.csv`, `e1_adapters.csv` | measured |
| C2 | max(generation_modified) and max(LAST_MODIFIED) move down on delete (not monotone) | E1 `_down` columns | `e1_candidates.csv` | measured |
| C3 | Contacts: last-updated ts moves on insert/edit; deleted-contacts log on delete | E1 | `e1_candidates.csv` | measured |
| C4 | SMS body edits and calendar event edits move no candidate | E1 update column | `e1_candidates.csv` | measured |
| C5 | App-written Documents files are not in MediaStore; shell-created files stay is_pending | manual probes 2026-11-08 00:22–00:26 (RUNLOG); E1 `files.media_count` constant | RUNLOG, raw E1 | measured (qualitative + E1 field) |
| C6 | Background provider notifications ~10 s late; FileObserver immediate; foreground fast | E1 latency (bg) + E1 fg; AOSP ContentService constant | `e1_events.csv`, `e1_latency.csv`; aosp_contentservice | measured + source-verified |
| C7 | Content-trigger jobs cannot be persisted | AOSP JobInfo source (verified by fetch) | aosp_jobinfo | source-verified |
| C8 | Gap taxonomy: survival, notification delivery early/late, trigger, exit records | E2 | `e2_taxonomy.csv` | measured |
| C9 | Event-only misses DeathEv of changed uses in listener-loss gaps; Tether-style the same; LeaseMem 0 | E2 | `e2_policy.csv`, summary.json | measured |
| C10 | LeaseMem-epoch unsound under deferred delivery | E2 none/freeze early | `e2_policy.csv` | measured |
| C11 | OS trigger fixes kill, not force-stop/reboot | E2 | `e2_policy.csv`, `e2_taxonomy.csv` | measured |
| C12 | TTL: no single TTL works | offline replay over E2 timestamps | `e2_ttl.csv` | computed from measured timestamps |
| C13 | LeaseMem is NOT faster than global provider refresh | E2 cost | `e2_cost.csv`, summary cost_* | measured (negative result, kept) |
| C14 | GUI re-observation median GuiS s (best case, no LLM) | E4 | `e4_gui.csv` | measured |
| C15 | Boundary re-validation reduces stale actions; residual > 0 | E3 | `e3_boundary.csv` | measured |
| C16 | SMS id reuse; mtime same-second; clock set-back breaks TS watermark; guard catches persistent, not transient | E6 | summary e6_* , `e6_clock.csv` | measured |
| C17 | AndroidWorld census: AwWm/AwApi/AwGui of 116 | code inspection (registry + manual store map) | `aw_census_*.csv` | code inspection, not a run |
| C18 | SIGKILL fallback used in 0 kill trials | E2 raw `sigkill_fallback_*` keys | summary sigkill_fallbacks=0 | verified |
| C19 | (superseded) Tests are now trial-level, restart-aware vs EvCheck at the early decision, with platform column | Fisher+Holm on trials | `e2_sig.csv` | superseded by R3-7 |
| C20 | Theorems 1–2, Props 3–4 | proofs in appendix | `appendix-proofs.tex` | analytical |
| C21 | Unregister-gap event-only catches only shared-file changes (23/23), via FileObserver delivering after stopWatching (artifact) | raw e2_unregister | RUNLOG 05:45 | verified, disclosed |
| C22 | (corrected) Reboot: Contacts DB empty after 1/90 reboots (all rounds); MediaStore version never changed | E2 reboot wm_obs/wm_now | summary reboot_* | measured |
| C23 | E7: 0/10 LMK kills in 28 app switches (3 GB AVD) | E7 | summary e7_* | measured |
| C24 | Per-source LeaseMem verdicts (reuse, false invalidation, unknown) | E2 | `e2_per_source.csv` | measured |

## Honesty notes
- The "agent" is a deterministic script; only E8 calls a local LLM (Ollama qwen2.5:7b). The memory client evaluates all in-app policies over the same evidence. TTL and the OS-trigger baseline are computed offline from logged device timestamps and the trigger app's durable log.
- The freezer experiment uses a shortened freezer debounce (2 s instead of the default 600 s).
- Host sleep paused the emulators during some trials; those are excluded by a duration-only rule (span > 120 s, 400 s for reboot), independent of outcomes, and the count is reported (ETwoSleep).
- Client v1 → v2 (clock guard). E1 used v1, whose PROBE code path is identical to v2's. All E2/E3/E6 data come from v2.
- Discarded: the first CLI-mutator runs (too slow), kept in `artifact/logs/discarded_cli_runs/` and used nowhere.


## Round-2 ledger additions (2026-11-08)
| # | Claim | Evidence | Source | Status |
|---|---|---|---|---|
| R1 | Restart-aware event-only: 0/660 missed in process-ending gaps, refreshes 16/16 | E2 v3 bg | `e2_policy.csv`, summary death_*, mean_evr_ref_death | measured |
| R2 | In-epoch early misses: restart-aware 88/559, LeaseMem 0 | E2 v3 bg | summary susp_* | measured |
| R3 | Age dependence: API 33 65/76 (<10 s) vs 1/800; API 35 31/33 and 27/177, up to 26 s; FGS 0 | E2 v3 | `e2_ages.csv`, summary age_* | measured |
| R4 | Deferral API 35 median 13.5 s (source constant 10 s) | E1 API 35 | summary e1api35_*; AOSP android15 ContentService | measured + source-checked |
| R5 | (corrected) Long gaps: default-debounce freezer held changes only ~60 s; stepped Doze in maintenance window at batch 2 in 4/5 | E2 longfreeze/longdoze | `e2_taxonomy.csv` | measured; superseded by R3-2/R3-4 |
| R6 | LeaseMem slower for provider facts (43 vs 32 ms; 92%) | E2 v3 bg | summary cost_* | measured (negative, kept) |
| R7 | (withdrawn as a benefit claim) E8: memoization beats EvCheck in every condition | E8 | `e8_summary.csv` | see R3-3 |
| R8 | E3 v2: 3/13 stale with overlap; 0/130 before; 0/17 after | E3 v2 | `e3_where.csv` | measured |
| R9 | VERSION adapter clock-proof (15/15, 15/15) | E6 v2 | summary e6v2_* | measured |
| R10 | Freezer flag reverted by reboot and by DeviceConfig sync | RUNLOG 06:12, 06:18 | logs | observed |


## Round-3 ledger (2026-11-09)
| # | Claim | Evidence | Source | Status |
|---|---|---|---|---|
| R3-1 | Doze and the restricted bucket add no delay: first callback 10.0 s median like no gap; freezer 18.3 s | E2 first-callback latency | `e2_taxonomy.csv` fcl_* | measured |
| R3-2 | 10-min frozen holds: 0/133 + 0/140 sources lost while frozen; 1/20 Android 13 frozen process killed ("too many empty") | E9 | `e9_frozen.csv`, summary e9_* | measured |
| R3-3 | E8 memoization 1.81 vs EvCheck 4.03 s (kill, p=0.3), cheaper in all conditions; times are sums of per-call latencies | E8 | `e8_summary.csv` | measured (cost model) |
| R3-4 | Verified deep-idle long Doze (default debounce) | E2 longdoze2 | `e2_taxonomy.csv` | see RUNLOG; first run excluded (2 s debounce confound) |
| R3-5 | Default assistant: ProcState 5 / adj 100, ms callbacks, not frozen, survives am kill; persistent priv-app: 0 / -800, force-stop no effect | E10 | `raw/e10_deploy_*.jsonl`, `tab_deploy.tex` | measured |
| R3-6 | FGS cost: small CPU/PSS/charge; policy costs from Android docs | E11 + docs | `raw/e11_fgcost_33.jsonl` | measured + cited |
| R3-7 | Trial-level Fisher/Holm with platform column | E2 | `e2_sig.csv` | computed |
| R3-8 | Scale: Contacts validation 7.0→31.7 ms (48→5048 raw contacts), MediaStore 4.7→32.9 ms (→10074 images), check→effect 19→34 ms | E12 | `raw/e12_scale.jsonl` | measured |
| R3-9 | Host agent over adb: global 11.9 s vs EvCheck 8.0/8.1 s, faster 40/40, 0 misses | E13 | `e13_host.csv` | measured |
| R3-10 | E3 band: overlap 55/104 stale; ±10 ms of check start 51/67 vs later 3/107 | E3 | `e3_where.csv`, `e3_bins.csv` | measured |
| R3-11 | Census rescope: 71 tasks read existing state; 12 evidence / 6 API / 53 GUI | code inspection | `aw_census_tasks.csv` reads_state | code inspection |

# STATUS — P06 LeaseMem-Mobile

**Current state (2026-11-15): approved emulator revision complete; release validation passed.**

The revised manuscript uses explicit 10pt and has 12 main-body pages (21 total). It adds consistent cooperative certificates, conservative UNKNOWN stock fallback, device-executed race tests, matched host baselines, trial-level uncertainty, deployment diagnostics and a conformance suite. Determinism passes for 53 outputs; a clean anonymous local extraction rebuilds analyses, PDF and APKs with identical generated outputs/PDF text. Physical-device replication and complete stock contracts remain open.

See `review/revision-execution-report.md`, `review/artifact-revision-audit.md`, `manuscript/main.pdf` and `output/review-package/P06-review.zip`. Raw/failed runs are retained. Both owned emulators are stopped. No public upload, commit or push was made.

The following status blocks are historical and are superseded where their claims conflict with the revision.

**State (2026-11-09, ~04:50 +07): ROUND-3 REVISION COMPLETE.** Round-2 decision was Reject (2/2/3/2). All round-3 experiments ran and are analysed:
- E9 long frozen holds: 20 + 20 trials.
- E10 deployments: background / FGS / assistant on Android 13 and 15; persistent priv-app on Android 13.
- E11 FGS cost.
- E12 scale: up to 5,048 raw contacts and 10,074 images.
- E13 host agent.
- E3 band: 150 trials.
- Verified long Doze: 10 trials. Its first run (2 s debounce confound) and the first persist run are excluded and disclosed.

The paper is retitled *Absent or Unchanged? What Android Tells a Cached-Fact Client After a Lifecycle Gap*, and the system is renamed EvCheck. Claims are rescoped: the default assistant is neither deferred nor frozen, so restart-aware refresh is sound there. EvCheck is cheaper only for a host agent. Memoization beats it for LLM-derived facts.

The PDF has 17 pages; the body ends on p. 12. There are 62 references, all cited, with no undefined references, no overfull boxes and no `??`. `make all` succeeds, and `make check-determinism` prints DETERMINISTIC. The response is in `review/response-round2.md`. Emulators 5620 and 5622 are shut down, and no P06 process is running. The round-2 block below is historical.

**Paper:** `manuscript/main.pdf`, retitled *Absent or Unchanged? What Android Lets an Agent's Memory Know After a Lifecycle Gap*. 14 pp total; body ends on p.10 (12-page limit); references p.10–12; appendix (proofs + 4 tables) after them. 59 references, all cited. 0 undefined refs/citations, 0 overfull boxes, no `??` placeholders. Build: pdflatex → bibtex → pdflatex ×2 (TeX Live 2020, pgfplots compat 1.17).

**REAL vs PLACEHOLDER:** every results number, table and figure is generated from real emulator runs by `cd artifact && make all` (analyze.py → render.py → LaTeX). `make check-determinism` prints DETERMINISTIC. E8 uses a real local LLM (Ollama qwen2.5:7b). The AndroidWorld census (E5) is code inspection. No simulated numbers.

## Headline results (round 2)
| What | Result |
|---|---|
| E1 evidence (API 33, 105 trials; API 35, 30) | MediaStore generation, RawContacts VERSION, call-log LAST_MODIFIED (falls on delete), file mtimes; nothing for SMS/calendar edits/settings. Same on API 35. |
| Deferral | median 10.0 s (API 33; none <10.00 s, n=337); 13.5 s (API 35, p5 13.2 s, n=129; source says 10 s, extra undiagnosed); FGS 7.5 ms |
| E2 v3 (239 bg + 90 FGS on API 33; 48 on API 35) | process-ending gaps: event-only 644/660 missed (98%), restart-aware 0/660 (refreshes all 16), LeaseMem 0/660 (refreshes 10.6). In-epoch, early decision: restart-aware 88/559, LeaseMem 0. FGS in-epoch 0/149. LeaseMem 0 misses in every condition (0/1219 bg late, 0/934 FGS, 0/510 API 35). |
| Long gaps (freezer 600 s debounce; stepped Doze; ~10 min) | all callbacks delayed, none lost by the late decision (0/60 missed late; 3/60 early) |
| Cost (provider-readable) | LeaseMem 43 ms vs global 32 ms vs restart-aware 23 ms per decision; LeaseMem slower in 92% of decisions |
| E8 LLM-derived facts (44 trials) | after kill, p=0.3: 7.82 s → 4.00 s per decision; p=0.1: 7.13 → 2.16 s; no stale. No gap: restart-aware faster (2.18 vs 2.98 s) |
| E3 v2 (240 trials) | stale 40/40 without boundary re-validation; with it 0/130 (change before check), 3/13 (overlapping check→effect), 0/17 (after effect); check→effect median 28 ms |
| E6 v2 | VERSION adapter detects 15/15 transient + 15/15 persistent clock set-backs; TS adapter accepts stale 15/15 transient |
| Reboot | Contacts DB empty after 1/90 reboots; MediaStore version never changed |

## Deliverables
| Deliverable | State |
|---|---|
| manuscript (rewritten for round 2), generated/ tables, figs, macros | done |
| review/response-round1.md | final |
| artifact (client v3, trig, mut; drivers e1–e8; analyze/render; Makefile) | done |
| raw data `artifact/results/raw/` (round 2) + `raw/round1/` (short-hold condition) | complete; see `raw/PARTIAL_ROUND2.md` (no partial data remain) |
| RUNLOG, notes ledger, README | updated |

## Not done (stated in paper/response)
- No physical-device replication (none available); no OEM build.
- No platform prototype (dropped-notification token / public generations).
- No per-fact census rescope (app-level only); no per-aggregate deltas; 30-day tombstone horizon untested.
- The extra ~3.5 s of Android 15 deferral is not diagnosed.

Last updated: 2026-11-08.

## P06 parked (2026-11-09)
The user parked P06 after three MobiSys Rejects (round 3: 2/2/2/2, 7 Required). Open interpretation errors from round 3, to fix if this is ever resumed: the Android 15 "longer deferral" is the cached-apps freezer (freeze_debounce_timeout=10000 in logs/run_r2d_5622.log); the E9 post-thaw callbacks arrive at the +14 s decision because the client re-froze. Reviewers suggest a short-paper venue (HotMobile).

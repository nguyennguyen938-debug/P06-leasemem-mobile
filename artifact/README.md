# P06: Android cached-fact evidence after lifecycle gaps

This is the named local artifact for the platform measurement paper, authored by Xuan-Bach Le. It contains historical Android 13/15 campaigns, separately identified revision campaigns, source/APK provenance, raw outcomes, retained failures, analysis, and manuscript inputs. No physical handset, production deployment, public hosting, or independent third-party reproduction is claimed.

## Rebuild results and paper

From `artifact/`:

```sh
make all
python3 revision/test_oracle.py
make check-determinism
```

Python 3 standard library is sufficient for analyses. The paper additionally requires pdfLaTeX, BibTeX, acmart, TikZ/PGFPlots and Poppler. `make all` regenerates historical results, the revised independent oracle summaries and tables, then compiles with explicit 10pt. Missing results no longer produce placeholder tables. Historical analyses use their archived validity rules; revision data are never combined with them.

To rebuild Android apps:

```sh
export ANDROID_HOME=/path/to/android-sdk
export JAVA_HOME=/path/to/jdk17
make apks
```

SDK requirements: platform android-33, build-tools 34.0.0, platform-tools. The manifest-only API-35 FGS compatibility fixture compiles against API 33 and targets 35; it was tested on runtime API 35, not on current Android hardware. The included `app/k.jks` is a public test-only signing key (password `android`, alias `k`), never a production credential. Use fresh test devices/AVDs or the documented read-only overlays; an unrelated installation may have an incompatible signing key.

## Evidence boundaries

- Historical E1–E13: `results/raw/`, `results/RUNLOG.md`, archived client v2/v3 APKs and the historical source archive. Original results include the non-atomic fact-then-watermark protocol.
- Revision: `results/revision-20261115/`. The final cooperative conformance cohort, stock race campaign, host comparison, timestamp attempts, supplemental tests and deployment campaigns are separately named and hashed.
- `revision/PROTOCOL.md` describes the strict UNKNOWN fallback and the cooperative transactional provider. The stock provider query/snapshot/epoch contracts remain unestablished; richer evidence is logged without enabling strict stock reuse.
- `revision/ADAPTERS.md` links pinned source evidence and limitations. Source similarity is not treated as deployed binary equivalence.
- `revision/provenance/` contains a manual nine-task query/validator inspection at AndroidWorld commit `55ddaf5edc6f6c25673aed343907d5b9dca66f84`. Historical census CSVs are frozen inputs to normal rebuilding. Recomputing the full census requires that external checkout and its dependencies; the selected inspected sources are included.
- The matched host memoization arm measures base input reads. E8's summed-call cost model is retained separately from the two-model resumed Android draft tasks in `followup/agent_tasks.py`; the latter measures execution through an Android file effect.
- `revision/oracle.py` and `test_oracle.py` independently check snapshot/version/interval consistency, preserve whole trials, and distinguish later-read ambiguity from proven stale certification.
- `revision/README.md` documents live setup and the eight-hour setup/experiment cap. P06-only ports 5620/5622 are used. SDK images and TeX/JDK tools are external dependencies, not included in the ZIP.

Initial failed/superseded campaigns and build logs are retained. `results/revision-20261115/exclusions.json` inventories their dispositions. The named follow-up package preserves raw bytes and includes a hash manifest. The execution report distinguishes clean local extraction from independent external retrieval, which is not claimed. See `followup/README.md` for the follow-up evidence and current commands.

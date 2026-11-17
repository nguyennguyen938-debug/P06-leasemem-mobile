# P06 revision experiments

The accepted scope is Android 13/15 emulator evidence, an eight-hour setup/live-run cap, and no handset or public upload. `results/revision-20261115/execution.json` records the timing boundary. AVDs are launched with read-only overlays; never use personal devices or unrelated emulator ports. `run.py` only accepts the P06 allowlist (5620/5622).

From the paper root, build `artifact/app/client/build.sh LeaseMemClient-v4` and the mutator. `revision/build-env.sh` accepts externally supplied `ANDROID_HOME` and `JAVA_HOME`. Required SDK components: platform android-33, build-tools 34.0.0, platform-tools; live reruns additionally require Android 13 and 15 Google APIs arm64 images and an emulator. Host Python uses the standard library. Main paper rebuilding needs a working TeX installation and Poppler.

Live commands (use new output suffixes/directories; recorded campaign files are never overwritten):

```
python3 artifact/revision/run.py emulator-5620 reference --n 20 --suffix=-new
python3 artifact/revision/run.py emulator-5620 stock --n 20 --suffix=-new
python3 artifact/revision/run.py emulator-5620 tick --n 20 --suffix=-new
python3 artifact/revision/run.py emulator-5620 host --n 30 --suffix=-new
```

Repeat on 5622 for Android 15. Setup grants restricted test permissions/app-ops; this is not evidence of ordinary app deployability. `deployment.py` tests actual bound-service/process states. `supplement.py` revokes only the test client's permissions, resets Contacts in the isolated overlay, and temporarily changes/restores emulator time; do not run it on personal data. It does not emulate arbitrary provider database restoration.

`oracle.py` reads fixed archived campaign filenames, independently checks complete reference attempts and generates the revised statistics/tables. `test_oracle.py` includes deliberately inconsistent and wrongly ordered evidence. `ADAPTERS.md` states which stock obligations remain unmet. `PROTOCOL.md` documents helper and provider interfaces. `provenance/sample.json` records a deterministic nine-task manual source inspection, not new task executions.

The initial reference cohort used an Application initializer in the provider process as well as the main process. The final build skips client initialization in `:reference`; final reference regressions separately verify that change. Stock, transport and deployment cohorts did not call the reference provider after their fresh package installs. Their measured APKs are retained separately, so results are not silently attributed to a later build.

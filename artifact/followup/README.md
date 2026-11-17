# P06 review follow-up (2026-11-16)

The paper adopts direction A: platform measurement. `StampCheck` labels the optimistic baseline in the staged campaigns; `EvCheck` labels strict snapshot certification. Raw policy IDs and frozen source archives retain their original names. They are not reassigned to the strict protocol.

## Rebuild recorded evidence

From `artifact`, run `make all`, `python3 revision/test_oracle.py`, `python3 followup/test_results.py`, and `make check-determinism`. Python standard library, pdfLaTeX/BibTeX and Poppler suffice; no network/model/device is needed for recorded-result rebuilding. The main document uses 10pt, names Xuan-Bach Le and includes the approved LLM-prose disclosure. `followup/analyze.py` generates the expanded deployment table and resumed-task table; `revision/oracle.py` generates independent trial counts and paired transport CIs. The old six-change deployment records remain raw evidence; the expanded persistent-system cohort is also 20 Contacts trials on Android 13.

## Live emulator reproduction

Use isolated P06 AVD overlays only (ports 5620/5622, Android 13/15). Set `ANDROID_HOME`, `ANDROID_AVD_HOME`, `JAVA_HOME` (JDK 17) and `SA` as documented by the shared SDK setup; the driver defaults to the sibling `shared-android/sdk`. All apps use a **public test signing key** (`app/k.jks`, password `android`). Do not install onto personal data. Build with `make apks`; assistant target SDK is 35, ordinary client target SDK is 33. API-35 FGS fixtures have typed/missing-type variants.

1. Start P06Avd and P06Avd35 read-only, with no snapshot or audio, at their allowlisted ports. Runtime build fingerprints and measured APK hashes are in the setup records.
2. Choose a fresh output directory by changing `OUT`/`D` in the follow-up drivers; output JSONL files use exclusive creation. Never overwrite a recorded campaign.
3. Run `python3 followup/deployment.py emulator-5620` and its 5622 counterpart. Each performs 20 Contacts mutations for background-unfrozen, background-frozen, FGS and system-bound assistant. It restarts the client after changing DeviceConfig, records before/during cgroup freezer state, reads event files from root without waking the process, then thaws via Activity launch. Invalid/error records are retained and excluded explicitly.
4. After the deployment collectors exit, run `python3 followup/fgs35.py` on 5622, then `python3 followup/agent_tasks.py`. The FGS script is the existing compatibility harness with a different output location. It does not test background-start or six-hour eligibility.
5. The task study uses local Ollama at `127.0.0.1:11434`, `qwen2.5:7b` and `llama3.2:3b`. `agent-models.json` pins local model digests. Each model has 24 trials per force-stop/p=.1, force-stop/p=.3 and no-gap/p=.3 schedule. Three structured draft tasks rotate; all three policies share an observation and write schedule, with randomized resumed-arm order. Pairing is within each model; cross-model schedules are not paired. Raw requests/responses, Android write/readback outcomes, all timings and errors are retained. No messages or calls are sent.

For the persistent-system cohort, boot the owned Android 13 AVD with both `-read-only` (userdata overlay) and `-writable-system` (temporary system copy). After boot, enable adb root and remount, push `app/persist/build/LeaseMemPersist.apk` under `/system/priv-app/LeaseMemPersist/`, set mode 644 and reboot. Run `python3 followup/persistent.py` after boot completes. It verifies root, grants test permissions, restarts the persistent process so observer registration follows the grants, checks SYSTEM/PERSISTENT flags and oom adjustment -800, and collects 20 Contacts changes. The first setup failed because root was requested during reboot and did not persist; `persist.log` retains that timeout, while `persist-retry.log` and the exclusive JSONL contain the valid run.

## Interpretation

- The deployment follow-up isolates **Contacts** callback timing, not all seven source-specific latency distributions. The Android 15 13.5s source-probe and 18.0s no-gap policy medians remain mixed-state measurements. Their curve is removed from the age comparison, and they are not called a larger ContentService constant.
- Strict stock certification remains disabled. Evidence-mode task execution refreshes/rederives on UNKNOWN; no fallback is counted as a certified reuse.
- Task latency is directly measured from resumed input acquisition through Android file write/readback, excluding the shared anchor/gap prefix. Task success checks exact structured inputs and task identity plus a nonempty draft, not natural-language quality. A stale action uses the pre-gap inputs after they changed; other wrong inputs are separately logged.
- The 10-output E8 summed-cost workload is retained separately. The new 3-task two-model study is not pooled with it or represented as an AndroidWorld completion study.
- Hold sensitivity is an analytic model (one quiescent write, unfrozen process, 10s delivery delay), not field data or a concurrency guarantee.
- Physical Pixel/OEM replication, physical energy, natural deployment frequencies, current-target background/long-duration service eligibility and public independent artifact retrieval remain open. Direction B's stock-contract and conditional-effect mechanism extensions are not claimed.

## Packaging

The named follow-up ZIP under `submission/` preserves source/raw bytes and verifies SHA-256 hashes on clean extraction. It includes measured APKs, source snapshots, exclusions and model metadata; SDK/AVD images and local environments are omitted. The snapshot of changed source is supplemental to immutable cohort archives. Local clean rebuilding is not independent remote retrieval. Registration is prepared locally only; the execution report and registration packet record portal access limitations.

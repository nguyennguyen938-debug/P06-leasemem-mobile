# PHYS-PROTOCOL: experiments on one physical Android phone

Status: **draft of 2026-11-18, written before the test phone was connected.** Every cell that says
*not yet probed* is filled from the B0 probe (`b0-probe-*.jsonl`) once the phone is attached; until then nothing in
this file is a measurement. Owner: Experiment role. Readers: Theory (`06b-physical-setup.tex`, Evidence column of
the guidance table), Results (`artifact/physical/analyze_phys.py`).

Task codes (B0 to B12) are those of `PLAN-dien-thoai-that.md` section 4.

## 1. Device

| Field | Value | Source |
|---|---|---|
| Manufacturer, model | not yet probed | B0 probe `identity` |
| `ro.build.fingerprint` | not yet probed | B0 probe `identity`; also in every record |
| Android release, SDK level, security patch | not yet probed | B0 probe `identity` |
| Build type (`ro.build.type`), `ro.debuggable` | not yet probed (a retail phone is `user`, `0`) | B0 probe `identity` |
| Root (adbd runs as uid 0) | not yet probed (expected: no) | B0 probe `adb_root`; `rooted` in every record |
| Serial | used only in the allowlist (`P06_SERIALS`), not published | |

Only this one phone is used. It is a test phone: the experiments write and delete contacts, SMS, call-log rows,
images, calendar events, a Settings key and files, and B0 clears the Contacts provider once.

## 2. Host

- Windows 11 Pro, Git Bash, Python 3.14 (standard library; `psutil` only for the host load average).
- JDK 17 at `D:/Java/jdk-17.0.21+9`; Android SDK at `D:/Android/Sdk` (platform-tools 37.0.1, build-tools 34.0.0,
  platforms android-33 and android-35). No environment variable is set permanently; each command sets
  `JAVA_HOME=D:/Java/jdk-17.0.21+9` and `ANDROID_HOME=D:/Android/Sdk`.
- Drivers find adb as `$ADB`, else `$ANDROID_HOME/platform-tools/adb.exe`, else `adb` on PATH (`lmdrv._find_adb`).
- Allowlist: `lmdrv.ALLOWED` = the two P06 emulators plus every entry of `P06_SERIALS` (comma separated). An entry
  matches the adb serial or the phone's `ro.serialno`, so one entry admits the phone over USB and over wireless
  debugging, whose adb serial changes per connection. Set `P06_SERIALS` to the output of
  `adb shell getprop ro.serialno`. Any other device makes every driver stop with an error before any command.
- `P06_PORT` (default 18764): host port forwarded to the client's loopback test socket for `revision/run.py`
  campaigns on the phone (the emulators keep 18760 and 18762).
- Host sleep: `lmdrv.Dev` calls `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` so Windows does not
  sleep while a driver runs (replaces macOS `caffeinate`; no power setting is changed).
- Host load in records (`host_load`): `os.getloadavg` where it exists, else `psutil.getloadavg`, whose first value
  after process start is zeros.
- The historical `artifact/driver/run_*.sh` scripts are records of the macOS emulator runs and are not ported;
  `artifact/physical/campaign.py` replaces them for the phone.

### Building the APKs (Git Bash)

```
export JAVA_HOME=D:/Java/jdk-17.0.21+9 ANDROID_HOME=D:/Android/Sdk
cd artifact/app/client && bash ./build.sh LeaseMemClient-v4
cd ../trig && bash ./build.sh;  cd ../mut && bash ./build.sh;  cd ../assist && bash ./build.sh
```

`revision/build-env.sh` selects `d8.bat` and `apksigner.bat` on Windows. The signing key `artifact/app/k.jks` is a
new test key made by the JDK 17 keytool on 2026-11-18 (alias `k`, password `android`, excluded by `.gitignore`); the
emulator APKs were signed with another key, so APK hashes differ from the emulator RUNLOG entries. Builds are not
byte-reproducible (signing time), so `campaign.py` records the SHA-256 of the APKs it installs in every RUNLOG line.
Build of 2026-11-18 01:49 (all six apps built without error; the four installed ones):

| APK | SHA-256 |
|---|---|
| `client/build/LeaseMemClient-v4.apk` | `bb17d2802c5193796381390f3d52945b0d772ad39e7bf2a72d1ce6c4ac10cf77` |
| `mut/build/LeaseMemMut.apk` | `6fba64b4271cd3eb7aecb929144f78a8d954c752250e5a470b2b40eda3d46ae2` |
| `trig/build/LeaseMemTrig.apk` | `703878114c9fa5e770e23a632b8536245842d9ed574f95f6155306dc0c964de1` |
| `assist/build/LeaseMemAssist.apk` | `6bbc55939c25ffb1530bda41b27f1b9d748afc9dbdf463aee2835076fbb293e1` |

Client code relative to the emulator v4: two additions only, the `stamp` batch mode (B6) and the `effect` op plus
`reads` and `wall_offset_ms` in batch results (B7). Existing modes and ops are unchanged.

## 3. Phone preparation (once, before B0)

1. The user confirms the phone is a test phone (stop point 1). No personal account is signed in.
2. Screen lock: None. The reboot gap needs the client and providers to run after boot without an unlock
   (credential-encrypted storage stays locked until the first unlock).
3. Developer options: USB debugging on; authorize the host. For daytime tasks on the charger, "Stay awake" may be on
   (it applies only while charging, so it does not affect B11 and B12).
4. Wireless debugging paired with the host (needed for B11 and B12, which run unplugged): on the phone, Developer
   options, Wireless debugging, Pair device with pairing code; on the host `adb pair <ip>:<pair port>` then
   `adb connect <ip>:<port>`. The `<ip>:<port>` serial is passed to `--serial`.
5. Experiment takes `projects/p06-leasemem/phone.lock` before the first command and returns it after each session.

## 4. Root-dependent steps and their replacements on a phone without root

| On the emulators (adbd as root) | On a phone without root | Code |
|---|---|---|
| `adb root` | refused by a production adbd and harmless; `rooted` is read as `id -u == 0` | `lmdrv.Dev.rooted` |
| `cat /data/data/<pkg>/files/...` (command results, mutator results, `mem.json`, `trig.log`) | `run-as <pkg> sh -c '...'`; all P06 apps are `android:debuggable="true"` | `Dev.app_sh`, `Dev.cat`, `Dev.rm` |
| cgroup v2 `cgroup.freeze` via `/proc/<pid>/cgroup` | same files if the shell may read them (shell is normally in the `readproc` group); otherwise `isFrozen=` in `dumpsys activity processes <pkg>` | `Dev.frozen`; each record names the source in `frozen_method` (`cgroup` or `dumpsys`) |
| `kill -9 <pid>` from the shell | `run-as <pkg> kill -9 <pid>` (same uid as the app) | `Dev.kill9` |
| `date @<t>` (B10 clock rollback) | per the plan the clock part of B10 runs only on a rooted phone; otherwise it is cut and the emulator result stays, labeled emulator-only. B0 also probes `cmd alarm set-time <ms>`; if that moves the clock without root, it is reported at S1 as an option and not used without the user's approval | `e6_pitfalls.py` runs the clock part only when `rooted`; B0 probe `clock_set_back` |
| persistent system app (`followup/persistent.py`) | not possible without root; emulator result stays | not run |

## 5. Commands probed in B0

`artifact/physical/b0_probe.py` runs each probe, restores what it changed, and writes one record per probe
(`ok`, `detail`). Result column: filled from `b0-probe-*.jsonl`.

| Probe | Command(s) | Needed by | If it fails | Result |
|---|---|---|---|---|
| `identity` | `getprop` model, fingerprint, release, SDK, patch, build type | all | | not yet probed |
| `adb_root` | `adb root`, `id` | all (selects root or run-as path) | run-as path | not yet probed |
| `run_as` | `run-as org.leasemem.client id` | all | no driver can read results: stop and report | not yet probed |
| `read_app_files` | client command round trip, `files/mem.json` | all | as above | not yet probed |
| `appops` | `appops set <pkg> MANAGE_EXTERNAL_STORAGE allow`, `WRITE_SMS allow` | fixtures, files, SMS | drop the affected source, record | not yet probed |
| `fixtures_ensure_base` | mutator `ensure` (all seven sources) | all | drop the failing source | not yet probed |
| `mutations_all_kinds` | mutator `mutate` for every source and kind | B2, B3, B4, B5, B9 | drop that source or kind | not yet probed |
| `client_probe_candidates` | client `PROBE` (candidate stamps) | B3 | candidates returning ERR are dropped, as on the emulator | not yet probed |
| `proc_cgroup_read` | `cat /proc/<pid>/cgroup`, `cgroup.freeze`, `oom_score_adj` | B1, B2, B5, B11 | `dumpsys` fallback | not yet probed |
| `dumpsys_isFrozen` | `dumpsys activity processes <pkg>` | fallback for the above | if both fail: cut B1 frozen mode, B2 freezer, B5 | not yet probed |
| `freezer_debounce_2s` | `device_config set_sync_disabled_for_tests until_reboot`; `device_config put activity_manager_native_boot freeze_debounce_timeout 2000`; wait for frozen | B1 frozen, B2 freezer, B5 | B5 and frozen modes use the default debounce (about 10 min) if the phone still freezes; otherwise cut | not yet probed |
| `am_kill` | `am kill <pkg>` in background | B2 kill | cut gap | not yet probed |
| `am_force_stop` | `am force-stop <pkg>` | B2 force-stop | cut gap | not yet probed |
| `sigkill_kill9` | `run-as <pkg> kill -9 <pid>` | B2 SIGKILL (FGS only, not in B2 list) | cut | not yet probed |
| `pm_revoke_grant` | `pm revoke` / `pm grant READ_CONTACTS` | B2 revoke | cut gap | not yet probed |
| `battery_unplug` | `dumpsys battery unplug`, `reset` | B2 Doze | cut Doze gap | not yet probed |
| `doze_force_idle_deep` | `dumpsys deviceidle force-idle deep`, `get deep`, `unforce` | B2 Doze | cut Doze gap | not yet probed |
| `standby_bucket` | `am set-standby-bucket <pkg> restricted`, `get-standby-bucket` | B2 bucket | cut gap | not yet probed |
| `assistant_role` | `cmd role add-role-holder android.app.role.ASSISTANT org.leasemem.assist 0`, `dumpsys voiceinteraction` (`mBound=true`) | B1 assistant | cut assistant mode | not yet probed |
| `clock_set_back` | `settings put global auto_time 0`; `date @t` or `cmd alarm set-time`; restore | B10 clock (rooted only) | cut clock part (emulator result stays) | not yet probed |
| `charge_counter` | `dumpsys battery` (`Charge counter`), `/sys/class/power_supply/battery/charge_counter` | B12 | B12 uses battery level (1% steps) | not yet probed |
| `batterystats` | `dumpsys batterystats --reset`, `--charged <pkg>` | B12 | B12 keeps charge counter only | not yet probed |
| `screen_sleep_wake` | `input keyevent KEYCODE_SLEEP` / `WAKEUP`, `dumpsys power` | B2 long Doze, B12 | | not yet probed |
| `wireless_debugging` | `adb devices -l`, `adb_wifi_enabled`, `service.adb.tls.port` | B11, B12 | B11 and B12 cannot run unplugged: cut | not yet probed |
| `pm_clear_contacts` (with `--destructive`) | `pm clear com.android.providers.contacts`, then fixtures again | Contacts reset scenario | record | not yet probed |
| `reboot` (with `--destructive`, last) | `adb reboot`, boot time, client state after boot | B2 reboot | cut gap | not yet probed |

B0 then runs one complete B2 no-gap trial (`b0-trial-none-*.jsonl`) as the end-to-end check.

## 6. Experiments

All tasks run through one command (Git Bash, from `artifact/`):

```
JAVA_HOME=D:/Java/jdk-17.0.21+9 ANDROID_HOME=D:/Android/Sdk P06_SERIALS=<ro.serialno> \
  python physical/campaign.py <TASK> --serial <adb serial> [--pilot] [--night 1|2] [--dry-run]
```

`--dry-run` prints the exact driver commands without touching a device. `--pilot` runs 2 trials per condition (S2).
Before every task except B1, B4, B6 and B7 (which call it themselves), `campaign.py` runs `revision/run.py`'s
`setup` (install client v4 and mutator with `-g`, appops, grants, fixtures), installs the trigger app, and stops the
client's foreground service. Output directory: `artifact/results/physical-<YYYYMMDD>/` (start date of the command),
files named with the start time `HHMM`; driver logs in `logs/`. Daytime tasks run on the charger; Doze is emulated
with `dumpsys battery unplug` (B2) as on the emulator.

| Task | Driver | Trials and conditions | Seeds | Raw file(s) |
|---|---|---|---|---|
| B0 | `physical/b0_probe.py --destructive`; `driver/e2v3_gaps.py none 1` | all probes of section 5; one full trial | 2611000 | `b0-probe-HHMM.jsonl`, `b0-trial-none-HHMM.jsonl` |
| B1 | `followup/deployment.py` | Contacts: background unfrozen, background frozen (debounce 2 s), FGS, bound assistant, 20 each; MediaStore and call log: background unfrozen and FGS, 20 each | as in the emulator driver | `deploy-<source>-HHMM.jsonl` (pilot: `deploy-pilot-<source>-HHMM.jsonl`) |
| B3 | `driver/e1_coverage.py` | 30 trials; every source independently insert, update, delete or unchanged | 2611301 | `coverage-HHMM.jsonl` |
| B2 | `driver/e2v3_gaps.py` | 25 trials for each of: none, freeze, dozeidle, bucket, unregister, kill, forcestop, perm, reboot; background client; decisions at +2 s and +14 s; hold U(0, 30) s | 2611201 to 2611209 | `gaps-<gap>-HHMM.jsonl` |
| B4 | `revision/run.py stock` | 20 trials for each of the seven sources | 20261115 (driver) | `stock-<serial>-HHMM.jsonl` |
| B9 | `driver/e3v2_boundary.py` | 100 changes spread over the window, 25 changes without boundary check, 20 + 20 no-change controls; then 100 changes in [-10, +40] ms around the check | 2611901, 2611902 | `boundary-HHMM.jsonl`, `boundary-band-HHMM.jsonl` |
| B10 | `driver/e6_pitfalls.py` | SMS `_id` reuse 50, same-second mtime 50; clock rollback 50 only if rooted | 2611001 | `pitfalls-HHMM.jsonl` |
| B5 | `driver/e9_frozen.py` | 10 holds, each frozen for 600 s after the first change, debounce 2 s; overnight, on the charger | 2611501 | `frozen-HHMM.jsonl` |
| B12 | `physical/b12_battery.py` | per night 4 equal blocks inside 6 h from unplug (minus 10 min margin); night 1 FGS on, off, on, off; night 2 off, on, off, on; screen off; unplugged; wireless | | `battery-night<N>-HHMM-samples.jsonl`, `battery-night<N>-HHMM-block<k>-<arm>-batterystats.txt` |
| B11 | `physical/b11_statelog.py` | 24 h, one sample every 5 s, unplugged, wireless; client as a plain background app | | `statelog-HHMM.jsonl` |
| B6 | `revision/run.py host --arms refresh,validate,stamp,relay,memo` | 30 trials for each write pattern: none, one, continuous | 20261115 (driver) | `host-<serial>-HHMM.jsonl` |
| B7 | `physical/b7_continuous.py` | 30 trials; arms refresh, stamp, relay under a continuous Contacts writer | 2611701 | `continuous-HHMM.jsonl` |

Pre-commands applied by `campaign.py`: B2 sets the freezer debounce to 2000 ms for `freeze` and to 600000 ms for every
other gap (with DeviceConfig sync disabled until reboot) and stops the FGS; B5 sets 2000 ms; B3, B9, B10 stop the FGS;
B11 and B12 restore the phone's defaults (`dumpsys battery reset`, `dumpsys deviceidle unforce`,
`settings put global auto_time 1`, `device_config delete activity_manager_native_boot freeze_debounce_timeout`,
`device_config set_sync_disabled_for_tests none`).

B12 night procedure: charge to full on USB with wireless debugging connected; start
`campaign.py B12 --night N --serial <ip:port>` before going to bed; the script waits for the unplug (up to 12 h),
which starts the 6-hour budget; the user unplugs the phone at bedtime and plugs it back in on waking. Reconnecting a
charger ends the current block (marked incomplete) and the run.

B11 usage mode (decision at S1, user): either the user carries the test phone for one day as a secondary phone with
no personal account, or a script opens common apps on a fixed schedule (script not written yet). The paper states
which one was used.

## 7. JSONL schema

### Fields added to every record

| Field | Meaning |
|---|---|
| `device` | `ro.product.manufacturer` + `ro.product.model` |
| `fingerprint` | `ro.build.fingerprint` |
| `sdk` | `ro.build.version.sdk` |
| `serial` | adb serial used (USB serial or `<ip>:<port>`) |
| `rooted` | adbd ran as uid 0 |
| `plugged` | `dumpsys battery` reported a charger when the record was created. Under `dumpsys battery unplug` this is the emulated value. B11 and B12 read it per sample. |

All other fields keep the emulator schema of the same driver; the additions per file are below. Errors are kept in
the record (`error`, often `trace`); trials rejected by the driver keep `invalid` (for example `not_frozen`).

| File | Record shape | Additions to the emulator schema |
|---|---|---|
| `b0-probe-*.jsonl` | one record per probe | new: `probe`, `ok`, `detail`, `seconds`, `trace` on exceptions |
| `deploy-*.jsonl` (B1) | `followup/deployment.py` | `source` (`contacts`, `media`, `calllog`); `frozen_method` in `before` and each `states` entry; `host_load` from psutil on Windows. **Results:** a callback counts for the trial's `source`, so filter events on `e['src'] == r['source']` and keep Contacts tables on `source == 'contacts'` |
| `gaps-*.jsonl` (B2) | `driver/e2v3_gaps.py`, protocol `v3` | `frozen_method` for freezer trials |
| `coverage-*.jsonl` (B3) | `driver/e1_coverage.py` | none beyond the common fields |
| `stock-*.jsonl` (B4) | `revision/run.py stock` | none |
| `frozen-*.jsonl` (B5) | `driver/e9_frozen.py` | `frozen_method` |
| `host-*.jsonl` (B6) | `revision/run.py host` | arm `stamp`; every batch result gains `reads` (fact to `[read_start_ns, read_end_ns]`, elapsedRealtimeNanos, re-read facts only) and `wall_offset_ms`; `stamp` batches gain `stamp` (source to `confirmed` or the refresh reason: `no_stamp`, `no_prior_stamp`, `stamp_moved`, `clock_jump`, `racy_mtime`, `support_missing`, `stamp_error`) and `stamp_reads` |
| `continuous-*.jsonl` (B7) | new, see below | |
| `boundary-*.jsonl` (B9) | `driver/e3v2_boundary.py`, protocol `v2` | none |
| `pitfalls-*.jsonl` (B10) | `driver/e6_pitfalls.py` | `exp: clock` records absent when not rooted |
| `statelog-*.jsonl` (B11) | new, see below | |
| `battery-night*-samples.jsonl` (B12) | new, see below | |
| `<serial>-setup-<ns>.json` | setup metadata (not JSONL) | install results, APK SHA-256, `dumpsys activity settings`, common fields |

### B7 `continuous-*.jsonl`

`trial`, `seed`, `start`, `end`; `anchor` (arm to batch result filling the cache); `truth0` (refresh batch before
the writer starts); `mutations` (each `{src, kind, tag, t_pre, t_dev, did}`, device `System.currentTimeMillis`;
the update sets LM Dana's number to `"+1555" + tag` and commits inside `[t_pre, t_dev]`); `arms_order`; `arms` (arm to
`{batch, effect}`; `effect` has `value`, `wall_ms`, `effect_start_ns`, `effect_end_ns`); `writer_errors`;
`truth_after`. The oracle is `classify()` in `artifact/physical/b7_continuous.py` (self-check:
`python physical/b7_continuous.py --selftest`): certification instant = `wall_offset_ms + end_ns/1e6` of the
batch, action instant = `effect.wall_ms`; class `fresh`, `stale_at_certification`, `stale_at_action_only`, or
`ambiguous` when an instant falls inside a commit window; `read_ok` checks a re-read value against the truth at the
ends of its read interval.

### B11 `statelog-*.jsonl`

One `kind: start` record (`hours`, `period_s`, freezer settings), then `kind: sample` records: `i`, `t` (host epoch
s), `alive`, `pid`, `oom_score_adj`, `frozen` (`1`, `0`, or null), `frozen_method`, `bucket`, `doze_deep`,
`doze_light`, `plugged`, `level`, `charge_uAh`, `wakefulness`, or `error` when the sample failed (adb drop); a final
`kind: end` with the sample count. Kills and restarts are read from `pid` changes and `alive`; time while `plugged`
is analyzed separately.

### B12 `battery-night*-samples.jsonl`

`kind`: `start` (order, budget, battery at start), `unplugged` (`t_unplug`, `deadline`, `block_s`), `block_start`,
`sample`, `block_end` (each with `plugged`, `level`, `charge_uAh`, `voltage_mV`, `temp_dC`, `doze_deep`,
`client_pid`, `fgs`, `wakefulness`, or `error`), `block` (summary: `block`, `arm`, `t_start`, `t_end`, `duration_s`,
`charge_start_uAh`, `charge_end_uAh`, `level_start`, `level_end`, `complete`, `stopped`, `fgs_start`, `fgs_end`),
`abort`, `end`. Raw BatteryStats text per block in the `.txt` files. Drain per hour is computed only from complete
blocks.

## 8. Validity and exclusions

- Raw files are created with `open(..., 'x')`; nothing is overwritten, appended to across runs, or deleted. A failed
  run keeps its file and gets a RUNLOG line; exclusions are listed in `artifact/results/RUNLOG.md` and applied by the
  analysis, never by editing raw data.
- Every `campaign.py` command appends to RUNLOG: time, task, label, command, device, fingerprint, `rooted`,
  `plugged`, APK SHA-256 (first 12 hex digits), minutes, exit code, records, records with `error`, records marked
  `invalid`, output and log paths.
- Freezer-dependent trials are valid only if the frozen state was observed (existing `not_frozen` rule).
- B11 and B12 records with `plugged: true` are analyzed as charging time, separately.
- No emulator number replaces a phone number. A command that fails on the phone cuts the dependent experiment; the
  cut is listed at S1 for the user (stop point 3).

## 9. Known limitations of the method

- One device and one Android build; no claim beyond it.
- Polling perturbs what it measures: B11 issues one short `adb shell` every 5 s over Wi-Fi, B12 one sample every
  5 min. Both are logged; B12 is the same for both arms.
- Daytime Doze is emulated (`dumpsys battery unplug`, `force-idle`), as on the emulator; only B11 and B12 observe
  unplugged behavior.
- If `cgroup.freeze` is unreadable, frozen state comes from ActivityManager's own flag (`frozen_method: dumpsys`).
- All callback and commit times are device clock times; the host clock is used only for waits and B11 or B12 sample
  times.

## 10. Results macros fed by each file

The 24 macro names are those of the registry in `artifact/physical/analyze_phys.py` (commit 192e448, owned by
Results); this protocol keeps all of them and renames none. `analyze_phys.py` reads only top-level
`artifact/results/physical-*/*.jsonl`; every file pattern below is a top-level file there.

| Macro | Task | Raw file pattern under `results/physical-<YYYYMMDD>/` |
|---|---|---|
| `PhysDevice`, `PhysFingerprint`, `PhysRooted` | all | `*.jsonl` (common fields `device`, `fingerprint`, `rooted` in every record) |
| `PhysDeployTrials`, `PhysDeployBgMedian`, `PhysDeployFgMedian`, `PhysDeployAssistMedian`, `PhysDeployFrozenBeforeThaw` | B1 | `deploy*.jsonl`, i.e. `deploy-contacts-HHMM.jsonl`, `deploy-media-HHMM.jsonl`, `deploy-calllog-HHMM.jsonl`, and pilot `deploy-pilot-<source>-HHMM.jsonl` |
| `PhysCoverageTrials` | B3 | `coverage-HHMM.jsonl` |
| `PhysGapTrials`, `PhysGapNoneFcl` | B2 | `gaps-<gap>-HHMM.jsonl` (`gap` field inside each record) |
| `PhysRaceTrials`, `PhysRaceStale` | B4 | `stock-<serial>-HHMM.jsonl` |
| `PhysBoundaryTrials`, `PhysCteMs` | B9 | `boundary-HHMM.jsonl`, `boundary-band-HHMM.jsonl` (`band` field inside) |
| `PhysSmsReuse`, `PhysMtimeSame` | B10 | `pitfalls-HHMM.jsonl` (`exp` field: `sms_reuse`, `mtime`, `clock`) |
| `PhysFrozenHolds`, `PhysFrozenKilled` | B5 | `frozen-HHMM.jsonl` |
| `PhysStateHours`, `PhysStateFrozenPct`, `PhysStateKillsPerHour` | B11 | `statelog-HHMM.jsonl` |
| `PhysBatteryFgsMahPerHour`, `PhysBatteryBgMahPerHour` | B12 | `battery-night<N>-HHMM-samples.jsonl` (complete `kind: block` records) |

Notes for Results:

1. `deploy*.jsonl` mixes three sources. The current `deploy()` counts only Contacts callbacks
   (`e['src'] == 'contacts'`), so media and call-log trials would be read as Contacts trials without a callback.
   Filter on the record's `source` field (`contacts` for the existing `PhysDeploy*` macros); media and call-log
   trials need their own macros if the paper reports them.
2. Pilot files (`deploy-pilot-*`, 2 trials per mode) match `deploy*.jsonl` and are ordinary valid trials from the
   same protocol; exclude them by file name if the paper should count only the main run.
3. Other top-level files that `*.jsonl` also loads: `b0-probe-*`, `b0-trial-none-*`, `host-*` (B6),
   `continuous-*` (B7). They carry the common fields, so `PhysDevice` and the like are unaffected. B6 and B7 have no
   macro yet; names are Results' choice when those tasks run.

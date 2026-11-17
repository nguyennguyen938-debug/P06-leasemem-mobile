# PHYS-PROTOCOL: experiments on one physical Android phone

Status: **draft of 2026-11-18, written before the phone was connected.** Every cell that says *not yet probed* is
filled from the B0 probe (`b0-probe-*.jsonl`) once the phone is attached; until then nothing in this file is a
measurement. Owner: Experiment role. Readers: Theory (`06b-physical-setup.tex`, Evidence column of the guidance
table), Results (`artifact/physical/analyze_phys.py`).

Task codes (B0 to B12) are those of `PLAN-dien-thoai-that.md` section 4.

**The phone is the user's personal phone.** Every experiment runs inside a separate Android user named `P06 Test`
with no account signed in; nothing reads, writes or deletes data of the owner's user (user 0). Section 4 lists how
the code enforces this.

## 1. Device

| Field | Value | Source |
|---|---|---|
| Manufacturer, model | not yet probed | B0 probe `identity` |
| `ro.build.fingerprint` | not yet probed | B0 probe `identity`; also in every record |
| Android release, SDK level, security patch | not yet probed | B0 probe `identity` |
| Build type (`ro.build.type`), `ro.debuggable` | not yet probed (a retail phone is `user`, `0`) | B0 probe `identity` |
| Root | never used; the drivers refuse a phone whose adbd runs as root | `rooted` in every record |
| Test user id, restrictions | not yet probed (`no_sms`, `no_outgoing_calls` expected) | B0 probe `user_info`; `user_id` in every record |
| Serial | used only in the allowlist (`P06_SERIALS`), never written to data | |

## 2. Host

- Windows 11 Pro, Git Bash, Python 3.14 (standard library; `psutil` only for the host load average). The host is
  also a personal machine: the drivers write only in the repo (`artifact/results/physical-*`, `build/`), and E7 dry
  runs only in `build/`.
- JDK 17 at `D:/Java/jdk-17.0.21+9`; Android SDK at `D:/Android/Sdk` (platform-tools 37.0.1, build-tools 34.0.0,
  platforms android-33 and android-35). Each command sets `JAVA_HOME=D:/Java/jdk-17.0.21+9` and
  `ANDROID_HOME=D:/Android/Sdk`; nothing is set permanently.
- Drivers find adb as `$ADB`, else `$ANDROID_HOME/platform-tools/adb.exe`, else `adb` on PATH (`lmdrv._find_adb`).
- Allowlist: `lmdrv.ALLOWED` = the two P06 emulators plus every entry of `P06_SERIALS` (comma separated), matched
  against the adb serial or the phone's `ro.serialno`, so one entry admits the phone over USB and over wireless
  debugging. Set `P06_SERIALS` to the output of `adb shell getprop ro.serialno`.
- `P06_PORT` (default 18764): host port forwarded to the client's loopback test socket for `revision/run.py`.
- Host sleep: `lmdrv.Dev` calls `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` while a driver runs
  (replaces macOS `caffeinate`; no power setting changes). Host load (`host_load`): `os.getloadavg`, else
  `psutil.getloadavg` (its first value after process start is zeros).
- The historical `artifact/driver/run_*.sh` scripts record the macOS emulator runs and are not ported;
  `artifact/physical/campaign.py` replaces them for the phone.

### Building the APKs (Git Bash)

```
export JAVA_HOME=D:/Java/jdk-17.0.21+9 ANDROID_HOME=D:/Android/Sdk
cd artifact/app/client && bash ./build.sh LeaseMemClient-v4
cd ../trig && bash ./build.sh;  cd ../mut && bash ./build.sh;  cd ../assist && bash ./build.sh
```

`revision/build-env.sh` selects `d8.bat` and `apksigner.bat` on Windows. The signing key `artifact/app/k.jks` is a
test key made by the JDK 17 keytool on 2026-11-18 (alias `k`, password `android`, excluded by `.gitignore`), so APK
hashes differ from the emulator RUNLOG entries. Builds are not byte-reproducible (signing time); `campaign.py`
records the SHA-256 of the APKs in every RUNLOG line. Build of 2026-11-18 02:19:

| APK | SHA-256 |
|---|---|
| `client/build/LeaseMemClient-v4.apk` | `f378a76475a003bbea07cccaf569b233d5d33271a5361a905fe664f00cffe20a` |
| `mut/build/LeaseMemMut.apk` | `657deb7c2bccff7e7c3a92d3df071be01dafcc27493fb9e9ad7f5ec71d820dd1` |
| `trig/build/LeaseMemTrig.apk` | `dd87a55e80f4a0a1c345e96758c3f5d515ae0290b82c7a58c2e7931ab6677a8a` |
| `assist/build/LeaseMemAssist.apk` | `0dcc8b692b717068185094b1891799fdcee78fb4eb1cf9d2ac002e936be8cfd9` |

App code relative to the emulator v4: (1) the `stamp` batch mode (B6) and the `effect` op with `reads` and
`wall_offset_ms` in batch results (B7); (2) shared storage is this user's (`Environment.getExternalStorageDirectory()`,
`/storage/emulated/<user>`) instead of the fixed `/storage/emulated/0`; (3) each app reads `files/p06_exclude` and
then neither reads, observes nor writes the listed sources. With no exclusion file (the emulators) behavior is
unchanged.

## 3. Preparing the personal phone (the user does this, once, before B0)

1. **Developer options and USB debugging, in the owner's user** (they apply to the whole phone; a secondary user
   usually cannot open Developer options). Settings, About phone, tap Build number seven times. Then Settings,
   System, Developer options: turn on USB debugging. Connect the cable and allow the host when the phone asks.
2. **Create the test user.** Settings, System, Multiple users (on some phones: Users and accounts, Users): add a
   user, name it exactly `P06 Test`. Do not sign in to any Google or other account in it. Skip every account step
   of its setup wizard.
3. **No screen lock for `P06 Test`.** In that user: Settings, Security, Screen lock: None. The owner's lock screen
   stays as it is; nothing changes it.
4. **Keep phone calls and SMS off for `P06 Test`.** In the owner's user: Settings, System, Multiple users, `P06 Test`:
   leave "Turn on phone calls and SMS" off. With it on, Android shares the owner's call and SMS history with that
   user; with it off, the user carries the `no_sms` and `no_outgoing_calls` restrictions, which the drivers check.
5. **Wireless debugging (for B11 and B12, which run unplugged), in the owner's user.** Developer options, Wireless
   debugging, Pair device with pairing code. On the host: `adb pair <ip>:<pair port>` (enter the code), then
   `adb connect <ip>:<port>`; pass `<ip>:<port>` to `--serial`. Then switch to `P06 Test`; B0 records whether the
   wireless connection survives the switch (`wireless_debugging`).
6. **Do not change anything else.** No app, account or setting of the owner's user is needed.
7. **Before every run** switch the phone to `P06 Test` and leave it there. Each run checks that `P06 Test` is the
   foreground user before starting and every 10 s while it runs, and stops (restoring settings) if it is not.
8. **Reboots** (the B2 reboot gap and the B0 reboot probe) run only when the user allows them for that run
   (`--allow-reboot`). After a reboot the phone shows the owner's lock screen; the driver does nothing until the user
   switches to `P06 Test` again (up to 30 min), then continues.
9. **At the end** `campaign.py cleanup` removes the P06 apps from `P06 Test`. The user deletes the `P06 Test` user
   only when they choose to.

Experiment takes `projects/p06-leasemem/phone.lock` before the first command and returns it after each session.

## 4. Isolation in code, and replacements for root-only steps

| Rule | How the code enforces it |
|---|---|
| Only user `P06 Test`, never user 0 | `lmdrv.Dev` reads `pm list users`, takes the one user named `P06 Test`, refuses if there is none, several, or it is user 0. Every user-scoped command (`am`, `pm`, `appops`, `content`, `cmd role`, `run-as`, `install`) is built by `Dev.u()` or `Dev.install()`, which add `--user <id>`; `Dev.sh()` refuses any command that lacks that `--user` or names another user (`lmdrv.phone_violation`). |
| Test user in the foreground | `Dev` checks `am get-current-user` at start, before every activity start and HOME key; `campaign.py` checks before every step and every 10 s while a driver runs, and stops the run otherwise. |
| No owner data | SMS is never read, observed or written (the SMS provider is shared by all users); the call log only when the test user has `no_outgoing_calls`. Shared storage is `/storage/emulated/<test user>`; the shell never touches `/sdcard`, `/storage` or `/data`. Before writing fixtures, `b0_setup.py` counts rows in the test user that P06 did not write (contacts, call log, calendar, images; `_id` only, count only) and stops if any exists. Only the client's own uid lines of BatteryStats are read; only the test user's block of `dumpsys user` leaves the phone; `dumpsys` is limited to an allowlist. |
| Banned on this phone | `pm clear`, user creation or removal, user switching by the driver, clock changes (`date`, `cmd alarm`, `auto_time`), root, `setprop`, `svc`, `locksettings`, `content insert/update/delete` from the shell, `batterystats --reset`, `settings` other than P06's keys `lm_mode` and `lm_target`, `device_config` other than the freezer debounce and its sync mode, `adb uninstall/push/pull`, and `pm uninstall` of anything but `org.leasemem.*` in the test user. `Dev.sh()` and `Dev.adb()` refuse them. |
| Device-wide settings are temporary | Drivers run only under `campaign.py` (`Dev` refuses otherwise on the phone). Before the first step it saves the freezer debounce, the DeviceConfig sync mode, Settings.Global `lm_mode` and `lm_target`, and the standby buckets of the P06 apps to `build/phone-restore-state.json`; after every step, also a failed or stopped one, it restores them and resets battery and Doze overrides, the test user's assistant role and READ_CONTACTS grants. `campaign.py --restore` does it from the file if the runner died. |
| Reboot only with consent | `Dev.adb('reboot')` refuses unless the run has `--allow-reboot`; afterwards `Dev.after_reboot()` only waits for the user. |
| Static check | `python physical/test_user_scope.py`: scans every file `campaign.py` runs for user-scoped command strings without `--user` and for banned commands, and checks the runtime guard on fixed examples. |

Root-only emulator steps and what the phone uses instead:

| On the emulators (adbd as root) | On the phone | Code |
|---|---|---|
| `cat /data/data/<pkg>/files/...` | `run-as --user <id> <pkg> sh -c '...'` (all P06 apps are debuggable) | `Dev.app_sh`, `Dev.cat`, `Dev.rm` |
| cgroup `cgroup.freeze` via `/proc/<pid>/cgroup` | same files if readable; otherwise `isFrozen=` of the test user's process in `dumpsys activity processes <pkg>` | `Dev.frozen`, `frozen_method` |
| `kill -9 <pid>` from the shell | `run-as --user <id> <pkg> kill -9 <pid>` | `Dev.kill9` |
| `pidof <pkg>` | `pidof` filtered to the process whose uid belongs to the test user | `Dev.pid` |
| clock rollback (B10), Contacts reset, persistent system app | not run on the phone; emulator results stay, labeled emulator-only | `e6_pitfalls.py` runs the clock part only on a rooted P06 emulator |

## 5. Commands probed in B0

`physical/b0_setup.py` prepares the test user (checks, installs with `--user`, grants and appops in that user,
exclusion files, fixtures through the mutator in that user); it never creates or switches users.
`physical/b0_probe.py` then runs each probe, restores what it changed, and writes one record per probe (`ok`,
`detail`). Result column: filled from `b0-probe-*.jsonl`.

| Probe | Command(s), all in the test user | Needed by | If it fails | Result |
|---|---|---|---|---|
| `identity` | `getprop` model, fingerprint, release, SDK, patch, build type | all | | not yet probed |
| `user_info` | `am get-current-user`, `am get-started-user-state <id>`, restrictions from the test user's `dumpsys user` block | all | stop | not yet probed |
| `install_user` | `pm list packages --user <id> org.leasemem` | all | stop | not yet probed |
| `run_as_user` | `run-as --user <id> org.leasemem.client id` (uid in the test user) | all | stop: no driver can read results | not yet probed |
| `read_app_files` | client command round trip; `files/mem.json`, `files/p06_exclude` | all | stop | not yet probed |
| `content_user` | `content query --user <id>` raw contacts named `LM ...` | fixtures check | stop | not yet probed |
| `appops` | `appops get --user <id> org.leasemem.mut MANAGE_EXTERNAL_STORAGE` | files source | drop files | not yet probed |
| `fixtures_ensure_base` | mutator `ensure` in the test user | all | drop the failing source | not yet probed |
| `mutations_all_kinds` | mutator `mutate` for every allowed source and kind | B2, B3, B4, B5, B9 | drop that source or kind | not yet probed |
| `client_probe_candidates` | client `PROBE` (candidate stamps) | B3 | ERR candidates dropped, as on the emulator | not yet probed |
| `process_user` | uid of the client process (`stat -c %u /proc/<pid>`), `oom_score_adj` | B1, B2, B11 | | not yet probed |
| `proc_cgroup_read` | `cat /proc/<pid>/cgroup`, `cgroup.freeze` | freezer state | `dumpsys` fallback | not yet probed |
| `dumpsys_isFrozen` | `dumpsys activity processes <pkg>` | fallback | if both fail: cut B1 frozen mode, B2 freezer, B5 | not yet probed |
| `freezer_debounce_2s` | `device_config put activity_manager_native_boot freeze_debounce_timeout 2000` (sync disabled until reboot); test-user client frozen | B1 frozen, B2 freezer, B5 | cut those | not yet probed |
| `am_kill` | `am kill --user <id> <pkg>` | B2 kill | cut gap | not yet probed |
| `am_force_stop` | `am force-stop --user <id> <pkg>` | B2 force-stop | cut gap | not yet probed |
| `sigkill_kill9` | `run-as --user <id> <pkg> kill -9 <pid>` | FGS SIGKILL gap | cut | not yet probed |
| `pm_revoke_grant` | `pm revoke` / `pm grant --user <id> ... READ_CONTACTS` | B2 revoke | cut gap | not yet probed |
| `battery_unplug` | `dumpsys battery unplug`, `reset` | B2 Doze | cut Doze gap | not yet probed |
| `doze_force_idle_deep` | `dumpsys deviceidle force-idle deep`, `get deep`, `unforce` (device-wide) | B2 Doze | cut Doze gap | not yet probed |
| `standby_bucket` | `am set-standby-bucket --user <id> <pkg> restricted`, `get-standby-bucket` | B2 bucket | cut gap | not yet probed |
| `assistant_role` | `cmd role add-role-holder --user <id> android.app.role.ASSISTANT org.leasemem.assist 0`, `mBound=true` | B1 assistant | cut assistant mode | not yet probed |
| `charge_counter` | `dumpsys battery` (`Charge counter`) | B12 | B12 uses battery level (1% steps) | not yet probed |
| `batterystats_uid` | client uid lines of `dumpsys batterystats --charged org.leasemem.client` (no reset) | B12 | B12 keeps charge counter only | not yet probed |
| `screen_sleep_wake` | `input keyevent KEYCODE_SLEEP` / `WAKEUP`, `mWakefulness` | B2 long Doze, B12 | | not yet probed |
| `wireless_debugging` | `adb devices -l` transports, `service.adb.tls.port` | B11, B12 | cut B11, B12 | not yet probed |
| `reboot` (only with `--allow-reboot`, last) | `adb reboot`; foreground user and test-user state after boot; time until the user switched back | B2 reboot | cut gap | not yet probed |

Removed for the personal phone: root, clock rollback, and clearing the Contacts provider (`pm clear`) are neither
probed nor run. B0 then runs one complete B2 no-gap trial (`b0-trial-none-*.jsonl`) as the end-to-end check.

## 6. Experiments

All tasks run through one command (Git Bash, from `artifact/`), with `P06 Test` in the foreground:

```
JAVA_HOME=D:/Java/jdk-17.0.21+9 ANDROID_HOME=D:/Android/Sdk P06_SERIALS=<ro.serialno> \
  python physical/campaign.py <TASK> --serial <adb serial> [--pilot] [--night 1|2] [--allow-reboot] [--dry-run]
python physical/campaign.py --restore --serial <adb serial>      # only if a run died before restoring
python physical/campaign.py cleanup --serial <adb serial>        # end of the campaign
```

`--dry-run` prints the driver commands without a device. `--pilot` runs 2 trials per condition (S2). Before every
task `campaign.py` runs `b0_setup.py` (idempotent) and stops the client's foreground service. Output directory:
`artifact/results/physical-<YYYYMMDD>/` (start date of the command), files named with the start time `HHMM`; driver
logs in `logs/`. Daytime tasks run on the charger; Doze is emulated with `dumpsys battery unplug` (B2), restored
after each step.

| Task | Driver | Trials and conditions | Seeds | Raw file(s) |
|---|---|---|---|---|
| B0 | `physical/b0_probe.py`; `driver/e2v3_gaps.py none 1` | probes of section 5; one full trial | 2611000 | `b0-probe-HHMM.jsonl`, `b0-trial-none-HHMM.jsonl` |
| B1 | `followup/deployment.py` | Contacts: background unfrozen, background frozen (debounce 2 s), FGS, bound assistant, 20 each; MediaStore and call log: background unfrozen and FGS, 20 each (call log only if not excluded) | as in the emulator driver | `deploy-<source>-HHMM.jsonl` |
| B3 | `driver/e1_coverage.py` | 30 trials; every allowed source independently insert, update, delete or unchanged | 2611301 | `coverage-HHMM.jsonl` |
| B2 | `driver/e2v3_gaps.py` | 25 trials for each of: none, freeze, dozeidle, bucket, unregister, kill, forcestop, perm, reboot (only with `--allow-reboot`); background client; decisions at +2 s and +14 s; hold U(0, 30) s | 2611201 to 2611209 | `gaps-<gap>-HHMM.jsonl` |
| B4 | `revision/run.py stock` | 20 trials for each allowed source (no SMS) | 20261115 (driver) | `stock-<serial>-HHMM.jsonl` |
| B9 | `driver/e3v2_boundary.py` | 100 changes over the window, 25 changes without boundary check, 20 + 20 no-change controls; then 100 changes in [-10, +40] ms. The effect is a call-log row: skipped if the call log is excluded | 2611901, 2611902 | `boundary-HHMM.jsonl`, `boundary-band-HHMM.jsonl` |
| B10 | `driver/e6_pitfalls.py` | same-second mtime 50. SMS `_id` reuse and clock rollback are not run on the phone (emulator results stay) | 2611001 | `pitfalls-HHMM.jsonl` |
| B5 | `driver/e9_frozen.py` | 10 holds, each frozen for 600 s after the first change, debounce 2 s; overnight, on the charger | 2611501 | `frozen-HHMM.jsonl` |
| B12 | `physical/b12_battery.py` | per night 4 equal blocks inside 6 h from unplug (minus 10 min margin); night 1 FGS on, off, on, off; night 2 off, on, off, on; screen off; unplugged; wireless | | `battery-night<N>-HHMM-samples.jsonl` |
| B11 | `physical/b11_statelog.py` | 24 h, one sample every 5 s, unplugged, wireless; client as a plain background app in `P06 Test`, which stays in the foreground | | `statelog-HHMM.jsonl` |
| B6 | `revision/run.py host --arms refresh,validate,stamp,relay,memo` | 30 trials for each write pattern: none, one, continuous | 20261115 (driver) | `host-<serial>-HHMM.jsonl` |
| B7 | `physical/b7_continuous.py` | 30 trials; arms refresh, stamp, relay under a continuous Contacts writer | 2611701 | `continuous-HHMM.jsonl` |

Pre-commands applied by `campaign.py` (all restored after the step): B2 sets the freezer debounce to 2000 ms for
`freeze` and 600000 ms for every other gap (DeviceConfig sync disabled until reboot) and stops the FGS; B5 sets
2000 ms; B0, B3, B9, B10 stop the FGS.

B12 night procedure: charge to full on USB with wireless debugging connected and `P06 Test` in the foreground; start
`campaign.py B12 --night N --serial <ip:port>` before going to bed; the script waits for the unplug (up to 12 h),
which starts the 6-hour budget; the user unplugs the phone at bedtime and plugs it back in on waking. Reconnecting a
charger ends the current block (marked incomplete) and the run.

B11 usage mode (decision at S1, user): `P06 Test` must stay in the foreground for the 24 hours, so either the user
carries the phone in `P06 Test` for one day (no personal account, so most personal apps are unavailable), or a script
opens apps installed in `P06 Test` on a fixed schedule (script not written yet). The paper states which one was used.

## 7. JSONL schema

### Fields added to every record

| Field | Meaning |
|---|---|
| `device` | `ro.product.manufacturer` + `ro.product.model` |
| `fingerprint` | `ro.build.fingerprint` |
| `sdk` | `ro.build.version.sdk` |
| `user_id` | Android user id of `P06 Test` (0 on the emulators) |
| `excluded_sources` | sources the apps and drivers never touch on this device (`sms`, and `calllog` unless calls are off for the test user) |
| `user_no_sms`, `user_no_outgoing_calls` | the test user's restrictions as read at the start of the run |
| `serial` | adb serial used (USB serial or `<ip>:<port>`) |
| `rooted` | adbd ran as uid 0 (always false on the phone) |
| `plugged` | `dumpsys battery` reported a charger when the record was created. Under `dumpsys battery unplug` this is the emulated value. B11 and B12 read it per sample. |

All other fields keep the emulator schema of the same driver; the additions per file are below. Errors are kept in
the record (`error`, often `trace`); trials rejected by the driver keep `invalid` (for example `not_frozen`).

**Pilot files.** A run with `--pilot` puts `pilot` into every output name: `deploy-pilot-<source>-HHMM`,
`gaps-pilot-<gap>-HHMM`, `coverage-pilot-HHMM`, `stock-<serial>-pilot-HHMM`, `boundary-pilot-HHMM`,
`boundary-pilot-band-HHMM`, `pitfalls-pilot-HHMM`, `frozen-pilot-HHMM`, `host-<serial>-pilot-HHMM`,
`continuous-pilot-HHMM`, `statelog-pilot-HHMM`, `battery-pilot-night<N>-HHMM-samples`. `analyze_phys.py` keeps every
file with `pilot` in its name out of the main numbers.

| File | Record shape | Additions to the emulator schema |
|---|---|---|
| `b0-probe-*.jsonl` | one record per probe | new: `probe`, `ok`, `detail`, `seconds`, `trace` on exceptions |
| `deploy-*.jsonl` (B1) | `followup/deployment.py` | `source` (`contacts`, `media`, `calllog`); `frozen_method` in `before` and each `states` entry; `binding` holds only the `leasemem` and `mBound` lines of `dumpsys voiceinteraction`. **Results:** a callback counts for the trial's `source` (`e['src'] == r['source']`); Contacts tables use `source == 'contacts'` |
| `gaps-*.jsonl` (B2) | `driver/e2v3_gaps.py`, protocol `v3` | `frozen_method` for freezer trials; `user_back_s` (reboot gap: time until the user switched back to `P06 Test`) |
| `coverage-*.jsonl` (B3) | `driver/e1_coverage.py` | `muts` covers only the allowed sources |
| `stock-*.jsonl` (B4) | `revision/run.py stock` | cases only for allowed sources |
| `frozen-*.jsonl` (B5) | `driver/e9_frozen.py` | `frozen_method` |
| `host-*.jsonl` (B6) | `revision/run.py host` | arm `stamp`; every batch result gains `reads` (fact to `[read_start_ns, read_end_ns]`, elapsedRealtimeNanos, re-read facts only) and `wall_offset_ms`; `stamp` batches gain `stamp` (source to `confirmed` or the refresh reason: `no_stamp`, `no_prior_stamp`, `stamp_moved`, `clock_jump`, `racy_mtime`, `support_missing`, `stamp_error`) and `stamp_reads` |
| `continuous-*.jsonl` (B7) | new, see below | |
| `boundary-*.jsonl` (B9) | `driver/e3v2_boundary.py`, protocol `v2` | none |
| `pitfalls-*.jsonl` (B10) | `driver/e6_pitfalls.py` | only `exp: mtime` records on the phone |
| `statelog-*.jsonl` (B11) | new, see below | |
| `battery-night*-samples.jsonl` (B12) | new, see below | |
| `setup-HHMMSS.json` and `<serial>-setup-<ns>.json` | setup metadata (not JSONL) | install results, APK SHA-256, restrictions, rows not written by P06 before and after setup (`foreign_before`, `foreign_after`, counts only), fixtures, common fields |

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
s), `alive`, `pid` (the test user's client process), `oom_score_adj`, `frozen` (`1`, `0`, or null),
`frozen_method`, `bucket`, `current_user`, `doze_deep`, `doze_light`, `plugged`, `level`, `charge_uAh`,
`wakefulness`, or `error` when the sample failed (adb drop); a final `kind: end` with the sample count. Kills and
restarts are read from `pid` changes and `alive`; time while `plugged` is analyzed separately.

### B12 `battery-night*-samples.jsonl`

`kind`: `start` (order, budget, battery at start), `unplugged` (`t_unplug`, `deadline`, `block_s`), `block_start`,
`sample`, `block_end` (each with `plugged`, `level`, `charge_uAh`, `voltage_mV`, `temp_dC`, `doze_deep`,
`client_pid`, `fgs`, `wakefulness`, or `error`; `block_start` and `block_end` also `batterystats_uid`: the client
uid's lines of `dumpsys batterystats --charged`), `block` (summary: `block`, `arm`, `t_start`, `t_end`,
`duration_s`, `charge_start_uAh`, `charge_end_uAh`, `level_start`, `level_end`, `complete`, `stopped`, `fgs_start`,
`fgs_end`), `abort`, `end`. BatteryStats is never reset and never dumped whole. Drain per hour is computed only from
complete blocks.

## 8. Validity and exclusions

- Raw files are created with `open(..., 'x')`; nothing is overwritten, appended to across runs, or deleted. A failed
  run keeps its file and gets a RUNLOG line; exclusions are listed in `artifact/results/RUNLOG.md` and applied by the
  analysis, never by editing raw data.
- Every `campaign.py` command appends to RUNLOG: time, task, label, command, device, fingerprint, user id, `rooted`,
  `plugged`, APK SHA-256 (first 12 hex digits), minutes, exit code, records, records with `error`, records marked
  `invalid`, whether the run was stopped (foreground user changed), restore result, output and log names. Skipped
  parts (reboot gap without consent, B9 or B1 call log when excluded) get their own RUNLOG line.
- Freezer-dependent trials are valid only if the frozen state was observed (existing `not_frozen` rule).
- B11 and B12 records with `plugged: true` are analyzed as charging time, separately.
- No emulator number replaces a phone number. A command that fails on the phone cuts the dependent experiment; the
  cut list goes to the user at S1 (stop point 3).

## 9. Known limitations of the method

- One device and one Android build; no claim beyond it. Experiments run in a secondary Android user; process,
  freezer, Doze and callback behavior is that of a secondary user in the foreground.
- SMS is not measured on the phone, and the call log only if calls are off for the test user; those sources keep
  their emulator results.
- Polling perturbs what it measures: B11 issues one short `adb shell` every 5 s over Wi-Fi, B12 one sample every
  5 min; the foreground-user watchdog adds one read every 10 s. All are logged; B12 is the same for both arms.
- Daytime Doze is emulated (`dumpsys battery unplug`, `force-idle`), as on the emulator; only B11 and B12 observe
  unplugged behavior.
- If `cgroup.freeze` is unreadable, frozen state comes from ActivityManager's own flag (`frozen_method: dumpsys`).
- All callback and commit times are device clock times; the host clock is used only for waits and B11 or B12 sample
  times.

## 10. Results macros fed by each file

The 24 macro names are those of the registry in `artifact/physical/analyze_phys.py` (owned by Results); this
protocol keeps all of them and renames none. `analyze_phys.py` reads only top-level
`artifact/results/physical-*/*.jsonl` and leaves out every file with `pilot` in its name.

| Macro | Task | Raw file pattern under `results/physical-<YYYYMMDD>/` |
|---|---|---|
| `PhysDevice`, `PhysFingerprint`, `PhysRooted` | all | `*.jsonl` (common fields `device`, `fingerprint`, `rooted` in every record) |
| `PhysDeployTrials`, `PhysDeployBgMedian`, `PhysDeployFgMedian`, `PhysDeployAssistMedian`, `PhysDeployFrozenBeforeThaw` | B1 | `deploy*.jsonl`, i.e. `deploy-contacts-HHMM.jsonl`, `deploy-media-HHMM.jsonl`, `deploy-calllog-HHMM.jsonl` |
| `PhysCoverageTrials` | B3 | `coverage-HHMM.jsonl` |
| `PhysGapTrials`, `PhysGapNoneFcl` | B2 | `gaps-<gap>-HHMM.jsonl` (`gap` field inside each record) |
| `PhysRaceTrials`, `PhysRaceStale` | B4 | `stock-<serial>-HHMM.jsonl` |
| `PhysBoundaryTrials`, `PhysCteMs` | B9 | `boundary-HHMM.jsonl`, `boundary-band-HHMM.jsonl` (`band` field inside) |
| `PhysSmsReuse`, `PhysMtimeSame` | B10 | `pitfalls-HHMM.jsonl` (`exp` field). On the phone only `mtime` exists; `PhysSmsReuse` has no phone data (SMS not touched) |
| `PhysFrozenHolds`, `PhysFrozenKilled` | B5 | `frozen-HHMM.jsonl` |
| `PhysStateHours`, `PhysStateFrozenPct`, `PhysStateKillsPerHour` | B11 | `statelog-HHMM.jsonl` |
| `PhysBatteryFgsMahPerHour`, `PhysBatteryBgMahPerHour` | B12 | `battery-night<N>-HHMM-samples.jsonl` (complete `kind: block` records) |

Notes for Results:

1. `deploy*.jsonl` mixes three sources; filter on the record's `source` field (`contacts` for the existing
   `PhysDeploy*` macros); media and call-log trials need their own macros if the paper reports them.
2. Other top-level files that `*.jsonl` also loads: `b0-probe-*`, `b0-trial-none-*`, `host-*` (B6),
   `continuous-*` (B7). They carry the common fields, so `PhysDevice` and the like are unaffected. B6 and B7 have no
   macro yet; names are Results' choice when those tasks run.
3. `PhysSmsReuse` stays without phone data by design (SMS is shared with the owner's user); the paper keeps the
   emulator result for it.

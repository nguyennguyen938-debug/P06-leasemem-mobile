# PHYS-PROTOCOL: experiments on rented phones (AWS Device Farm)

Status: **draft of 2026-11-18 (G4).** The AWS project exists and the three uploads of the first run passed Device
Farm's checks (section 2); **no run has been scheduled and no device minute has been used.** Every cell that says
*not yet probed* is filled from the first B0 run (`b0-probe-*.jsonl`), which is sent only when the user agrees; until
then nothing here is a measurement of a phone. Owner: Experiment role. Readers: Theory (`06b-physical-setup.tex`,
Evidence column), Results (`artifact/physical/analyze_phys.py`).

Task codes (B0 to B13) are those of `PLAN-dien-thoai-that.md` section 5.

**Superseded: the personal-phone protocol.** The E5 to E7 version ran every experiment in an Android user `P06 Test`
on the user's own Galaxy A35. That phone cannot create a second user (`pm get-max-users` = 1), so it is never used:
its serial `RFCXA0TTMPP` is blocked in every mode of the drivers (section 4). The isolation code of that version
stays in `lmdrv.py` (personal mode) but no run uses it.

## 1. Devices

| Field | Value | Source |
|---|---|---|
| Main model | Google Pixel 8, Android 15 (`arn:aws:devicefarm:us-west-2::device:DE5BD47FF3BD42C3A14BF7A6EFB1BFE7`), the Android version of the paper's emulator | chosen by the Orchestrator from `list-devices`, 2026-11-18 |
| Backup model (if the main one is busy; never mixed within one task) | Google Pixel 9, Android 15 (`arn:aws:devicefarm:us-west-2::device:BCDA2B2CE0B54ABEA1F8B34A54A2752C`) | same |
| Second-manufacturer model (B13, only if minutes remain) | Samsung Galaxy S25, Android 15 (`arn:aws:devicefarm:us-west-2::device:69977E819F314BD481F194580E8EFC16`) | same |
| `ro.build.fingerprint`, SDK, security patch | not yet probed | B0 probe `identity`; `fingerprint`, `sdk` in every record |
| Root | no; the drivers refuse a rooted adbd | `rooted` in every record |
| Physical units | a run may land on another unit of the same model | `device_instance` in every record |
| Test host | Device Farm `amazon_linux_2` (the Android host of Device Farm's current curated Appium Python specs), Python 3.12 (`devicefarm-cli use python 3.12`), the host's adb | B0 probe `host` |

The phones are wiped by Device Farm between runs and hold no personal data, so experiments run in user 0 with every
source (Contacts, SMS, call log, MediaStore, calendar, Settings, files).

## 2. How a run works

- **AWS access (rules of the project's CLAUDE.md).** Only the AWS CLI (`C:/Program Files/Amazon/AWSCLIV2/aws`,
  2.36.29), only `aws devicefarm ...`, always `--profile devicefarm --region us-west-2` (the profile has root
  rights, so no other AWS service, no SDK, no `aws configure`, no credentials printed or copied). `aws/devicefarm.py`
  passes every request as `--cli-input-json` (API member names) and moves files through the presigned URLs that
  `aws devicefarm` returns (standard urllib). If the CLI reports an expired login, it stops and asks the user to run
  `aws login --profile devicefarm --region us-west-2`.
- **Project.** `mobisys-thu-nghiem`, `arn:aws:devicefarm:us-west-2:478825889366:project:83e7e695-4f56-4afc-bca4-cb04dea963ec`;
  the account's `maxJobTimeoutMinutes` is 150.
- **Mode.** Custom test environment, test type `APPIUM_PYTHON` with the client APK as the app under test (Device Farm
  installs it; the drivers install all four APKs themselves and, if Device Farm's copy was re-signed, replace it).
  The test spec `artifact/aws/testspec.yml` (host `amazon_linux_2`) runs `physical/campaign.py`, which reaches the
  phone only through adb. There is no adb from the user's computer to a rented phone.
- **Test package format** (checked by Device Farm at upload): a zip with `requirements.txt` (`pytest==8.3.4`; Device
  Farm rejects an empty file and checks the pytest version; the test spec installs nothing from it, the drivers use
  only the standard library), `tests/test_p06_entry.py` (Device Farm requires a `test*` file in `tests/`; it only
  checks that the campaign entry point is present and is never run by the spec) and `tests/P06/artifact/<path>` for
  the 16 allowlisted files (the P06 driver code and the four APKs). No wheelhouse: Python 3 packages do not need one.
  `aws/package.py` builds it and refuses a member that looks like an AWS key. The fixtures are written on the phone
  by the mutator app; nothing else of the user's computer is uploaded.
- **Uploads of the first run** (2026-11-18, 0 device minutes, `aws/devicefarm.py upload`):

| File | Type | Upload ARN (project prefix `arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/`) | Status |
|---|---|---|---|
| `LeaseMemClient-v4.apk` (SHA-256 `f378a764...`) | `ANDROID_APP` | `e7f7dd9d-b697-4c61-836f-9d142696bc85` | SUCCEEDED |
| `p06-tests-20261118-153552.zip` (SHA-256 `10028192...`) | `APPIUM_PYTHON_TEST_PACKAGE` | `713e702a-099f-4113-9826-f83b0613abc0` | SUCCEEDED |
| `p06-testspec-20261118-153424.yml` (SHA-256 `42eac2ae...`, same as `aws/testspec.yml`) | `APPIUM_PYTHON_TEST_SPEC` | `c396c072-a24b-4152-9e96-89fb5bfd6510` | SUCCEEDED |
| two earlier packages | `APPIUM_PYTHON_TEST_PACKAGE` | `c47ce5bf-...` (no `test*` file), `eaddcbb8-...` (empty `requirements.txt`) | FAILED, left unused |

- **One run = one `campaign.py` invocation** with an execution timeout close to its estimate (20 % and 3 min of
  slack, at most 150 min). Device Farm passes the task in two run-level environment variables: `P06_TASK` (B0,
  B1, ...) and `P06_ARGS` (`--pilot`, `--only`, `--trials`, `--part`, `--allow-reboot`, and `--budget-min` = timeout
  minus 4, so no step starts too late). Each driver flushes after every trial, so a run cut short keeps its trials.
- **Every run prepares the wiped phone itself** (`physical/b0_setup.py` through `campaign.py`): install the four APKs
  in user 0 with all runtime permissions (`adb install --user 0 -r -g`), appops `MANAGE_EXTERNAL_STORAGE` and
  `WRITE_SMS`, grants, and the fixtures of all seven sources through the mutator app.
- **Records carry the run's identity.** `device_instance` (`$DEVICEFARM_DEVICE_UDID`), `device_arn`
  (`$DEVICEFARM_DEVICE_ARN`) and `run_arn` (`$DEVICEFARM_RUN_ARN`), read by `lmdrv` on the test host.
- **Minutes.** The cap is **300 device minutes for all of P06** (the user's decision); the account's free minutes
  (995.88 left on 2026-11-18) are shared with other projects, and minutes beyond them cost 0.17 USD each. The ledger
  `artifact/results/aws-minutes.jsonl` (append-only) gets a `scheduled` line per run (its timeout) and a `final` line
  with Device Farm's `deviceMinutes` (total, metered, unmetered); `RUNLOG.md` gets the same numbers. A run counts with
  its final total, or with its timeout while it has no final line. `run` refuses a run if used + reserved + its
  timeout > 300, and when 2 runs are already active.
- **Stopping.** `run` watches every run: on an errored or failed result, on an overrun of its timeout by 10 min, on
  Ctrl-C, or when the runner itself ends before the run completes, it calls `stop-run` at once and reads the status
  back (STOPPING or COMPLETED), then records the minutes and fetches what exists.
- **Commands** (Windows, Git Bash, from `artifact/`):

```
python aws/package.py                                   # build/aws/p06-tests-<stamp>.zip, manifest, testspec copy
python aws/devicefarm.py upload <file> <TYPE> [...]     # create-upload, PUT, wait for SUCCEEDED or FAILED (0 min)
python aws/devicefarm.py plan B2 --allow-reboot         # prints --args="..." --estimate N per run (no AWS call)
python aws/devicefarm.py run <TASK> --device pixel8 --app-arn <A> --package-arn <P> --spec-arn <S> [--args="..."] [--estimate N] [--timeout M]
python aws/devicefarm.py minutes                        # used, reserved, left under 300
python aws/devicefarm.py stop <run ARN>                 # stop-run and read the status back
```

- **The first run (B0, short), not sent:** it runs only after the user agrees. Pixel 8, Android 15, about 15 min
  expected, timeout 25 min: the 31 probes of section 5 (above all process and freezer state: `dumpsys activity`,
  cgroup, `run-as`), the reboot probe last, and one full B2 no-gap trial. One command, from `artifact/`:

```
python aws/devicefarm.py run B0 --device pixel8 --allow-reboot --estimate 15 --timeout 25 --app-arn arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/e7f7dd9d-b697-4c61-836f-9d142696bc85 --package-arn arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/713e702a-099f-4113-9826-f83b0613abc0 --spec-arn arn:aws:devicefarm:us-west-2:478825889366:upload:83e7e695-4f56-4afc-bca4-cb04dea963ec/c396c072-a24b-4152-9e96-89fb5bfd6510
```

  The same command was run against `aws/fake_aws.py` (requests checked against the Device Farm model of botocore):
  one `schedule-run` with `jobTimeoutMinutes` 25, the Pixel 8 ARN, `P06_TASK=B0`, `P06_ARGS=--allow-reboot
  --budget-min 21`, 0 model errors.

### Building the APKs (Git Bash, on the user's computer)

```
export JAVA_HOME=D:/Java/jdk-17.0.21+9 ANDROID_HOME=D:/Android/Sdk
cd artifact/app/client && bash ./build.sh LeaseMemClient-v4
cd ../trig && bash ./build.sh;  cd ../mut && bash ./build.sh;  cd ../assist && bash ./build.sh
```

The signing key `artifact/app/k.jks` is a test key (JDK 17 keytool, alias `k`, password `android`, excluded by
`.gitignore`). Builds are not byte-reproducible (signing time); every RUNLOG line carries the APK SHA-256 used.

## 3. Artifact layout

On the test host, `campaign.py --out-root $DEVICEFARM_LOG_DIR/p06` writes:

```
$DEVICEFARM_LOG_DIR/p06/RUNLOG.md                      one line per step, as on the emulators
$DEVICEFARM_LOG_DIR/p06/physical-<YYYYMMDD>/*.jsonl    raw records (create-only)
$DEVICEFARM_LOG_DIR/p06/physical-<YYYYMMDD>/setup-<HHMMSS>.json, <udid>-setup-<ns>.json
$DEVICEFARM_LOG_DIR/p06/physical-<YYYYMMDD>/logs/<task>-<label>-<HHMM>.log
```

Device Farm returns `$DEVICEFARM_LOG_DIR` as the Customer Artifacts zip. `devicefarm.py fetch` copies every
`p06/physical-*/...` member into `artifact/results/physical-<YYYYMMDD>/...` with create-only writes (an existing file
is never overwritten; a clash is reported in RUNLOG), then appends to `artifact/results/RUNLOG.md` one `AWS fetch` line
(run ARN, files, records, records with `error`, device instances, clashes) followed by the run's own RUNLOG lines.
`devicefarm.py run` also appends an `AWS schedule` line (task, `P06_ARGS`, device ARN, run ARN, timeout, estimate,
minutes used and reserved), an `AWS stop` line whenever it stops a run, and an `AWS minutes` line (total, metered,
unmetered device minutes of the run, and P06's running total against 300). The minutes of a run are those Device
Farm reports (`deviceMinutes`), also written to `artifact/results/aws-minutes.jsonl`.

## 4. Guard on rented phones, and the blocked personal phone

| Rule | How the code enforces it |
|---|---|
| The user's phone is never used | `lmdrv.Dev` refuses serial `RFCXA0TTMPP` (also inside a longer adb name) before any adb call, in every mode, and refuses any device whose `ro.serialno` is that serial right after reading it. Only allowlisted serials are touched: P06's emulators, `P06_SERIALS`, and the Device Farm UDID. |
| AWS mode | `P06_TARGET=aws` (set by the test spec) or `DEVICEFARM_DEVICE_UDID`: user 0, nothing excluded, no `P06 Test` user required. |
| Every user-scoped command names the user | `am`, `pm`, `appops`, `content`, `cmd role`, `run-as`, `install` are built by `Dev.u()` or `Dev.install()` with `--user 0`; `Dev.sh()` refuses any command without it. |
| Banned commands | `pm clear` (one exception: exactly `pm clear --user 0 com.android.providers.contacts`, in AWS mode only), user management and user switching, `setprop`, `svc`, `su`, `locksettings`, `content insert/update/delete` from the shell, `batterystats --reset`, `/sdcard`, `/storage`, `/data` paths, `settings` other than `lm_mode`, `lm_target`, `auto_time`, `device_config` other than the freezer debounce and its sync mode, `dumpsys` outside a short allowlist, `adb push/pull/uninstall`. Clock commands (`date`, `cmd alarm`, `auto_time`) are allowed only in AWS mode, for the B0 probe. |
| Reboot | `Dev.adb('reboot')` needs `--allow-reboot` on the run; `devicefarm.py run ... --allow-reboot` passes it for B0, and for B2 only if B0's `reboot` probe has `survived: true`. After a reboot the driver waits (10 min at most on AWS) for user 0 in the foreground and unlocked. |
| Drivers run only under `campaign.py` | `Dev` refuses otherwise outside the emulators. `campaign.py` records the device-wide settings it may change, restores and reads them back after every step (exit status checked, values compared); on a rented phone a restore failure is logged and the run goes on, since Device Farm wipes the phone after the run. |
| Doze | always emulated on the charging rented phones with `dumpsys battery unplug` and `dumpsys deviceidle force-idle deep` (the drivers use the `dumpsys deviceidle` form, as in `driver/e2v3_gaps.py`; `cmd deviceidle` is not used), undone with `dumpsys deviceidle unforce` and `dumpsys battery reset`. |
| Static check | `python physical/test_user_scope.py`: no user-scoped command string without `--user`, no banned, clock or `pm clear` command outside documented exemptions, guard examples for user 10 and AWS user 0 (the Contacts `pm clear` allowed only in AWS mode, refused for any other package, user or mode), the blocked serial refused before any adb call (and when reported as `ro.serialno`), AWS mode in user 0 with SMS and call log, personal mode still requiring `P06 Test`. |

Root-only emulator steps and their replacements (unchanged from the emulator port):

| On the emulators (adbd as root) | On a rented phone | Code |
|---|---|---|
| `cat /data/data/<pkg>/files/...` | `run-as --user 0 <pkg> sh -c '...'` (all P06 apps are debuggable) | `Dev.app_sh`, `Dev.cat`, `Dev.rm` |
| cgroup `cgroup.freeze` via `/proc/<pid>/cgroup` | same files if readable; otherwise `isFrozen=` in `dumpsys activity processes <pkg>` | `Dev.frozen`, `frozen_method` |
| `kill -9 <pid>` from the shell | `run-as --user 0 <pkg> kill -9 <pid>` | `Dev.kill9` |
| clock rollback (B10) | run only if B0 shows the shell can set the time without root; else the emulator result stays | B0 probe `clock_set_back` |
| Contacts reset (`pm clear com.android.providers.contacts`, used by `revision/supplement.py`) | in user 0 of a wiped rented phone no root is needed; B0 probes it. The guard allows exactly `pm clear --user 0 com.android.providers.contacts` in AWS mode and refuses every other `pm clear` in every mode. If it works, the reset scenario can run on the phone; otherwise the emulator result stays | B0 probe `pm_clear_contacts`; `lmdrv.PM_CLEAR_AWS_OK` |
| persistent system app | not run; emulator result stays | |

## 5. Commands probed in B0

`physical/b0_probe.py` runs each probe in user 0, restores what it changed, and writes one record per probe (`ok`,
`detail`). B0 then runs one complete B2 no-gap trial (`b0-trial-none-*.jsonl`).

| Probe | Command(s) | Needed by | If it fails | Result |
|---|---|---|---|---|
| `identity` | `getprop` model, fingerprint, release, SDK, patch, build type | all | | not yet probed |
| `host` (AWS) | Python and adb versions, platform of the test host | all | | not yet probed |
| `user_info` | `am get-current-user`, `am get-started-user-state 0` | all | stop | not yet probed |
| `install_user` | `pm list packages --user 0 org.leasemem` | all | stop | not yet probed |
| `run_as_user` | `run-as --user 0 org.leasemem.client id` | all | stop: no driver can read results | not yet probed |
| `read_app_files` | client command round trip; `files/mem.json` | all | stop | not yet probed |
| `content_user` | `content query --user 0` fixture raw contacts | fixtures | stop | not yet probed |
| `appops` | `appops get --user 0 org.leasemem.mut MANAGE_EXTERNAL_STORAGE` | files | drop files | not yet probed |
| `fixtures_ensure_base` | mutator `ensure` (seven sources) | all | drop the failing source | not yet probed |
| `mutations_all_kinds` | mutator `mutate` for every source and kind, SMS and call log included | B2, B3, B4, B5, B9, B10 | drop that source or kind | not yet probed |
| `sms_role` (AWS) | `cmd role add-role-holder --user 0 android.app.role.SMS org.leasemem.mut 0`, then removed | SMS writes if appops alone is not enough | SMS kept only if `mutations_all_kinds` wrote SMS | not yet probed |
| `client_probe_candidates` | client `PROBE` | B3 | ERR candidates dropped | not yet probed |
| `process_user` | uid of the client process, `oom_score_adj` | B1, B2 | | not yet probed |
| `proc_cgroup_read`, `dumpsys_isFrozen` | cgroup freeze file; `dumpsys activity processes` | freezer state | if both fail: cut B1 frozen mode, B2 freezer, B5 | not yet probed |
| `freezer_debounce_2s` | `device_config put activity_manager_native_boot freeze_debounce_timeout 2000` (sync disabled until reboot), client frozen | B1 frozen, B2 freezer, B5 | cut those | not yet probed |
| `am_kill`, `am_force_stop`, `sigkill_kill9` | `am kill`, `am force-stop`, `run-as ... kill -9` | B2 kill, force-stop | cut gap | not yet probed |
| `pm_revoke_grant` | `pm revoke` / `pm grant --user 0 ... READ_CONTACTS` | B2 revoke | cut gap | not yet probed |
| `battery_unplug`, `doze_force_idle_deep` | `dumpsys battery unplug`, `dumpsys deviceidle force-idle deep`, `unforce`, `reset` | B2 Doze (emulated; the phone is always charging) | cut Doze gap | not yet probed |
| `standby_bucket` | `am set-standby-bucket --user 0 <pkg> restricted` | B2 bucket | cut gap | not yet probed |
| `assistant_role` | `cmd role add-role-holder --user 0 android.app.role.ASSISTANT org.leasemem.assist 0`, `mBound=true` | B1 assistant | cut assistant mode | not yet probed |
| `clock_set_back` (AWS) | `settings put global auto_time 0`; `date @t` or `cmd alarm set-time`; restore | B10 clock | clock part keeps the emulator result | not yet probed |
| `charge_counter`, `batterystats_uid`, `screen_sleep_wake` | `dumpsys battery`, client uid lines of `dumpsys batterystats --charged`, `input keyevent` | records only (no battery experiment) | | not yet probed |
| `pm_clear_contacts` (AWS) | `pm clear --user 0 com.android.providers.contacts`, then fixtures again | Contacts reset scenario | emulator result stays | not yet probed |
| `reboot` (with `--allow-reboot`) | `adb reboot`, `adb wait-for-device`, boot time, foreground user after boot; the record carries `survived: true` only if the run outlived the reboot | B2 reboot (and `\ifPhysReboot`) | the reboot gap keeps the emulator result | not yet probed |

The seconds per trial and the minutes of setup are read from the B0 run (RUNLOG and record time stamps) and replace
the estimates of section 6.

## 6. Experiments, runs and estimated device minutes

All tasks run through `campaign.py` on the test host, scheduled by `devicefarm.py`. A task too long for one run is
split by `devicefarm.py plan`: B2 by gap (labels packed into runs), single-step tasks by trials (`--trials`,
`--part K`: seeds shifted by 1000 K and file names tagged `-pK`, so parts never share seeds or names).

| Task | Driver | Trials and conditions | Seeds | Raw file(s) |
|---|---|---|---|---|
| B0 | `physical/b0_probe.py`; `driver/e2v3_gaps.py none 1` | probes of section 5; one full trial | 2611000 | `b0-probe-HHMM.jsonl`, `b0-trial-none-HHMM.jsonl` |
| B1 | `followup/deployment.py` | Contacts: background unfrozen, background frozen (debounce 2 s), FGS, bound assistant, 20 each; MediaStore and call log: background unfrozen and FGS, 20 each | | `deploy-<source>-HHMM.jsonl` |
| B3 | `driver/e1_coverage.py` | 30 trials, all seven sources (SMS included), insert, update, delete or unchanged | 2611301 | `coverage-HHMM.jsonl` |
| B2 | `driver/e2v3_gaps.py` | 25 trials for each of: none, freeze, dozeidle (emulated), bucket, unregister, kill, forcestop, perm, reboot (only if B0 shows the run survives a reboot); decisions at +2 s and +14 s | 2611201 to 2611209 | `gaps-<gap>[-pK]-HHMM.jsonl` |
| B4 | `revision/run.py stock` | 20 trials for each of the seven sources | 20261115 (driver) | `stock-<udid>[-pK]-HHMM.jsonl` |
| B9 | `driver/e3v2_boundary.py` | 100 changes over the window, 25 without boundary check, 20 + 20 no-change controls; then 100 changes in [-10, +40] ms | 2611901, 2611902 | `boundary-HHMM.jsonl`, `boundary-band-HHMM.jsonl` |
| B10 | `driver/e6_pitfalls.py` | SMS `_id` reuse 50, same-second mtime 50; clock rollback only on a rooted P06 emulator, so it stays emulator-only unless the driver gains a non-root path after B0 | 2611001 | `pitfalls-HHMM.jsonl` |
| B5 | `driver/e9_frozen.py` | 10 holds, each frozen for 600 s after the first change, debounce 2 s; 2 runs of 5 | 2611501 + 1000 K: 2612501 (part 1), 2613501 (part 2) | `frozen-p1-HHMM.jsonl`, `frozen-p2-HHMM.jsonl` |
| B13 | `followup/deployment.py`, `driver/e2v3_gaps.py` | second manufacturer: B1 Contacts, 4 deployments, 10 trials; B2 none, freeze, dozeidle, kill, forcestop, 10 trials each | 2621301 to 2621305 | `b13-deploy-contacts-HHMM.jsonl`, `b13-gaps-<gap>-HHMM.jsonl` |
| B6 | `revision/run.py host --arms refresh,validate,stamp,relay,memo` | 30 trials for each write pattern: none, one, continuous | 20261115 (driver) | `host-<udid>-HHMM.jsonl` |
| B7 | `physical/b7_continuous.py` | 30 trials; arms refresh, stamp, relay under a continuous Contacts writer | 2611701 | `continuous-HHMM.jsonl` |
| B11, B12 | | **dropped**: the rented phones are always charging and a run lasts at most 150 min, so there is no unplugged day and no battery drain. `campaign.py` logs `dropped` in AWS mode; the driver files stay | | |

Pre-commands applied by `campaign.py`: B2 and B13 set the freezer debounce to 2000 ms for `freeze` and 600000 ms for
every other gap (DeviceConfig sync disabled until reboot) and stop the FGS; B5 sets 2000 ms; B0, B3, B9, B10 stop
the FGS. All are restored after the step.

### Estimated device minutes (`python aws/estimate.py`)

How: the seconds per trial are the median gap between the start stamps of consecutive trials in the emulator raw
files (gaps over 10 times the median dropped as host sleep), so they include every wait of a trial; the planned trial
counts of the table above multiply them. Each run adds 6 min of preparation (an assumption until B0 measures it), and
a task is split so that a run holds at most 110 min of trials. Phone trials may be faster or slower than emulator
trials; B0 replaces these numbers.

| Task | Trial time, min | Runs (<= 150 min) | Device min incl. 6 min/run | USD at 0.17/min |
|---|---|---|---|---|
| B0 | 20.0 (assumption) | 1 | 20.0 | 3.40 |
| B1 | 27.8 | 1 | 33.8 | 5.75 |
| B3 | 13.8 | 1 | 19.8 | 3.37 |
| B2 | 137.8 | 2 | 149.8 | 25.46 |
| B4 | 0.5 | 1 | 6.5 | 1.11 |
| B9 | 17.9 | 1 | 23.9 | 4.07 |
| B10 | 0.8 | 1 | 6.8 | 1.15 |
| B5 | 123.5 | 2 | 135.5 | 23.03 |
| B13 | 36.6 | 1 | 42.6 | 7.23 |
| B6 | 0.6 | 1 | 6.6 | 1.12 |
| B7 | 0.6 | 1 | 6.6 | 1.12 |
| core B0 to B4 | | | 229.9 | 39.08 |
| all tasks | | | 451.9 | 76.82 |

Runs from `devicefarm.py plan` (with `--allow-reboot`): B2 in two runs (none, freeze, dozeidle, forcestop, reboot,
perm: about 104 min; unregister, bucket, kill: about 45 min), B5 in two runs of 5 holds (about 68 min each), every
other task in one run. A pilot B1 run (2 trials per condition) is about 7 min. These figures are before any free
minutes the account may have, and they do not include reruns of failed runs.

### Fitting the 300-minute cap

The user capped P06 at 300 device minutes. With the emulator-paced estimates above (to be replaced by B0's timings),
the core comes first, 15 % of the cap is kept for failed or cut runs, and the rest goes to B10, B9, B5 in that order
of fit. Timeouts are what a run reserves while it runs (`run` checks used + reserved + timeout <= 300 before each run);
the estimate is what it is expected to use.

| Block | Runs | Estimate, device min | Timeouts reserved | Status under the cap |
|---|---|---|---|---|
| B0 short (Pixel 8) | 1 | 15.0 | 25 | first; sent only with the user's agreement |
| B1 pilot (S2) | 1 | 7.4 | 12 | core |
| B1 | 1 | 33.8 | 44 | core |
| B3 | 1 | 19.8 | 27 | core |
| B2 with the reboot gap (only if B0's `reboot` probe has `survived: true`) | 2 | 149.7 | 129, 58 | core |
| B4 | 1 | 6.5 | 11 | core |
| **B0 and core** | 7 | **232.2** | | |
| Reserve for failed or cut runs, 15 % of 300 | | **45.0** | | kept |
| **Left** | | **22.8** | | |
| B10 | 1 | 6.8 | 12 | fits (15.9 left) |
| B9 | 1 | 23.9 | 32 | does not fit; fits if B2 runs without the reboot gap (126.3 instead of 149.7) or if the reserve is not used |
| B5 | 2 | 135.6 | 109, 58 | cut: ten 10-min frozen holds alone exceed what is left; emulator result stays |
| B13 (Galaxy S25), B6, B7 | 1 each | 42.6, 6.6, 6.6 | 55, 11, 11 | cut |

If B2 runs without the reboot gap, the core is 208.8, the left part 46.2: B10 and B9 both fit (15.5 left), B5 still
does not. Once B0 has measured the real seconds per trial and the real preparation time of a run, `estimate.py` is
rerun with them and this table is redone before B1; nothing beyond the core is scheduled without the new table.

Seconds per trial behind the table (emulator, median):

| Step | s per trial | Emulator file | Stamp |
|---|---|---|---|
| B2 none, freeze, dozeidle, bucket, unregister, kill, forcestop, perm, reboot | 34.2, 35.5, 36.3, 30.6, 33.5, 30.6, 40.0, 33.7, 56.3 | `raw/e2v3_bg_<gap>.jsonl` | `t_obs`, device ms |
| B1 bg_unfrozen, bg_freezer, fg, assistant | 16.6, 19.1, 3.7, 3.4 | `followup-20261116/deploy-emulator-562*.jsonl` | `mutation.t_pre`, device ms |
| B3 | 27.7 | `raw/e1_coverage_bg.jsonl` | earliest `muts.t_pre`, device ms |
| B4 | 1.6 | `revision-20261115/stock-emulator-5620.jsonl` | sum of `end - start` over the cases of a trial, host s |
| B6 (and B7) | 1.2 | `revision-20261115/host-emulator-5620.jsonl` | same |
| B5 | 740.9 | `raw/e9_frozen_33.jsonl` | `t_obs`, device ms |
| B9 | 4.1 | `raw/e3v2_boundary.jsonl` | `at`, device ms |
| B10 SMS reuse, mtime | 0.1, 0.8 | `raw/e6_pitfalls.jsonl` | `res.t_pre`, device ms |

Order (plan section 8, within the cap above): B0, pilot B1, then B1 and B3, B2 and B4 (two runs in parallel at most), B10, B9, B5, then
B13, and B6, B7 if time allows.

## 7. JSONL schema

### Fields added to every record

| Field | Meaning |
|---|---|
| `device` | `ro.product.manufacturer` + `ro.product.model` |
| `fingerprint` | `ro.build.fingerprint` |
| `sdk` | `ro.build.version.sdk` |
| `device_instance` | AWS: `$DEVICEFARM_DEVICE_UDID`, the physical unit; elsewhere the adb serial |
| `device_arn` | AWS: `$DEVICEFARM_DEVICE_ARN`; null elsewhere |
| `run_arn` | AWS: `$DEVICEFARM_RUN_ARN`, the Device Farm run; null elsewhere |
| `user_id` | Android user the experiment ran in (0 on AWS and on the emulators) |
| `excluded_sources` | sources the drivers and apps never touch on this device. Empty on a rented phone: all seven sources run, SMS and call log included. `analyze_phys.py` reads it from the latest B0 record and prints "not run on phone" (and sets `\ifPhysSms`, `\ifPhysCalllog` false) for every source it lists |
| `user_no_sms`, `user_no_outgoing_calls` | only meaningful in the superseded personal-phone mode; false on a rented phone |
| `serial` | adb serial used |
| `rooted` | adbd ran as uid 0 (always false on a rented phone) |
| `plugged` | `dumpsys battery` reported a charger when the record was created; true on a rented phone except under `dumpsys battery unplug` |

All other fields keep the emulator schema of the same driver. Errors stay in the record (`error`, often `trace`);
trials rejected by the driver keep `invalid` (for example `not_frozen`).

**File names.** `--pilot` puts `pilot` into every output name (`gaps-pilot-none-HHMM`, `coverage-pilot-HHMM`, ...);
`analyze_phys.py` keeps those files out of the main numbers. `--part K` adds `-pK` (`gaps-none-p1-HHMM`,
`frozen-p2-HHMM`, `stock-<udid>-p1-HHMM`). B13 files start with `b13-`.

| File | Record shape | Additions to the emulator schema |
|---|---|---|
| `b0-probe-*.jsonl` | one record per probe | `probe`, `ok`, `detail`, `seconds`, `trace` on exceptions |
| `deploy-*.jsonl` (B1) | `followup/deployment.py` | `source` (`contacts`, `media`, `calllog`); `frozen_method`; `binding` holds only the `leasemem` and `mBound` lines of `dumpsys voiceinteraction` |
| `gaps-*.jsonl` (B2) | `driver/e2v3_gaps.py`, protocol `v3` | `frozen_method`; `user_back_s` (reboot gap) |
| `coverage-*.jsonl` (B3) | `driver/e1_coverage.py` | none |
| `stock-*.jsonl` (B4) | `revision/run.py stock` | none |
| `frozen-*.jsonl` (B5) | `driver/e9_frozen.py` | `frozen_method` |
| `boundary-*.jsonl` (B9) | `driver/e3v2_boundary.py`, protocol `v2` | none |
| `pitfalls-*.jsonl` (B10) | `driver/e6_pitfalls.py` | none |
| `host-*.jsonl` (B6) | `revision/run.py host` | arm `stamp`; batch results gain `reads`, `wall_offset_ms`; `stamp` batches gain `stamp` and `stamp_reads` |
| `continuous-*.jsonl` (B7) | `physical/b7_continuous.py` | oracle `classify()` in that file |
| `b13-deploy-*.jsonl`, `b13-gaps-*.jsonl` (B13) | as B1 and B2 | none |
| `setup-HHMMSS.json`, `<udid>-setup-<ns>.json` | setup metadata (not JSONL) | install results, APK SHA-256, fixtures, counts of rows not written by P06 |

## 8. Validity and exclusions

- Raw files are created with `open(..., 'x')` on the test host, and `fetch` copies them with create-only writes;
  nothing is overwritten or deleted. A failed or cut run keeps its files and gets RUNLOG lines; exclusions are listed
  in `artifact/results/RUNLOG.md` and applied by the analysis.
- Every step appends to the run's RUNLOG: time, task, label, command, device, fingerprint, user, `rooted`,
  `plugged`, device instance and run ARN, APK SHA-256, minutes, exit code, records, records with `error` or
  `invalid`, restore result, output and log names. Steps not started because of `--budget-min` get a `budget` line.
- Freezer-dependent trials are valid only if the frozen state was observed (`not_frozen` rule).
- One task never mixes two models; the device instance of every trial is recorded, so Results can compare units.
- No emulator number replaces a phone number. A command that fails on the phone cuts the dependent experiment; the
  cut list goes to the user after S1 (stop point 3).

## 9. Known limitations of the method

- One model (and a second one in B13 if time allows); rented units of that model may differ from run to run.
- The phones are always charging: Doze is emulated (`dumpsys battery unplug`, `deviceidle force-idle`), and there is
  no battery or unplugged-day measurement (B11, B12 dropped).
- Runs last at most 150 min on a freshly wiped phone; long holds (B5) are split.
- Not rooted: frozen state may come from ActivityManager's flag (`frozen_method: dumpsys`); clock rollback, Contacts
  reset and the persistent system app keep their emulator results.
- All callback and commit times are device clock times; the test host's clock is used only for waits.

## 10. Results macros fed by each file

The authoritative list is the `macros` registry in `analyze()` of `artifact/physical/analyze_phys.py` (Results).
`manuscript/generated/physical_macros.tex` (commit d43bcef, Results G1) defines 58 macros (the 49 registry entries
below plus the 9 dropped ones) and 3 switches; every name in this section was checked against that file. If Results
adds or renames a macro, the registry wins. `analyze_phys.py` reads only top-level
`artifact/results/physical-*/*.jsonl` and leaves out files with `pilot` in the name. SMS and the call log follow the
same rule: a source listed in `excluded_sources` of the latest B0 record prints "not run on phone"; on a rented phone
nothing is listed, so both run.

| Switch | True when |
|---|---|
| `\ifPhysSms` | SMS is not in `excluded_sources` of the latest B0 record |
| `\ifPhysCalllog` | the call log is not in `excluded_sources` of the latest B0 record |
| `\ifPhysReboot` | B2 has at least one valid, non-pilot reboot trial (needs a B0 `reboot` record with `survived: true` and B2 run with `--allow-reboot`) |

| Macro(s) | Task | Raw file pattern under `results/physical-<YYYYMMDD>/` |
|---|---|---|
| `PhysDevice`, `PhysFingerprint`, `PhysRooted`, `PhysSdk` | all | `*.jsonl` (common fields) |
| `PhysInstances` | all | `*.jsonl`, distinct `device_instance` |
| `PhysAndroid` | B0 | `b0-probe-*.jsonl` (`identity` probe) |
| `PhysDeployTrials`, `PhysDeployBgMedian`, `PhysDeployFgMedian`, `PhysDeployAssistMedian`, `PhysDeployFrozenBeforeThaw`, `PhysDeployMediaBgMedian`, `PhysDeployMediaFgMedian`, `PhysDeployCalllogBgMedian`, `PhysDeployCalllogFgMedian` | B1 | `deploy*.jsonl` (filtered on `source`) |
| `PhysCoverageTrials` | B3 | `coverage-*.jsonl` |
| `PhysGapTrials`, `PhysGapNoneFcl`, `PhysGapFreezeFcl`, `PhysGapDozeFcl`, `PhysGapBucketFcl`, `PhysGapLostEv`, `PhysGapLostEvr`, `PhysGapLostLm`, `PhysGapInEpochEv`, `PhysGapInEpochEvr`, `PhysGapInEpochLm`, `PhysCostGl`, `PhysCostGlCi`, `PhysCostLm`, `PhysCostLmCi`, `PhysCostN` | B2 | `gaps-*.jsonl` (all parts) |
| `PhysRaceTrials`, `PhysRaceStale` | B4 | `stock-*.jsonl` |
| `PhysBoundaryTrials`, `PhysCteMs`, `PhysBndObsStale`, `PhysBndBeforeCheckStale`, `PhysBndOverlapStale` | B9 | `boundary*.jsonl` |
| `PhysSmsReuse`, `PhysMtimeSame` | B10 | `pitfalls-*.jsonl` (`exp`) |
| `PhysFrozenHolds`, `PhysFrozenStayed`, `PhysFrozenKilled`, `PhysFrozenLastUnseen` | B5 | `frozen-*.jsonl` (both parts) |
| `PhysHostTrials` | B6 | `host-*.jsonl` |
| `PhysEvidCheap`, `PhysEvidBound`, `PhysEvidWeak` | B2; B1 and B2; B4 and B10 | as above |

Dropped (B11, B12; always "not run on phone", with the reason that rented phones are always charging and a run
lasts at most 150 min): `PhysStateHours`, `PhysStateAlivePct`, `PhysStateFrozenPct`, `PhysStateDozePct`,
`PhysStateKillsPerHour`, `PhysBatteryFgsMahPerHour`, `PhysBatteryBgMahPerHour`, `PhysBatteryFgsBlocks`,
`PhysBatteryBgBlocks`.

Notes for Results: B13 files (`b13-*`) match none of the B1 or B2 patterns, so the main-model macros never read them;
they do match `*.jsonl`, so `PhysDevice` and `PhysInstances` would count the second model's records once B13 runs.
B7 (`continuous-*`) has no macro.

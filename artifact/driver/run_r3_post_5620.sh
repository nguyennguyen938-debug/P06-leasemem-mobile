#!/bin/bash
# After E9 on emulator-5620 (P06Avd, Android 13): E10 deployments (bg, fg, assist), then the long-Doze gap with
# deep idle verified before both mutation batches (10 trials).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
until grep -q E9_DONE_5620 logs/run_r3_frozen_5620.log; do sleep 30; done
echo "== E10 on $(adb -s $S shell getprop ro.build.version.sdk) $(date)"
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
for m in bg fg; do python3 driver/e10_deploy.py $S $m 6 1000 results/raw/e10_deploy_33.jsonl; done
bash driver/r3_assist_setup.sh $S
python3 driver/e10_deploy.py $S assist 6 1001 results/raw/e10_deploy_33.jsonl
bash driver/r3_assist_teardown.sh $S
echo "== longdoze2 $(date)"
adb -s $S shell am stopservice -n org.leasemem.client/.FgService
python3 driver/e2v3_gaps.py $S longdoze2 10 1300 results/raw/e2v3_bg_longdoze2.jsonl
echo POST_DONE_5620 $(date)

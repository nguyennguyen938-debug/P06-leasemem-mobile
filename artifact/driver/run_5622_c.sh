#!/bin/bash
# Top-up: replace the 8 freezer trials excluded for host sleep (pre-declared rule), same protocol, new seed.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
while ! grep -q BATCH5622B_DONE logs/run_5622_b.log; do sleep 20; done
adb -s $S shell "settings put global auto_time 1"
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
python3 driver/e2_gaps.py $S freeze 8 203 results/raw/e2_freeze_topup.jsonl
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 600000
echo BATCH5622C_DONE $(date)

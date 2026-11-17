#!/bin/bash
# E2 batch for emulator-5622 (P06Avd2). Freeze runs with a 2 s freezer debounce; all other gaps restore the
# platform default (600 s) so a cached client is not frozen during the gap.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
python3 driver/e2_gaps.py $S freeze 50 201 results/raw/e2_freeze.jsonl
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 600000
for g in none kill forcestop; do python3 driver/e2_gaps.py $S $g 50 $((300 + ${#g})) results/raw/e2_$g.jsonl; done
echo BATCH5622_DONE

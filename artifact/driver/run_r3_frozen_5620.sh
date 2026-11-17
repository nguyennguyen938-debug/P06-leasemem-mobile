#!/bin/bash
# E9: long frozen gaps (>=600 s frozen after the first change, ~150 notifications), 20 trials.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
adb -s $S shell device_config set_sync_disabled_for_tests until_reboot
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
echo "debounce: $(adb -s $S shell dumpsys activity settings | grep freeze_debounce)"
python3 driver/e9_frozen.py $S 20 9000 results/raw/e9_frozen_$(adb -s $S shell getprop ro.build.version.sdk | tr -d '\r').jsonl 600
echo E9_DONE_5620 $(date)

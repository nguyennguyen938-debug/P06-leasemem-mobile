#!/bin/bash
# Follow-up batch for emulator-5622, after run_e2_5622.sh.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
while pgrep -f run_e2_5622.sh >/dev/null; do sleep 15; done
echo "batch A done $(date)"
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 600000
python3 driver/e2_gaps.py $S reboot 50 706 results/raw/e2_reboot.jsonl
python3 driver/e1_coverage.py $S 25 102 results/raw/e1_coverage_fg.jsonl fg
adb -s $S shell input keyevent KEYCODE_HOME
python3 driver/e6_pitfalls.py $S 50 801 results/raw/e6_pitfalls.jsonl
echo BATCH5622B_DONE $(date)

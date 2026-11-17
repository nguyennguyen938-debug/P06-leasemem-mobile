#!/bin/bash
# Verified long Doze (deep idle before both batches), default freezer debounce, 5 trials on emulator-5622 (P06Avd2, Android 13).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
while pgrep -f "e11_fgcost.py emulator-5622" >/dev/null; do sleep 10; done
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 600000
adb -s $S shell dumpsys activity settings | grep freeze_debounce
adb -s $S shell am stopservice -n org.leasemem.client/.FgService
python3 driver/e2v3_gaps.py $S longdoze2 5 1320 results/raw/e2v3_bg_longdoze2_b.jsonl
echo DOZE_DONE_5622 $(date)

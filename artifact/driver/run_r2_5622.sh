#!/bin/bash
# Round-2 batch B on emulator-5622 (P06Avd2): freezer with verified frozen state (debounce flag applied by reboot),
# reboot gap, foreground-service arm, long realistic freezer gaps (default debounce).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
reboot_root() { adb -s $S reboot; sleep 8; until [ "$(adb -s $S shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 3; done; adb -s $S root; sleep 4; adb -s $S shell appops set root WRITE_SMS allow; }
# NOTE: the flag takes effect live; a reboot reverts it to 600000 on this image (first attempt, see RUNLOG)
adb -s $S shell device_config set_sync_disabled_for_tests until_reboot   # otherwise DeviceConfig sync reverts the flag
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
echo "debounce live: $(adb -s $S shell dumpsys activity settings | grep freeze_debounce)"
python3 driver/e2v3_gaps.py $S freeze 24 2011 results/raw/e2v3_bg_freeze.jsonl
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 600000
echo "debounce live: $(adb -s $S shell dumpsys activity settings | grep freeze_debounce)"
python3 driver/e2v3_gaps.py $S reboot 25 2002 results/raw/e2v3_bg_reboot.jsonl
i=0
for g in none dozeidle unregister sigkill forcestop reboot; do
  i=$((i+1)); python3 driver/e2v3_gaps.py $S $g 15 $((2100+i)) results/raw/e2v3_fg_$g.jsonl --fg
done
adb -s $S shell am stopservice -n org.leasemem.client/.FgService
echo R2B_PART1_DONE $(date)
python3 driver/e2v3_gaps.py $S longfreeze 5 2201 results/raw/e2v3_bg_longfreeze.jsonl
echo R2B_DONE $(date)

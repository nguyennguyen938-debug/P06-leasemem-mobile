#!/bin/bash
# Batch for emulator-5620 (P06Avd), after E1 finishes.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
while pgrep -f "e1_coverage.py emulator-5620" >/dev/null; do sleep 10; done
echo "E1 done $(date)"
adb -s $S install -r -g app/LeaseMemClient-v2.apk | tail -1
adb -s $S shell appops set org.leasemem.client MANAGE_EXTERNAL_STORAGE allow
python3 driver/e3_boundary.py $S 25 401 results/raw/e3_boundary.jsonl     # 25 x 12 cells = 300 trials
for g in doze unregister perm; do python3 driver/e2_gaps.py $S $g 50 $((500 + ${#g})) results/raw/e2_$g.jsonl; done
python3 driver/e4_gui_cost.py $S 10 601 results/raw/e4_gui.jsonl        # 10 x 8 cells = 80 trials
echo BATCH5620_DONE $(date)

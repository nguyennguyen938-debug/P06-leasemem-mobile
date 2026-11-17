#!/bin/bash
# Round-2 follow-up on emulator-5620 after batch A: E3 v2, E6 v2 (clock vs VERSION adapter), E8 (LLM-derived facts).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
while ! grep -q R2A_DONE logs/run_r2_5620.log; do sleep 20; done
python3 driver/e3v2_boundary.py $S 160 3001 results/raw/e3v2_boundary.jsonl
python3 driver/e6v2_clock.py $S 30 3002 results/raw/e6v2_clock.jsonl
adb -s $S shell "settings put global auto_time 1"
python3 driver/e8_llm.py $S kill 20 0.3 3003 results/raw/e8_kill_p03.jsonl
python3 driver/e8_llm.py $S kill 12 0.1 3004 results/raw/e8_kill_p01.jsonl
python3 driver/e8_llm.py $S none 12 0.3 3005 results/raw/e8_none_p03.jsonl
echo R2A2_DONE $(date)

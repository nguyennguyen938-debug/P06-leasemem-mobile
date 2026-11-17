#!/bin/bash
# Resume batch on emulator-5620 (P06Avd): remaining background conditions, long Doze, E3 v2, E6 v2, E8.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
python3 driver/e2v3_gaps.py $S forcestop 23 1016 results/raw/e2v3_bg_forcestop.jsonl
python3 driver/e2v3_gaps.py $S perm 25 1017 results/raw/e2v3_bg_perm.jsonl
python3 driver/e2v3_gaps.py $S longdoze 5 1101 results/raw/e2v3_bg_longdoze.jsonl
echo C_E2_DONE $(date)
python3 driver/e3v2_boundary.py $S 160 3001 results/raw/e3v2_boundary.jsonl
echo C_E3_DONE $(date)
python3 driver/e6v2_clock.py $S 30 3002 results/raw/e6v2_clock.jsonl
adb -s $S shell "settings put global auto_time 1"
echo C_E6_DONE $(date)
ollama serve > logs/ollama_r2c.log 2>&1 & OP=$!; echo $OP > logs/ollama.pid; sleep 5
python3 driver/e8_llm.py $S kill 20 0.3 3003 results/raw/e8_kill_p03.jsonl
python3 driver/e8_llm.py $S kill 12 0.1 3004 results/raw/e8_kill_p01.jsonl
python3 driver/e8_llm.py $S none 12 0.3 3005 results/raw/e8_none_p03.jsonl
kill $OP; sleep 2
echo R2C_DONE $(date)

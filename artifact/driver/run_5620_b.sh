#!/bin/bash
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
while ! grep -q BATCH5620_DONE logs/run_5620.log; do sleep 20; done
python3 driver/e7_lmk.py emulator-5620 10 28 901 results/raw/e7_lmk.jsonl
echo BATCH5620B_DONE $(date)

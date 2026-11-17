#!/bin/bash
# Round-2 batch A on emulator-5620 (P06Avd, default freezer debounce): background-client gaps, v3 protocol.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
i=0
for g in none dozeidle bucket unregister kill forcestop perm; do
  i=$((i+1)); python3 driver/e2v3_gaps.py $S $g 25 $((1000+i)) results/raw/e2v3_bg_$g.jsonl
done
echo R2A_PART1_DONE $(date)
python3 driver/e2v3_gaps.py $S longdoze 5 1101 results/raw/e2v3_bg_longdoze.jsonl
echo R2A_DONE $(date)

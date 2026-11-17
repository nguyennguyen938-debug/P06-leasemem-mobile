#!/bin/bash
# After the post-E9 batch on emulator-5620: E13 host-agent costs over adb (40 decisions).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5620
until grep -q POST_DONE_5620 logs/run_r3_post_5620.log; do sleep 30; done
echo "== E13 $(date)"
python3 driver/e13_host.py $S 40 1400 results/raw/e13_host_33.jsonl
echo HOST_DONE_5620 $(date)

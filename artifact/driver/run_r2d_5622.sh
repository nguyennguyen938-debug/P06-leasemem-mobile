#!/bin/bash
# Resume batch on port 5622: remaining FGS conditions and long freezer on P06Avd2, then Android 15 (P06Avd35).
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
python3 driver/e2v3_gaps.py $S sigkill 8 2114 results/raw/e2v3_fg_sigkill.jsonl --fg
python3 driver/e2v3_gaps.py $S forcestop 15 2115 results/raw/e2v3_fg_forcestop.jsonl --fg
python3 driver/e2v3_gaps.py $S reboot 15 2116 results/raw/e2v3_fg_reboot.jsonl --fg
adb -s $S shell am stopservice -n org.leasemem.client/.FgService
echo "debounce (default expected): $(adb -s $S shell dumpsys activity settings | grep freeze_debounce)"
python3 driver/e2v3_gaps.py $S longfreeze 5 2201 results/raw/e2v3_bg_longfreeze.jsonl
echo D_API33_DONE $(date)
adb -s $S emu kill; sleep 12
nohup emulator -avd P06Avd35 -port 5622 -grpc 8622 -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot > logs/emu5622_api35.log 2>&1 &
sleep 20; until [ "$(adb -s $S shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 5; done
adb -s $S root; sleep 5
echo "fingerprint: $(adb -s $S shell getprop ro.build.fingerprint)"
for a in app/LeaseMemClient-v3.apk app/trig/build/LeaseMemTrig.apk app/mut/build/LeaseMemMut.apk; do adb -s $S install -r -g $a | tail -1; done
adb -s $S shell "appops set org.leasemem.client MANAGE_EXTERNAL_STORAGE allow; appops set org.leasemem.mut MANAGE_EXTERNAL_STORAGE allow; appops set org.leasemem.mut WRITE_SMS allow; appops set root WRITE_SMS allow; pm grant org.leasemem.mut android.permission.WRITE_SECURE_SETTINGS"
echo "freezer: $(adb -s $S shell dumpsys activity settings | grep -E 'use_freezer|freeze_debounce')"
python3 driver/e1_coverage.py $S 30 4001 results/raw/e1api35_bg.jsonl
i=0
for g in none kill unregister; do i=$((i+1)); python3 driver/e2v3_gaps.py $S $g 12 $((4100+i)) results/raw/e2v3_api35_$g.jsonl; done
adb -s $S shell device_config set_sync_disabled_for_tests until_reboot
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
python3 driver/e2v3_gaps.py $S freeze 12 4110 results/raw/e2v3_api35_freeze.jsonl
echo R2D_DONE $(date)

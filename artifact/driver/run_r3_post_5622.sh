#!/bin/bash
# After E9 on emulator-5622 (P06Avd35, Android 15): E10 deployments (bg, fg, assist) and E11 FGS cost.
# Then switch 5622 to P06Avd2 (Android 13): E3 boundary band and E12 scale.
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=emulator-5622
until grep -q E9_DONE_5622 logs/run_r3_frozen_5622.log; do sleep 30; done
echo "== E10 on $(adb -s $S shell getprop ro.build.version.sdk) $(date)"
adb -s $S shell device_config put activity_manager_native_boot freeze_debounce_timeout 2000
for m in bg fg; do python3 driver/e10_deploy.py $S $m 6 1100 results/raw/e10_deploy_35.jsonl; done
bash driver/r3_assist_setup.sh $S
python3 driver/e10_deploy.py $S assist 6 1101 results/raw/e10_deploy_35.jsonl
bash driver/r3_assist_teardown.sh $S
echo "== E11 $(date)"
python3 driver/e11_fgcost.py $S 3 600 1110 results/raw/e11_fgcost_35.jsonl
echo "== switch to P06Avd2 $(date)"
adb -s $S emu kill; sleep 15
nohup emulator -avd P06Avd2 -port 5622 -grpc 8622 -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot > logs/emu_5622_avd2_r3.log 2>&1 &
sleep 20; adb -s $S wait-for-device
until [ "$(adb -s $S shell getprop sys.boot_completed | tr -d '\r')" = "1" ]; do sleep 3; done
adb -s $S root; sleep 4; adb -s $S wait-for-device
until [ "$(adb -s $S shell getprop sys.boot_completed | tr -d '\r')" = "1" ]; do sleep 3; done
echo "sdk $(adb -s $S shell getprop ro.build.version.sdk)"
adb -s $S install -r -g app/mut/build/LeaseMemMut.apk
adb -s $S shell appops set org.leasemem.mut MANAGE_EXTERNAL_STORAGE allow
adb -s $S shell appops set org.leasemem.mut WRITE_SMS allow
adb -s $S shell pm grant org.leasemem.mut android.permission.WRITE_SECURE_SETTINGS
adb -s $S shell appops set org.leasemem.client MANAGE_EXTERNAL_STORAGE allow
adb -s $S shell appops set root WRITE_SMS allow
echo "== E3 band $(date)"
python3 driver/e3v2_boundary.py $S 150 3300 results/raw/e3v2_band.jsonl band
echo "== E12 $(date)"
python3 driver/e12_scale.py $S 10 1200 results/raw/e12_scale.jsonl
echo POST_DONE_5622 $(date)

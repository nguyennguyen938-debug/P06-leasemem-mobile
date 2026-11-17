#!/bin/bash
# Install the default-assistant variant (org.leasemem.assist) and make it the ASSISTANT role holder, so that
# system_server binds its VoiceInteractionService. Usage: r3_assist_setup.sh SERIAL
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=$1; P=org.leasemem.assist
adb -s $S install -r -g app/assist/build/LeaseMemAssist.apk
adb -s $S shell appops set $P MANAGE_EXTERNAL_STORAGE allow
adb -s $S shell cmd role add-role-holder android.app.role.ASSISTANT $P 0
sleep 3
adb -s $S shell settings get secure voice_interaction_service
adb -s $S shell settings get secure assistant
adb -s $S shell cmd role get-role-holders android.app.role.ASSISTANT 2>/dev/null
adb -s $S shell dumpsys voiceinteraction | grep -iE "leasemem|mBound|mComponent" | head -8

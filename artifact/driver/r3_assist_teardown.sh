#!/bin/bash
# Remove the assistant role from org.leasemem.assist and uninstall it. Usage: r3_assist_teardown.sh SERIAL
cd "$(dirname "$0")/.."
source ../../shared-android/env.sh
S=$1
adb -s $S shell cmd role remove-role-holder android.app.role.ASSISTANT org.leasemem.assist 0
adb -s $S uninstall org.leasemem.assist

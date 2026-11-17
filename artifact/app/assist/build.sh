#!/bin/bash
# Deployment-model variant: the same memory client code under package org.leasemem.assist, plus a minimal
# VoiceInteractionService so the package can hold the default-assistant role. Built without Gradle.
set -e
D="$(cd "$(dirname "$0")" && pwd)"; cd "$D"
source "$D/../../revision/build-env.sh"
BT=$ANDROID_HOME/build-tools/34.0.0; AJAR=$ANDROID_HOME/platforms/android-33/android.jar
KS="$D/../k.jks"
rm -rf build && mkdir -p build/classes build/dex
$BT/aapt2 compile --dir res -o build/res.zip
$BT/aapt2 link -o build/base.apk -I "$AJAR" --manifest AndroidManifest.xml -R build/res.zip --auto-add-overlay
$JAVA_HOME/bin/javac -source 11 -target 11 -d build/classes -classpath "$AJAR" $(find ../client/src -name '*.java')
"$D8" --min-api 30 --lib "$AJAR" --output build/dex $(find build/classes -name '*.class')
cd build; cp base.apk unsigned.apk; "$JAVA_HOME/bin/jar" uf unsigned.apk -C dex classes.dex
$BT/zipalign -f 4 unsigned.apk aligned.apk
"$APKSIGNER" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android --out LeaseMemAssist.apk aligned.apk
shasum -a 256 LeaseMemAssist.apk

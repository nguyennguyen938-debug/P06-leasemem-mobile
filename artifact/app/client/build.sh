#!/bin/bash
# Builds LeaseMemClient.apk without Gradle (javac + d8 + aapt2), as in shared-android/seallist2.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../revision" && pwd)/build-env.sh"
BT=$ANDROID_HOME/build-tools/34.0.0; AJAR=$ANDROID_HOME/platforms/android-33/android.jar
D="$(cd "$(dirname "$0")" && pwd)"; cd "$D"
KS="$D/../k.jks"
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -storepass android -keypass android -alias k -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=LeaseMem" >/dev/null 2>&1
NAME=${1:-LeaseMemClient}
rm -rf build && mkdir -p build/classes build/dex
$BT/aapt2 link -o build/base.apk -I "$AJAR" --manifest AndroidManifest.xml
$JAVA_HOME/bin/javac -source 11 -target 11 -d build/classes -classpath "$AJAR" $(find src -name '*.java')
"$D8" --min-api 30 --lib "$AJAR" --output build/dex $(find build/classes -name '*.class')
cd build; cp base.apk unsigned.apk; "$JAVA_HOME/bin/jar" uf unsigned.apk -C dex classes.dex
$BT/zipalign -f 4 unsigned.apk aligned.apk
"$APKSIGNER" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android --out $NAME.apk aligned.apk
shasum -a 256 $NAME.apk

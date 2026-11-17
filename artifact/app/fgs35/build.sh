#!/bin/bash
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$D/../../revision/build-env.sh"
BT="$ANDROID_HOME/build-tools/34.0.0"; AJAR="$ANDROID_HOME/platforms/android-33/android.jar"
cd "$D"
mkdir -p build/classes build/dex
"$JAVA_HOME/bin/javac" -source 11 -target 11 -d build/classes -classpath "$AJAR" $(find ../client/src -name '*.java')
"$BT/d8" --min-api 30 --lib "$AJAR" --output build/dex $(find build/classes -name '*.class')
for variant in typed missing; do
 mkdir -p "build/$variant"
 if [ "$variant" = missing ]; then sed 's/ android:foregroundServiceType="dataSync"//' AndroidManifest.xml > "build/$variant/AndroidManifest.xml"; else cp AndroidManifest.xml "build/$variant/AndroidManifest.xml"; fi
 "$BT/aapt2" link -o "build/$variant/base.apk" -I "$AJAR" --manifest "build/$variant/AndroidManifest.xml"
 cp "build/$variant/base.apk" "build/$variant/unsigned.apk"
 "$JAVA_HOME/bin/jar" uf "build/$variant/unsigned.apk" -C build/dex classes.dex
 "$BT/zipalign" -f 4 "build/$variant/unsigned.apk" "build/$variant/aligned.apk"
 "$BT/apksigner" sign --ks ../k.jks --ks-pass pass:android --key-pass pass:android --out "build/FGS35-$variant.apk" "build/$variant/aligned.apk"
done

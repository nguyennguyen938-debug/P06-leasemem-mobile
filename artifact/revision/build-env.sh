# Portable artifact toolchain. Caller may set ANDROID_HOME and JAVA_HOME.
P06_ARTIFACT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${ANDROID_HOME:-}" ]; then
  ANDROID_HOME="$P06_ARTIFACT_ROOT/../../shared-android/sdk"
fi
export ANDROID_HOME
if [ -z "${JAVA_HOME:-}" ]; then
  if [ -d /opt/homebrew/opt/openjdk@17 ]; then JAVA_HOME=/opt/homebrew/opt/openjdk@17
  elif command -v /usr/libexec/java_home >/dev/null 2>&1; then JAVA_HOME="$(/usr/libexec/java_home -v 17)"
  else JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")"; fi
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0:$PATH"
# Windows SDKs ship d8 and apksigner as .bat files, which Git Bash runs only by their full name.
if [ -f "$ANDROID_HOME/build-tools/34.0.0/d8.bat" ]; then
  D8="$ANDROID_HOME/build-tools/34.0.0/d8.bat"; APKSIGNER="$ANDROID_HOME/build-tools/34.0.0/apksigner.bat"
else
  D8="$ANDROID_HOME/build-tools/34.0.0/d8"; APKSIGNER="$ANDROID_HOME/build-tools/34.0.0/apksigner"
fi

#!/usr/bin/env bash
# یک APK امضاشده را روی سرور مهراد منتشر می‌کند تا اپ‌های نصب‌شده خودشان به‌روز شوند (از داخل اپ).
# اجرا:  NOTES="توضیح نسخه" ./tools/publish-apk.sh مسیر.apk
# versionCode/versionName از app/build.gradle خوانده می‌شود؛ باید با APK یکی باشد و از نسخهٔ نصب‌شده بزرگ‌تر.
set -euo pipefail
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

HOST="${BUILD_HOST:-root@89.125.35.130}"
KEY="${BUILD_KEY:-$HOME/.ssh/mehrdad_nl}"
APP_DATA=/opt/mehrdad/mehrdad/server/data
APK="${1:?مسیر APK را بده}"
NOTES="${NOTES:-}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ServerAliveInterval=15 "$HOST")

cd "$(dirname "$0")/.."
VCODE=$(grep -oE 'versionCode +[0-9]+' app/build.gradle | grep -oE '[0-9]+')
VNAME=$(grep -oE 'versionName +"[^"]+"' app/build.gradle | grep -oE '"[^"]+"' | tr -d '"')
SHA=$(python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$APK")
SIZE=$(wc -c < "$APK" | tr -d ' ')
JSON=$(python -c "import json,sys;print(json.dumps({'versionCode':int(sys.argv[1]),'versionName':sys.argv[2],'sha256':sys.argv[3],'size':int(sys.argv[4]),'notes':sys.argv[5]},ensure_ascii=False))" "$VCODE" "$VNAME" "$SHA" "$SIZE" "$NOTES")

"${SSH[@]}" "mkdir -p $APP_DATA/apk && cat > $APP_DATA/apk/mehrdad.apk.new && mv $APP_DATA/apk/mehrdad.apk.new $APP_DATA/apk/mehrdad.apk && chmod 644 $APP_DATA/apk/mehrdad.apk" < "$APK"
printf '%s' "$JSON" | "${SSH[@]}" "cat > $APP_DATA/apk/version.json.new && mv $APP_DATA/apk/version.json.new $APP_DATA/apk/version.json && chmod 644 $APP_DATA/apk/version.json"
echo "منتشر شد: نسخهٔ $VNAME (کد $VCODE)، sha256=$SHA"

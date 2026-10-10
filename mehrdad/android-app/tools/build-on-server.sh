#!/usr/bin/env bash
# APK انتشار (امضای ثابت) را روی یک سرور Docker خارج از ایران می‌سازد، روی سرور مهرداد منتشر می‌کند
# (تا خود اپ‌ها به‌روز شوند)، و یک نسخه را هم برای تو برمی‌گرداند.
#
# اجرا (Git Bash روی ویندوز):
#   ACCEPT_ANDROID_LICENSES=yes ./tools/build-on-server.sh [خروجی.apk]
#   NOTES="داشبورد مالی" PUBLISH=0 ./tools/build-on-server.sh     # فقط بساز، منتشر نکن
#
# نکته‌ها:
# - --network host و IPv6 لازم است چون روی سرورهای خاص مسیر IPv4 به dl.google.com ۴۰۴ می‌گیرد ولی IPv6 باز است.
# - کلید امضا فقط یک بار ساخته می‌شود و روی سرور می‌ماند؛ یک کپی هم به BACKUP_DIR می‌آید. بدون این کلید
#   هیچ نسخهٔ بعدی روی نصب فعلی نمی‌نشیند. آن را گم نکن و جایی منتشر نکن.
set -euo pipefail
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8   # خروجی فارسی در ویندوز (cp1256) نشکند

HOST="${BUILD_HOST:-root@89.125.35.130}"
KEY="${BUILD_KEY:-$HOME/.ssh/mehrdad_nl}"
DIR=/opt/mehrdad-android-build
APP_DATA=/opt/mehrdad/mehrdad/server/data           # همان ./data سرویس مهرداد (داخل کانتینر: /data)
OUT="${1:-mehrdad.apk}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/.mehrdad-signing}"
PUBLISH="${PUBLISH:-1}"
NOTES="${NOTES:-}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ServerAliveInterval=15 "$HOST")

cd "$(dirname "$0")/.."   # mehrdad/android-app

VCODE=$(grep -oE 'versionCode +[0-9]+' app/build.gradle | grep -oE '[0-9]+')
VNAME=$(grep -oE 'versionName +"[^"]+"' app/build.gradle | grep -oE '"[^"]+"' | tr -d '"')
echo "==> نسخه: $VNAME (کد $VCODE)"

echo "==> آماده‌سازی سرور"
"${SSH[@]}" "mkdir -p $DIR/src $DIR/keystore"
cat tools/Dockerfile.build | "${SSH[@]}" "cat > $DIR/Dockerfile.build"
"${SSH[@]}" "docker image inspect mehrdad-android-build >/dev/null 2>&1" || {
  echo "==> ساخت ایمیج SDK (بار اول)"
  "${SSH[@]}" "nice -n 19 docker build --network host -f $DIR/Dockerfile.build --build-arg ACCEPT_ANDROID_LICENSES=${ACCEPT_ANDROID_LICENSES:-no} -t mehrdad-android-build $DIR"
}

echo "==> کلید امضا"
"${SSH[@]}" "if [ ! -f $DIR/keystore/mehrdad-release.jks ]; then
  PASS=\$(openssl rand -hex 16)
  docker run --rm -v $DIR/keystore:/ks mehrdad-android-build keytool -genkeypair -keystore /ks/mehrdad-release.jks \
    -alias mehrdad -keyalg RSA -keysize 2048 -validity 10000 -storepass \$PASS -keypass \$PASS -dname 'CN=Mehrdad, O=Personal' >/dev/null 2>&1
  printf 'MEHRDAD_KEYSTORE=/ks/mehrdad-release.jks\nMEHRDAD_KS_PASS=%s\n' \$PASS > $DIR/keystore/keystore.env
  chmod 600 $DIR/keystore/keystore.env $DIR/keystore/mehrdad-release.jks
  echo 'کلید امضای تازه ساخته شد'
else echo 'کلید امضای موجود'; fi"
mkdir -p "$BACKUP_DIR"
"${SSH[@]}" "cat $DIR/keystore/mehrdad-release.jks" > "$BACKUP_DIR/mehrdad-release.jks"
"${SSH[@]}" "cat $DIR/keystore/keystore.env" > "$BACKUP_DIR/keystore.env"
echo "   پشتیبان کلید: $BACKUP_DIR"

echo "==> ارسال سورس"
tar --exclude=build --exclude=.gradle --exclude=local.properties -cf - app gradle gradlew settings.gradle build.gradle gradle.properties \
  | "${SSH[@]}" "rm -rf $DIR/src && mkdir -p $DIR/src && tar -xf - -C $DIR/src"
# gradlew اگر روی ویندوز با CRLF ذخیره شده باشد در لینوکس «not found» می‌دهد
"${SSH[@]}" "sed -i 's/\\r\$//' $DIR/src/gradlew && chmod +x $DIR/src/gradlew"

echo "==> ساخت (۱ هسته، ۲.۵GB رم، اولویت پایین)"
"${SSH[@]}" "cd $DIR/src && nice -n 19 docker run --rm --network host --cpus=1 --memory=2500m \
  --env-file $DIR/keystore/keystore.env -v $DIR/keystore:/ks:ro \
  -v $DIR/src:/work -v mehrdad-gradle-cache:/root/.gradle -w /work mehrdad-android-build \
  ./gradlew assembleRelease --no-daemon --console=plain -Dorg.gradle.jvmargs=-Xmx1536m"

APK="$DIR/src/app/build/outputs/apk/release/app-release.apk"
echo "==> بررسی امضا (اثرانگشت باید در هر ساخت یکی باشد)"
"${SSH[@]}" "docker run --rm -v $DIR/src:/work mehrdad-android-build sh -c \
  '\$ANDROID_HOME/build-tools/34.0.0/apksigner verify --print-certs /work/app/build/outputs/apk/release/app-release.apk 2>&1 | grep -E \"SHA-256|Verifies|DOES NOT\"'"

echo "==> دریافت APK"
"${SSH[@]}" "cat $APK" > "$OUT"
ls -l "$OUT"

if [ "$PUBLISH" = "1" ]; then
  echo "==> انتشار برای به‌روزرسانی از داخل اپ"
  SHA=$(python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$OUT")
  SIZE=$(wc -c < "$OUT" | tr -d ' ')
  JSON=$(python -c "import json,sys;print(json.dumps({'versionCode':int(sys.argv[1]),'versionName':sys.argv[2],'sha256':sys.argv[3],'size':int(sys.argv[4]),'notes':sys.argv[5]},ensure_ascii=False))" "$VCODE" "$VNAME" "$SHA" "$SIZE" "$NOTES")
  "${SSH[@]}" "mkdir -p $APP_DATA/apk && cat > $APP_DATA/apk/mehrdad.apk.new && mv $APP_DATA/apk/mehrdad.apk.new $APP_DATA/apk/mehrdad.apk && chmod 644 $APP_DATA/apk/mehrdad.apk" < "$OUT"
  printf '%s' "$JSON" | "${SSH[@]}" "cat > $APP_DATA/apk/version.json.new && mv $APP_DATA/apk/version.json.new $APP_DATA/apk/version.json && chmod 644 $APP_DATA/apk/version.json"
  echo "   منتشر شد: نسخهٔ $VNAME، sha256=$SHA"
fi

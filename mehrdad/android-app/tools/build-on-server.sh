#!/usr/bin/env bash
# APK دیباگ را روی یک سرور Docker خارج از ایران می‌سازد و فایل را برمی‌گرداند.
# اجرا (Git Bash روی ویندوز):  ACCEPT_ANDROID_LICENSES=yes ./tools/build-on-server.sh [خروجی.apk]
# نکته: --network host و IPv6 لازم است چون روی سرورهای خاص مسیر IPv4 به dl.google.com ۴۰۴ می‌گیرد ولی IPv6 میزبان باز است.
# فقط بار اول ایمیج ساخت (~۱ گیگابایت) ساخته می‌شود؛ بعد از آن هر ساخت چند دقیقه است.
set -euo pipefail

HOST="${BUILD_HOST:-root@89.125.35.130}"
KEY="${BUILD_KEY:-$HOME/.ssh/mehrdad_nl}"
DIR=/opt/mehrdad-android-build
OUT="${1:-mehrdad-debug.apk}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ServerAliveInterval=15 "$HOST")

cd "$(dirname "$0")/.."   # mehrdad/android-app

echo "==> آماده‌سازی سرور"
"${SSH[@]}" "mkdir -p $DIR/src"
cat tools/Dockerfile.build | "${SSH[@]}" "cat > $DIR/Dockerfile.build"
"${SSH[@]}" "docker image inspect mehrdad-android-build >/dev/null 2>&1" || {
  echo "==> ساخت ایمیج SDK (بار اول)"
  "${SSH[@]}" "nice -n 19 docker build --network host -f $DIR/Dockerfile.build --build-arg ACCEPT_ANDROID_LICENSES=${ACCEPT_ANDROID_LICENSES:-no} -t mehrdad-android-build $DIR"
}

echo "==> ارسال سورس"
tar --exclude=build --exclude=.gradle --exclude=local.properties -cf - app gradle gradlew settings.gradle build.gradle gradle.properties \
  | "${SSH[@]}" "rm -rf $DIR/src && mkdir -p $DIR/src && tar -xf - -C $DIR/src"
# gradlew اگر روی ویندوز با CRLF ذخیره شده باشد در لینوکس «not found» می‌دهد
"${SSH[@]}" "sed -i 's/\\r\$//' $DIR/src/gradlew && chmod +x $DIR/src/gradlew"

echo "==> ساخت (۱ هسته، ۲.۵GB رم، اولویت پایین)"
"${SSH[@]}" "cd $DIR/src && nice -n 19 docker run --rm --network host --cpus=1 --memory=2500m \
  -v $DIR/src:/work -v mehrdad-gradle-cache:/root/.gradle -w /work mehrdad-android-build \
  ./gradlew assembleDebug --no-daemon --console=plain -Dorg.gradle.jvmargs=-Xmx1536m"

echo "==> دریافت APK"
"${SSH[@]}" "cat $DIR/src/app/build/outputs/apk/debug/app-debug.apk" > "$OUT"
ls -l "$OUT"

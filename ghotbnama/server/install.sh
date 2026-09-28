#!/usr/bin/env bash
# نصب یک‌دستوری قطب‌نما روی سرور — فقط همین سرویس را اضافه می‌کند.
#
# این اسکریپت را خودت روی سرور اجرا کن (این محیط ابری به SSH سرورهای بیرونی
# دسترسی ندارد). هیچ سرویس دیگری روی سرور را لمس نمی‌کند:
#   - همه‌چیز داخل همین پوشه (ghotbnama/server) با Docker Compose بالا می‌آید،
#     با نام پروژه مجزا "ghotbnama" (کانتینر/شبکه/ولوم‌های جدا).
#   - پورت پیش‌فرض 127.0.0.1:8080 است (فقط لوکال)؛ اگر سرویس دیگری همین پورت
#     را گرفته، PORT را در .env عوض کن.
#   - با --install-docker فقط در صورتی Docker نصب می‌شود که غایب باشد؛ بدون
#     این پرچم، اسکریپت فقط بررسی می‌کند و دستور نصب را نشان می‌دهد.
#
# اجرا:
#   git clone https://github.com/<owner>/hello-world.git && cd hello-world/ghotbnama/server
#   ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME=ghotbnama

log(){ printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
die(){ printf '\033[1;31mخطا: %s\033[0m\n' "$1" >&2; exit 1; }

INSTALL_DOCKER=0
for a in "$@"; do [ "$a" = "--install-docker" ] && INSTALL_DOCKER=1; done

log "بررسی Docker"
if ! command -v docker >/dev/null 2>&1; then
  if [ "$INSTALL_DOCKER" = 1 ]; then
    log "نصب Docker (اسکریپت رسمی get.docker.com)"
    curl -fsSL https://get.docker.com | sh
  else
    die "Docker نصب نیست. یا خودت نصبش کن، یا دوباره با ./install.sh --install-docker اجرا کن."
  fi
fi
command -v docker >/dev/null 2>&1 || die "نصب Docker ناموفق بود."
if ! docker compose version >/dev/null 2>&1; then
  die "پلاگین 'docker compose' نیست (نسخه قدیمی Docker؟). https://docs.docker.com/compose/install/ را ببین."
fi

if [ ! -f .env ]; then
  log "ساخت .env (فقط یک بار)"
  cp .env.example .env
  rnd(){ openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
  sed -i "s/^SMS_TOKEN=.*/SMS_TOKEN=$(rnd 24)/" .env
  sed -i "s/^APP_KEY=.*/APP_KEY=$(rnd 24)/" .env
  sed -i "s/^SETUP_CODE=.*/SETUP_CODE=$(rnd 6)/" .env
  echo "  .env ساخته شد با SMS_TOKEN/APP_KEY/SETUP_CODE تصادفی."
  echo "  ⚠️  هنوز BOT_TOKEN خالی است — قبل از بالا آمدن باید پرش کنی (زیر را ببین)."
else
  log ".env از قبل هست — دست نخورد"
fi

if ! grep -q '^BOT_TOKEN=.\+' .env; then
  echo
  echo "این مقادیر را در .env پر کن، بعد دوباره همین اسکریپت را اجرا کن:"
  echo "  BOT_TOKEN     ← از @BotFather در تلگرام"
  echo "  PUBLIC_URL    ← آدرس HTTPS نهایی اپ (بعد از راه‌اندازی Caddy/CDN)"
  echo "  DOMAIN        ← فقط اگر از پروفایل https (Caddy) استفاده می‌کنی"
  echo
  echo "راهنمای کامل (پروکسی تلگرام، HTTPS، فوروارد پیامک اندروید): server/README.md"
  exit 0
fi

log "بالا آوردن قطب‌نما (پروفایل proxy — رسیدن به تلگرام از ایران)"
docker compose --profile proxy up -d --build

log "وضعیت"
sleep 2
docker compose ps
echo
curl -fsS http://127.0.0.1:"$(grep -oP '^PORT=\K.*' .env 2>/dev/null || echo 8080)"/health 2>/dev/null || curl -fsS http://127.0.0.1:8080/health || true
echo
echo "اگر telegram_last_ok_seconds_ago چیزی جز null نبود، به تلگرام وصل است."
echo "بعد در تلگرام به ربات بنویس: /start <SETUP_CODE از .env>"
echo "لاگ‌ها: docker compose logs -f ghotbnama"
echo "توقف (فقط همین سرویس، بقیه سرور دست‌نخورده): docker compose down"

#!/usr/bin/env bash
# نصب یک‌دستوری مهرداد روی سرور — فقط همین سرویس را اضافه می‌کند.
#
# این اسکریپت را خودت روی سرور اجرا کن. هیچ سرویس دیگری روی سرور را لمس نمی‌کند:
#   - همه‌چیز داخل همین پوشه (mehrdad/server) با Docker Compose بالا می‌آید،
#     با نام پروژه مجزا "mehrdad" (کانتینر/شبکه/ولوم‌های جدا، کاملاً جدا از قطب‌نما).
#   - پورت پیش‌فرض 127.0.0.1:8095 است (فقط لوکال؛ با HOST_PORT در .env قابل‌تغییر).
#   - با --install-docker فقط در صورتی Docker نصب می‌شود که غایب باشد.
#
# اجرا:
#   git clone https://github.com/<owner>/hello-world.git && cd hello-world/mehrdad/server
#   ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME=mehrdad

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
  sed -i "s/^SETUP_CODE=.*/SETUP_CODE=$(rnd 6)/" .env
  echo "  .env ساخته شد با SETUP_CODE تصادفی."
  echo "  ⚠️  هنوز BOT_TOKEN و ANTHROPIC_API_KEY خالی‌اند — قبل از بالا آمدن باید پرشان کنی."
else
  log ".env از قبل هست — دست نخورد"
fi

if ! grep -q '^BOT_TOKEN=.\+' .env || ! { grep -q '^ANTHROPIC_API_KEY=.\+' .env || grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.\+' .env || [ -f data/claude/.credentials.json ]; }; then
  echo
  echo "این مقادیر را در .env پر کن، بعد دوباره همین اسکریپت را اجرا کن:"
  echo "  BOT_TOKEN                ← از @BotFather در تلگرام (یک ربات تازه، جدا از ربات قطب‌نما)"
  echo "  و یکی از این دو (مغز مهرداد):"
  echo "  CLAUDE_CODE_OAUTH_TOKEN  ← بدون هزینهٔ API، با اشتراک خودت: روی سیستم خودت «claude setup-token»"
  echo "  ANTHROPIC_API_KEY        ← پولی، از https://console.anthropic.com"
  echo
  echo "راهنمای کامل: server/README.md"
  exit 0
fi

# ولوم داده را کاربر غیر-root کانتینر (uid 10001) می‌نویسد؛ Docker پوشهٔ bind-mount را با مالک root می‌سازد
mkdir -p data
chown 10001:10001 data 2>/dev/null || sudo chown 10001:10001 data 2>/dev/null \n  || die "نمی‌توانم مالک پوشهٔ data را 10001 کنم؛ اسکریپت را با root/sudo اجرا کن."

if grep -q '^\(TELEGRAM\|ANTHROPIC\)_PROXY=.\+' .env; then
  [ -f xray/config.json ] || die "پروکسی در .env فعال است ولی xray/config.json نیست (xray/config.example.json را کپی و پر کن)."
  log "بالا آوردن مهرداد (با پروفایل proxy — سرور داخل ایران)"
  docker compose --profile proxy up -d --build
else
  log "بالا آوردن مهرداد (اتصال مستقیم — سرور خارج از ایران)"
  docker compose up -d --build
fi

log "وضعیت"
sleep 2
docker compose ps
echo
curl -fsS "http://127.0.0.1:$(grep -E '^HOST_PORT=' .env | cut -d= -f2 | grep . || echo 8095)/health" 2>/dev/null || true
echo
echo "بعد در تلگرام به ربات بنویس: /start <SETUP_CODE از .env>"
echo "لاگ‌ها: docker compose logs -f mehrdad"
echo "توقف (فقط همین سرویس، بقیه سرور دست‌نخورده): docker compose down"

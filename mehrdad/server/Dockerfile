# ساخت از پوشه mehrdad:  docker compose -f server/docker-compose.yml build
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
# 1 = باینری رسمی Claude Code هم نصب شود (برای BRAIN_PROVIDER=cli با اشتراک Claude خود کاربر)
ARG INSTALL_CLAUDE_CLI=1
ENV PYTHONUNBUFFERED=1 TZ=Asia/Tehran DATA_DIR=/data
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -r -u 10001 -m -d /home/app app && mkdir -p /data && chown app /data
# نصب Claude CLI عمداً قبل از requirements و کد است: لایهٔ سنگین و شکننده‌اش با تغییر کد یا پکیج‌ها دوباره ساخته نشود.
# وضعیت/لاگین Claude Code روی ولوم /data می‌ماند؛ آپدیت خودکار خاموش تا نسخه بین ران‌ها ثابت بماند
USER app
ENV HOME=/home/app PATH=/home/app/.local/bin:$PATH CLAUDE_CONFIG_DIR=/data/claude DISABLE_AUTOUPDATER=1
# دانلود موقت گاهی ۴۰۳ می‌دهد (Cloudflare)؛ کل نصب تا ۸ بار با وقفه دوباره امتحان می‌شود. اول فایل دانلود می‌شود (نه curl|bash)
RUN if [ "$INSTALL_CLAUDE_CLI" = "1" ]; then \
      for i in 1 2 3 4 5 6 7 8; do \
        if curl -fsSL -o /tmp/claude-install.sh https://claude.ai/install.sh && bash /tmp/claude-install.sh && claude --version; then break; fi; \
        echo "نصب Claude CLI تلاش $i ناموفق؛ ۲۰ ثانیه صبر"; sleep 20; \
      done; \
      rm -f /tmp/claude-install.sh; claude --version; \
    fi
USER root
COPY server/requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt
# کد برنامه آخر کپی می‌شود تا تغییر کد فقط همین لایهٔ سبک را باطل کند
COPY server/app ./app
USER app
EXPOSE 8081
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8081/health')" || exit 1
CMD ["python", "-m", "app.main"]

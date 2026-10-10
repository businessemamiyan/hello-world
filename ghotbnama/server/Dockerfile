# ساخت از پوشه ghotbnama:  docker compose -f server/docker-compose.yml build
# اگر Docker Hub از سرور ایران در دسترس نیست، BASE_IMAGE را به یک mirror تغییر بده (README).
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 TZ=Asia/Tehran DATA_DIR=/data WEB_FILE=/srv/web/index.html
WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt
COPY server/app ./app
COPY server/static ./static
COPY index.html ./web/index.html
RUN useradd -r -u 10001 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1
CMD ["python", "-m", "app.main"]

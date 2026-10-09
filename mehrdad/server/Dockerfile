# ساخت از پوشه mehrdad:  docker compose -f server/docker-compose.yml build
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 TZ=Asia/Tehran DATA_DIR=/data
WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt
COPY server/app ./app
RUN useradd -r -u 10001 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8081
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8081/health')" || exit 1
CMD ["python", "-m", "app.main"]

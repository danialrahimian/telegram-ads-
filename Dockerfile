FROM python:3.12-slim
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.source="https://github.com/danialrahimian/telegram-ads-" \
      org.opencontainers.image.title="psychonet-ads" \
      org.opencontainers.image.version="${APP_VERSION}"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 1000 appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# One worker only: the scheduler runs inside the web process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

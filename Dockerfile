# Telegram Ads Manager: React frontend (built with Node) served by the FastAPI backend.

# ---------- 1) frontend ----------
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---------- 2) backend dependencies ----------
FROM python:3.13-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------- 3) runtime ----------
FROM python:3.13-slim
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/venv/bin:$PATH" \
    APP_VERSION=${APP_VERSION} DATA_DIR=/app/data FRONTEND_DIST=/app/frontend/dist
LABEL org.opencontainers.image.source="https://github.com/danialrahimian/telegram-ads-" \
      org.opencontainers.image.title="Telegram Ads Manager" \
      org.opencontainers.image.description="Multi-account Telegram Ads manager with sales-bot attribution and Claude analysis" \
      org.opencontainers.image.version="${APP_VERSION}"
RUN useradd -r -u 1000 appuser && mkdir -p /app/data && chown appuser /app/data
COPY --from=deps /venv /venv
WORKDIR /app/backend
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=web /web/dist /app/frontend/dist
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# One worker only: the sync scheduler runs inside the web process. Database migrations run at startup.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

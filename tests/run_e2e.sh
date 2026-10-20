#!/usr/bin/env bash
# Starts the fake Telegram Ads API and the app on a throwaway database, then runs tests/e2e.py.
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="$(mktemp -d)"
cleanup() { kill "${MOCK_PID:-0}" "${APP_PID:-0}" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
cat > "$WORK/.env" <<ENV
TG_ADS_TOKEN=mocktoken
TG_ADS_API_BASE=http://127.0.0.1:8790
ADMIN_PASSWORD=test-password-123
SESSION_SECRET=0123456789abcdef0123456789abcdef0123456789
CONVERSIONS_SECRET=conv-secret-xyz
WITHDRAW_DELAY_SECONDS=5
COOKIE_SECURE=0
DATA_DIR=$WORK/data
ENV
MOCK_INACTIVE_SECONDS=3 python tests/mock_tgads.py 8790 > "$WORK/mock.log" 2>&1 & MOCK_PID=$!
ENV_FILE="$WORK/.env" python -m uvicorn app.main:app --port 8800 > "$WORK/app.log" 2>&1 & APP_PID=$!
for _ in $(seq 1 30); do curl -fs http://127.0.0.1:8800/healthz >/dev/null && break; sleep 1; done
if ! python tests/e2e.py "$WORK/data"; then
  echo "---- app log ----"; tail -n 80 "$WORK/app.log"; exit 1
fi
if grep -q Traceback "$WORK/app.log"; then echo "---- traceback in app log ----"; cat "$WORK/app.log"; exit 1; fi

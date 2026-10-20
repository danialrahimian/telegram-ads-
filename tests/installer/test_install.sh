#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are read inside eval'd checks
# Exercises install.sh end to end with stubbed docker/curl/network: fresh install with v1 migration,
# re-run keeps secrets, backup/restore, password change, update, uninstall. Needs bash and root (or fakeroot).
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STUB="$WORK/bin"; LOG="$WORK/calls.log"; mkdir -p "$STUB"
export TGADS_TEST_LOG="$LOG" TGADS_REPO_ROOT="$ROOT"

cat > "$STUB/docker" <<'S'
#!/usr/bin/env bash
echo "docker $*" >> "$TGADS_TEST_LOG"
case "$*" in
  "--version") echo "Docker version 27.0.0, build x" ;;
  "compose version") echo "Docker Compose version v2" ;;
  *" ps -q --status running app"*) echo "abc123" ;;
  *" ps -q caddy"*) ;;
  *" exec -T app python -c "*)
    dir="$(sed -E 's/.*--project-directory ([^ ]+).*/\1/' <<< "$*")"
    cp "$dir/data/app.db" "$dir/data/.backup.db" ;;
esac
exit 0
S
cat > "$STUB/curl" <<'S'
#!/usr/bin/env bash
echo "curl $*" >> "$TGADS_TEST_LOG"
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2 ;; -*) shift ;; *) url="$1"; shift ;; esac; done
case "$url" in
  */releases/latest) echo '{"tag_name": "v2.0.0"}' ;;
  *api.ipify.org*|*ifconfig.me*) printf '203.0.113.9' ;;
  *healthz) echo '{"ok":true}' ;;
  */deploy/docker-compose.yml) cp "$TGADS_REPO_ROOT/deploy/docker-compose.yml" "$out" ;;
  */deploy/Caddyfile) cp "$TGADS_REPO_ROOT/deploy/Caddyfile" "$out" ;;
  */install.sh) cp "$TGADS_REPO_ROOT/install.sh" "$out" ;;
  *) echo "unexpected url $url" >&2; exit 22 ;;
esac
S
printf '#!/usr/bin/env bash\necho "203.0.113.9 STREAM ads.example.com"\n' > "$STUB/getent"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/ss"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/systemctl"
chmod +x "$STUB"/*
export PATH="$STUB:$PATH"

export INSTALL_DIR="$WORK/opt/tgads" BIN_PATH="$WORK/bin-installed/tgads" LEGACY_DIR="$WORK/opt/psychonet-ads" \
  LEGACY_BIN="$WORK/legacy-bin" TGADS_RAW_BASE="https://raw.test" TGADS_API_BASE="https://api.test"
mkdir -p "$(dirname "$BIN_PATH")" "$LEGACY_DIR"
printf "TG_ADS_TOKEN='legacy-token-123'\nADMIN_PASSWORD='old-password-1'\nDOMAIN='old.example.com'\n" > "$LEGACY_DIR/.env"
touch "$LEGACY_DIR/docker-compose.yml" "$LEGACY_BIN"

pass=0
check() { if eval "$2"; then echo "  ok   $1"; pass=$((pass + 1)); else echo "  FAIL $1"; echo "--- .env"; cat "$INSTALL_DIR/.env" || true; echo "--- calls"; cat "$LOG"; exit 1; fi; }
envv() { grep -E "^$1=" "$INSTALL_DIR/.env" | cut -d= -f2- | tr -d "'"; }

echo "fresh install (migrates v1, asks nothing because DOMAIN/ADMIN_PASSWORD come from v1)"
bash "$ROOT/install.sh" install --yes < /dev/null > "$WORK/out.txt" 2>&1 || { cat "$WORK/out.txt"; exit 1; }
check "domain taken from v1"            '[ "$(envv DOMAIN)" = old.example.com ]'
check "password taken from v1"          '[ "$(envv ADMIN_PASSWORD)" = old-password-1 ]'
check "legacy token handed to the app"  '[ "$(envv LEGACY_TG_ADS_TOKEN)" = legacy-token-123 ]'
check "https mode"                      '[ "$(envv COMPOSE_PROFILES)" = https ] && [ "$(envv COOKIE_SECURE)" = 1 ]'
check "session secret generated"        '[ "$(envv SESSION_SECRET | wc -c)" -ge 48 ]'
check "fernet key is 44 chars"          '[ "$(envv ENCRYPTION_KEY | tr -d "\n" | wc -c)" -eq 44 ]'
check "image pinned to release"         '[ "$(envv APP_IMAGE)" = ghcr.io/danialrahimian/telegram-ads:2.0.0 ]'
check ".env is private"                 '[ "$(stat -c %a "$INSTALL_DIR/.env")" = 600 ]'
check "old stack stopped"               'grep -q "psychonet-ads.*down" "$LOG"'
check "old CLI removed"                 '[ ! -e "$LEGACY_BIN" ]'
check "stack started"                   'grep -q "tgads/docker-compose.yml up -d" "$LOG"'
check "cli installed"                   '[ -x "$BIN_PATH" ]'
check "summary printed"                 'grep -q "https://old.example.com" "$WORK/out.txt"'

KEY="$(envv ENCRYPTION_KEY)"
echo "re-run keeps generated secrets"
DOMAIN=ads.example.com ADMIN_PASSWORD=new-password-9 bash "$ROOT/install.sh" install --yes < /dev/null > /dev/null 2>&1
check "encryption key unchanged"        '[ "$(envv ENCRYPTION_KEY)" = "$KEY" ]'
check "domain updated"                  '[ "$(envv DOMAIN)" = ads.example.com ]'

echo "invalid domain is refused without a terminal"
rm -rf "$WORK/opt2"; mkdir -p "$WORK/opt2"
if INSTALL_DIR="$WORK/opt2/x" LEGACY_DIR="$WORK/none" DOMAIN="not a domain" ADMIN_PASSWORD=abcdefgh1 \
  bash "$ROOT/install.sh" install --yes < /dev/null > /dev/null 2>&1; then r=1; else r=0; fi
check "bad domain rejected"             '[ $r -eq 0 ]'

echo "backup, password, restore, update, uninstall"
echo "sqlite-bytes" > "$INSTALL_DIR/data/app.db"
bash "$ROOT/install.sh" backup > /dev/null 2>&1
B="$(ls "$INSTALL_DIR"/backups/tgads-*.tar.gz | head -n1)"
check "backup has db and env"           'tar -tzf "$B" | grep -q app.db && tar -tzf "$B" | grep -q env'
bash "$ROOT/install.sh" password "another-pass-77" > /dev/null 2>&1
check "password changed"                '[ "$(envv ADMIN_PASSWORD)" = another-pass-77 ]'
bash "$ROOT/install.sh" password "short" > /dev/null 2>&1 && r=1 || r=0
check "short password refused"          '[ $r -eq 0 ]'
echo "changed" > "$INSTALL_DIR/data/app.db"
bash "$ROOT/install.sh" restore "$B" --yes > /dev/null 2>&1 || true
check "restore brings the db back"      '[ "$(cat "$INSTALL_DIR/data/app.db")" = sqlite-bytes ]'
bash "$ROOT/install.sh" update --version v2.0.1 > /dev/null 2>&1
check "update pins the new image"       '[ "$(envv APP_IMAGE)" = ghcr.io/danialrahimian/telegram-ads:2.0.1 ]'
check "update recorded"                 '[ "$(envv INSTALLED_VERSION)" = v2.0.1 ]'
bash "$ROOT/install.sh" status > /dev/null 2>&1
check "status works"                    'true'
bash "$ROOT/install.sh" uninstall --yes > /dev/null 2>&1
check "uninstall keeps data with --yes" '[ -f "$INSTALL_DIR/data/app.db" ] && [ ! -e "$BIN_PATH" ]'

echo "a v1 release is never picked as the latest version"
cat > "$STUB/curl-v1" <<'S'
#!/usr/bin/env bash
echo '{"tag_name": "v1.4.0"}'
S
chmod +x "$STUB/curl-v1"
v="$(PATH="$WORK/v1bin:$PATH"; mkdir -p "$WORK/v1bin"; cp "$STUB/curl-v1" "$WORK/v1bin/curl"; bash "$ROOT/install.sh" version 2>/dev/null | tail -n1)"
check "falls back to main"              '[ "$v" = "latest: main" ]'

echo "all $pass installer checks passed"

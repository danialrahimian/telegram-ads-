#!/usr/bin/env bash
# Psychonet Telegram Ads manager - installer and management command.
#
# Install:
#   sudo bash -c "$(curl -fsSL https://github.com/danialrahimian/telegram-ads-/raw/main/install.sh)" @ install
# After install the same script is available as:  psychonet-ads <command>
#
# Commands: install, update, status, logs, restart, start, stop, backup, restore, edit, uninstall, version, help
set -Eeuo pipefail

REPO="danialrahimian/telegram-ads-"
IMAGE_REPO="ghcr.io/danialrahimian/telegram-ads"
APP="psychonet-ads"
INSTALL_DIR="${INSTALL_DIR:-/opt/$APP}"
BIN_PATH="${BIN_PATH:-/usr/local/bin/$APP}"
RAW="${PSY_RAW_BASE:-https://raw.githubusercontent.com/$REPO}"   # overridable for testing
API="${PSY_API_BASE:-https://api.github.com/repos/$REPO}"
TG_API="https://promoteapi.telegram.org"
HEALTH_URL="http://127.0.0.1:8000/healthz"
KEEP_BACKUPS=14

# ---------- output ----------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_BLU=$'\033[36m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_BLD=""; C_OFF=""
fi
info() { printf '%s==>%s %s\n' "$C_BLU" "$C_OFF" "$*"; }
ok()   { printf '%s ✓ %s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%s ! %s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
die()  { printf '%s ✗ %s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }
trap 'die "Failed at line $LINENO: $BASH_COMMAND"' ERR

# ---------- helpers ----------
need_root() { [ "$(id -u)" -eq 0 ] || die "Run as root (use sudo)."; }
installed() { [ -f "$INSTALL_DIR/.env" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; }
need_installed() { installed || die "Not installed in $INSTALL_DIR. Run: $APP install"; }
has_tty() { [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; }

ask() { # ask VAR "question" [default]
  local __var="$1" __q="$2" __def="${3:-}" __ans=""
  has_tty || die "No terminal to ask: $__q  (set $__var in the environment instead)"
  if [ -n "$__def" ]; then printf '%s [%s]: ' "$__q" "$__def" > /dev/tty; else printf '%s: ' "$__q" > /dev/tty; fi
  IFS= read -r __ans < /dev/tty || true
  printf -v "$__var" '%s' "${__ans:-$__def}"
}
ask_secret() { # ask_secret VAR "question"
  local __var="$1" __q="$2" __ans=""
  has_tty || die "No terminal to ask: $__q  (set $__var in the environment instead)"
  printf '%s: ' "$__q" > /dev/tty
  IFS= read -rs __ans < /dev/tty || true
  printf '\n' > /dev/tty
  printf -v "$__var" '%s' "$__ans"
}
ASSUME_YES="${ASSUME_YES:-}"
confirm() { # confirm "question" (default no; --yes answers yes)
  local a=""
  [ -n "$ASSUME_YES" ] && return 0
  if ! has_tty; then warn "No terminal to confirm \"$1\"; add --yes to proceed."; return 1; fi
  printf '%s [y/N]: ' "$1" > /dev/tty
  IFS= read -r a < /dev/tty || true
  [[ "$a" =~ ^[Yy]([Ee][Ss])?$ ]]
}
rand() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-40}"; }

env_get() { # env_get KEY -> value from .env
  [ -f "$INSTALL_DIR/.env" ] || return 0
  local v
  v="$(grep -E "^$1=" "$INSTALL_DIR/.env" | tail -n 1 | cut -d= -f2- || true)"
  v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}
env_set() { # env_set KEY VALUE (adds or replaces one line, keeps the file private)
  local f="$INSTALL_DIR/.env" tmp
  touch "$f"; chmod 600 "$f"
  case "$2" in *"'"*|*$'\n'*) die "$1 cannot contain a single quote or a line break." ;; esac
  tmp="$(mktemp)"
  grep -vE "^$1=" "$f" > "$tmp" || true
  # Single quotes: Docker Compose then takes the value literally (no \$ or # surprises).
  printf "%s='%s'\n" "$1" "$2" >> "$tmp"
  cat "$tmp" > "$f"; rm -f "$tmp"
}

compose() { docker compose --project-directory "$INSTALL_DIR" -f "$INSTALL_DIR/docker-compose.yml" "$@"; }

public_ip() {
  curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}'
}

port_busy() { ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

wait_healthy() {
  local _
  for _ in $(seq 1 60); do
    if curl -fs --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

# ---------- versions ----------
latest_version() {
  local tag
  tag="$(curl -fsSL --max-time 15 "$API/releases/latest" 2>/dev/null | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/' || true)"
  echo "${tag:-main}"
}
image_tag_for() { # v1.2.3 -> 1.2.3, main -> main
  local ref="$1"
  if [[ "$ref" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo "${ref#v}"; else echo "$ref"; fi
}

fetch_deploy_files() { # fetch_deploy_files REF
  local ref="$1"
  info "Downloading deployment files ($ref)"
  curl -fsSL "$RAW/$ref/deploy/docker-compose.yml" -o "$INSTALL_DIR/docker-compose.yml.new" || die "Could not download docker-compose.yml for $ref"
  curl -fsSL "$RAW/$ref/deploy/Caddyfile" -o "$INSTALL_DIR/Caddyfile.new" || die "Could not download Caddyfile for $ref"
  mv "$INSTALL_DIR/docker-compose.yml.new" "$INSTALL_DIR/docker-compose.yml"
  mv "$INSTALL_DIR/Caddyfile.new" "$INSTALL_DIR/Caddyfile"
}

install_cli() { # install_cli REF
  local tmp; tmp="$(mktemp)"
  if curl -fsSL "$RAW/$1/install.sh" -o "$tmp" && bash -n "$tmp"; then
    install -m 755 "$tmp" "$BIN_PATH"
  elif [ -f "${BASH_SOURCE[0]:-}" ] && [ "$(realpath "${BASH_SOURCE[0]}")" != "$(realpath "$BIN_PATH" 2>/dev/null || true)" ]; then
    install -m 755 "${BASH_SOURCE[0]}" "$BIN_PATH"
  fi
  rm -f "$tmp"
}

prepare_image() { # prepare_image REF -> sets APP_IMAGE in .env
  local ref="$1" image
  image="$IMAGE_REPO:$(image_tag_for "$1")"
  info "Getting the app image $image"
  if docker pull -q "$image" >/dev/null 2>&1; then
    env_set APP_IMAGE "$image"
    ok "Image ready"
    return 0
  fi
  warn "Prebuilt image not available; building from source instead (takes a minute)"
  local src="$INSTALL_DIR/src"
  rm -rf "$src"; mkdir -p "$src"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$ref" | tar -xz -C "$src" --strip-components=1 \
    || die "Could not download the source for $ref"
  docker build -q --build-arg "APP_VERSION=$ref" -t "$APP:$ref" "$src" >/dev/null || die "Build failed"
  env_set APP_IMAGE "$APP:$ref"
  ok "Built $APP:$ref"
}

ensure_docker() {
  if ! command -v curl >/dev/null 2>&1; then
    info "Installing curl"
    if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null
    else die "Please install curl first."; fi
  fi
  if ! command -v docker >/dev/null 2>&1; then
    info "Installing Docker"
    curl -fsSL https://get.docker.com | sh >/dev/null || die "Docker install failed. See https://docs.docker.com/engine/install/"
  fi
  if ! docker compose version >/dev/null 2>&1; then
    info "Installing the Docker Compose plugin"
    if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y -qq docker-compose-plugin >/dev/null
    else die "Install the Docker Compose plugin (docker compose) and run again."; fi
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
  ok "Docker $(docker --version | awk '{print $3}' | tr -d ,)"
}

check_token() { # check_token TOKEN -> prints account, returns 1 if refused
  local out
  out="$(curl -fsS --max-time 20 -X POST -H "Authorization: Bearer $1" "$TG_API/getCurrentAccount" 2>&1 || true)"
  if printf '%s' "$out" | grep -q '"ok":true'; then
    ok "Telegram Ads token works (account: $(printf '%s' "$out" | sed -nE 's/.*"title":"([^"]*)".*/\1/p'))"
    return 0
  fi
  local err; err="$(printf '%s' "$out" | sed -nE 's/.*"error":"([^"]*)".*/\1/p')"
  if [ -n "$err" ]; then warn "Telegram Ads did not accept the token: $err"
  else warn "Could not reach Telegram Ads from this server (${out:0:120})"; fi
  return 1
}

install_backup_cron() {
  [ -d /etc/cron.d ] || return 0
  printf '%s\n' "SHELL=/bin/bash" "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    "30 3 * * * root $BIN_PATH backup --quiet >/dev/null 2>&1" > "/etc/cron.d/$APP"
  chmod 644 "/etc/cron.d/$APP"
}

# ---------- commands ----------
cmd_install() {
  need_root
  local version="" domain="${DOMAIN:-}" mode="" ip
  while [ $# -gt 0 ]; do
    case "$1" in
      --version) version="${2:?}"; shift 2 ;;
      --domain) domain="${2:?}"; mode="https"; shift 2 ;;
      --tunnel|--no-https) mode="tunnel"; shift ;;
      *) die "Unknown option: $1" ;;
    esac
  done
  if installed; then
    warn "Already installed in $INSTALL_DIR."
    confirm "Re-run setup (keeps your data and settings)?" || { echo "Nothing changed. Use: $APP update"; exit 0; }
  fi

  ensure_docker
  mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/backups"
  chmod 700 "$INSTALL_DIR/backups"
  chown 1000:1000 "$INSTALL_DIR/data"   # the app runs as uid 1000 inside the container

  [ -n "$version" ] || version="$(latest_version)"
  info "Installing version $version"
  fetch_deploy_files "$version"

  # Telegram Ads token
  local token; token="$(env_get TG_ADS_TOKEN)"; token="${TG_ADS_TOKEN:-$token}"
  while true; do
    if [ -z "$token" ]; then ask_secret token "Telegram Ads API token (Telegram Ads > API > Copy Token)"; fi
    [ -n "$token" ] || { warn "The token is required."; continue; }
    if check_token "$token"; then break; fi
    warn "If you set IP restrictions in Telegram Ads, add this server's IP: $(public_ip)"
    if has_tty && confirm "Enter the token again?"; then token=""; continue; fi
    warn "Continuing anyway; the app will show the error until the token works."
    break
  done
  env_set TG_ADS_TOKEN "$token"

  # Admin password
  local pass generated=""; pass="$(env_get ADMIN_PASSWORD)"; pass="${ADMIN_PASSWORD:-$pass}"
  if [ -z "$pass" ]; then
    if has_tty; then
      ask_secret pass "Admin password for the panel (at least 10 characters, empty = generate one)"
    fi
    if [ -z "$pass" ]; then pass="$(rand 16)"; generated=1; fi
  fi
  [ "${#pass}" -ge 10 ] || die "The admin password must be at least 10 characters."
  env_set ADMIN_PASSWORD "$pass"

  [ -n "$(env_get SESSION_SECRET)" ] || env_set SESSION_SECRET "$(rand 48)"
  [ -n "$(env_get CONVERSIONS_SECRET)" ] || env_set CONVERSIONS_SECRET "$(rand 40)"
  [ -n "$(env_get ANTHROPIC_API_KEY)" ] || env_set ANTHROPIC_API_KEY ""

  # Access mode
  [ -n "$domain" ] || domain="$(env_get DOMAIN)"
  if [ -z "$mode" ]; then
    if [ -n "$domain" ]; then mode="https"
    elif has_tty; then
      ask domain "Domain for HTTPS, e.g. ads.example.com (empty = private access through an SSH tunnel)" ""
      if [ -n "$domain" ]; then mode="https"; else mode="tunnel"; fi
    else mode="tunnel"; fi
  fi
  ip="$(public_ip)"
  if [ "$mode" = "https" ]; then
    if port_busy 80 || port_busy 443; then
      if [ -n "$(compose ps -q caddy 2>/dev/null || true)" ]; then :  # it is our own Caddy
      else
        warn "Port 80 or 443 is already used by another program on this server (a VPN panel or web server?)."
        warn "HTTPS needs both ports. Switching to SSH-tunnel mode; you can run the panel on a separate small VPS for HTTPS."
        mode="tunnel"
      fi
    fi
  fi
  if [ "$mode" = "https" ]; then
    local resolved; resolved="$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [ -n "$ip" ] && [ "$resolved" != "$ip" ]; then
      warn "$domain points to '${resolved:-nothing}', not to this server ($ip). Set an A record, or HTTPS will fail."
    fi
    env_set DOMAIN "$domain"; env_set COOKIE_SECURE 1; env_set COMPOSE_PROFILES https
  else
    env_set DOMAIN ""; env_set COOKIE_SECURE 0; env_set COMPOSE_PROFILES ""
  fi
  env_set INSTALLED_VERSION "$version"

  prepare_image "$version"
  info "Starting"
  compose up -d --remove-orphans >/dev/null
  wait_healthy || die "The app did not start. Check: $APP logs"
  install_cli "$version"
  install_backup_cron
  ok "Running"

  echo
  printf '%sPsychonet Ads %s is installed.%s\n' "$C_BLD" "$version" "$C_OFF"
  if [ "$mode" = "https" ]; then
    echo "  Panel:     https://$domain"
    echo "  Purchases: https://$domain/api/conversions"
  else
    echo "  Panel is private. On your own computer run:"
    echo "    ssh -N -L 8000:127.0.0.1:8000 root@$ip"
    echo "  then open http://localhost:8000"
  fi
  if [ -n "$generated" ]; then echo "  Admin password (shown once, also in $INSTALL_DIR/.env): $pass"; fi
  echo "  Conversions secret for your bot developer:  $APP secret"
  echo
  echo "  Important: in Telegram Ads > API > IP address restrictions, add this server's IP: $ip"
  echo "  Daily backups run at 03:30 into $INSTALL_DIR/backups.   Help: $APP help"
}

cmd_update() {
  need_root; need_installed
  local version="" from
  while [ $# -gt 0 ]; do
    case "$1" in --version) version="${2:?}"; shift 2 ;; *) die "Unknown option: $1" ;; esac
  done
  from="$(env_get INSTALLED_VERSION)"
  [ -n "$version" ] || version="$(latest_version)"
  info "Updating ${from:-unknown} -> $version"
  cmd_backup --quiet || warn "Backup before update failed; continuing"
  fetch_deploy_files "$version"
  prepare_image "$version"
  env_set INSTALLED_VERSION "$version"
  compose up -d --remove-orphans >/dev/null
  wait_healthy || die "The new version did not start. Roll back with: $APP update --version ${from:-<previous>}"
  install_cli "$version"
  ok "Now running $version"
}

cmd_status() {
  need_installed
  echo "Version:  $(env_get INSTALLED_VERSION)"
  echo "Folder:   $INSTALL_DIR"
  if curl -fs --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then echo "Health:   ${C_GRN}ok${C_OFF}"; else echo "Health:   ${C_RED}not responding${C_OFF}"; fi
  compose ps
}

cmd_logs() { need_installed; compose logs -f --tail=200 "${1:-app}"; }
cmd_restart() {
  need_root; need_installed; compose up -d >/dev/null; compose restart
  if wait_healthy; then ok "Restarted"; else die "Not responding. Check: $APP logs"; fi
}
cmd_start() {
  need_root; need_installed; compose up -d >/dev/null
  if wait_healthy; then ok "Started"; else die "Not responding. Check: $APP logs"; fi
}
cmd_stop() { need_root; need_installed; compose stop; ok "Stopped (ads on Telegram keep running; the panel and automation are off)"; }

cmd_backup() {
  need_root; need_installed
  local quiet="" stamp file tmp
  [ "${1:-}" = "--quiet" ] && quiet=1
  stamp="$(date +%Y%m%d-%H%M%S)"
  tmp="$(mktemp -d)"
  # A consistent copy even while the app writes (SQLite online backup).
  if [ -n "$(compose ps -q --status running app 2>/dev/null || true)" ]; then
    compose exec -T app python -c "import sqlite3; s=sqlite3.connect('/app/data/app.db'); d=sqlite3.connect('/app/data/.backup.db'); s.backup(d); d.close(); s.close()"
    mv "$INSTALL_DIR/data/.backup.db" "$tmp/app.db"
  elif [ -f "$INSTALL_DIR/data/app.db" ]; then
    cp "$INSTALL_DIR/data/app.db" "$tmp/app.db"
  else
    rm -rf "$tmp"; warn "No database yet; nothing to back up."; return 1
  fi
  cp "$INSTALL_DIR/.env" "$tmp/env"
  file="$INSTALL_DIR/backups/$APP-$stamp.tar.gz"
  tar -czf "$file" -C "$tmp" app.db env
  chmod 600 "$file"; rm -rf "$tmp"
  # keep the newest $KEEP_BACKUPS
  ls -1t "$INSTALL_DIR/backups/$APP-"*.tar.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
  [ -n "$quiet" ] || ok "Backup: $file  (contains your .env secrets; keep it private)"
}

cmd_restore() {
  need_root; need_installed
  local file="${1:-}" tmp
  [ -n "$file" ] && [ -f "$file" ] || die "Usage: $APP restore <backup.tar.gz>   (backups are in $INSTALL_DIR/backups)"
  tmp="$(mktemp -d)"
  tar -xzf "$file" -C "$tmp" app.db 2>/dev/null || { rm -rf "$tmp"; die "Not a $APP backup: $file"; }
  confirm "Replace the current database with $file? (a backup of the current one is made first)" || { rm -rf "$tmp"; echo "Cancelled."; exit 0; }
  cmd_backup --quiet || true
  compose stop app >/dev/null
  install -o 1000 -g 1000 -m 600 "$tmp/app.db" "$INSTALL_DIR/data/app.db"
  rm -f "$INSTALL_DIR/data/app.db-wal" "$INSTALL_DIR/data/app.db-shm"
  rm -rf "$tmp"
  compose up -d >/dev/null
  if wait_healthy; then ok "Restored from $file (settings in .env were not changed)"; else die "Not responding. Check: $APP logs"; fi
}

cmd_edit() {
  need_root; need_installed
  "${EDITOR:-nano}" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  compose up -d >/dev/null
  if wait_healthy; then ok "Applied"; else die "Not responding after the change. Check: $APP logs"; fi
}

cmd_secret() { need_root; need_installed; echo "CONVERSIONS_SECRET=$(env_get CONVERSIONS_SECRET)"; }

cmd_uninstall() {
  need_root; need_installed
  confirm "Stop and remove $APP? (ads on Telegram are not touched)" || { echo "Cancelled."; exit 0; }
  compose down --remove-orphans || true
  rm -f "$BIN_PATH" "/etc/cron.d/$APP"
  if [ -z "$ASSUME_YES" ] && confirm "Also delete the database and backups in $INSTALL_DIR? This cannot be undone"; then
    rm -rf "$INSTALL_DIR"
    ok "Removed everything"
  else
    ok "Removed the app; data and backups kept in $INSTALL_DIR"
  fi
}

cmd_version() { echo "${C_BLD}$APP${C_OFF} $(env_get INSTALLED_VERSION 2>/dev/null || true)"; echo "latest: $(latest_version)"; }

cmd_help() {
  cat <<EOF
$APP - Psychonet Telegram Ads manager

  install [--version vX.Y.Z] [--domain ads.example.com | --tunnel]
  update  [--version vX.Y.Z]     update (or roll back) to a version; backs up first
  status                         version, health and containers
  logs [app|caddy]               follow logs
  restart | start | stop
  backup                         backup to $INSTALL_DIR/backups (also runs daily at 03:30)
  restore <file>                 restore the database from a backup
  (add --yes to skip confirmation questions)
  edit                           edit settings (.env) and apply
  secret                         show the conversions secret for your bot developer
  uninstall
  version | help

Non-interactive install: set TG_ADS_TOKEN, ADMIN_PASSWORD and optionally DOMAIN in the environment.
EOF
}

main() {
  local cmd="${1:-help}" a args=()
  [ $# -gt 0 ] && shift
  for a in "$@"; do if [ "$a" = "--yes" ] || [ "$a" = "-y" ]; then ASSUME_YES=1; else args+=("$a"); fi; done
  set -- "${args[@]+"${args[@]}"}"
  case "$cmd" in
    install) cmd_install "$@" ;;
    update|upgrade) cmd_update "$@" ;;
    status) cmd_status ;;
    logs) cmd_logs "$@" ;;
    restart) cmd_restart ;;
    start|up) cmd_start ;;
    stop|down) cmd_stop ;;
    backup) cmd_backup "$@" ;;
    restore) cmd_restore "$@" ;;
    edit) cmd_edit ;;
    secret) cmd_secret ;;
    uninstall|remove) cmd_uninstall ;;
    version|-v|--version) cmd_version ;;
    help|-h|--help) cmd_help ;;
    *) cmd_help; die "Unknown command: $cmd" ;;
  esac
}

main "$@"

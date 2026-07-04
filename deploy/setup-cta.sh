#!/usr/bin/env bash
# deploy/setup-cta.sh — one-shot install for hl-cta on a fresh Ubuntu host.
#
# Usage (first-time install on the server):
#   git clone <repo> vault && cd vault
#   scp'd .env.cta must already be in place (see deploy/README.md)
#   sudo bash deploy/setup-cta.sh
#
# Idempotent: safe to re-run — existing venv is reused (packages updated),
# existing .env.cta is never overwritten, existing service is restarted.
set -euo pipefail

R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' B='\033[0;34m' BOLD='\033[1m' N='\033[0m'
info()  { echo -e "${G}[OK]${N} $*"; }
warn()  { echo -e "${Y}[!]${N} $*"; }
err()   { echo -e "${R}[X]${N} $*" >&2; }
step()  { echo -e "\n${B}${BOLD}--- $* ---${N}"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env.cta"
SERVICE_TPL="$PROJECT_DIR/deploy/hl-cta.service"
SYSTEMD_DST="/etc/systemd/system/hl-cta.service"
SERVICE_USER="${SUDO_USER:-${USER:-ubuntu}}"

echo -e "${BOLD}hl-cta install — project: $PROJECT_DIR, user: $SERVICE_USER${N}"

[[ $EUID -eq 0 ]] || { err "run with sudo: sudo bash deploy/setup-cta.sh"; exit 1; }

step "1/5 system packages"
if ! command -v python3 &>/dev/null; then
    apt-get update -y -qq && apt-get install -y python3 python3-pip python3-venv
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "python3 $PYVER"
apt-get install -y "python${PYVER}-venv" &>/dev/null || true

step "2/5 python venv + package install"
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    info "venv created"
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e "$PROJECT_DIR" --quiet
info "hlvault + hl-cta entrypoint installed"

step "3/5 .env.cta check"
if [[ ! -f "$ENV_FILE" ]]; then
    err ".env.cta not found at $ENV_FILE"
    err "copy it from your local machine first, e.g.:"
    err "  scp .env.cta ubuntu@<server>:~/vault/.env.cta"
    exit 1
fi
chmod 600 "$ENV_FILE"
info ".env.cta present (chmod 600)"
if grep -q "^LIVE_TRADING=true" "$ENV_FILE"; then
    warn "LIVE_TRADING=true — this WILL place real orders on startup"
fi

step "4/5 logs dir + systemd unit"
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data/cache"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$PROJECT_DIR" 2>/dev/null || true

sed \
    -e "s|/home/ubuntu/vault|$PROJECT_DIR|g" \
    -e "s|User=ubuntu|User=$SERVICE_USER|g" \
    -e "s|Group=ubuntu|Group=$SERVICE_USER|g" \
    "$SERVICE_TPL" > "$SYSTEMD_DST"

systemctl daemon-reload
systemctl enable hl-cta
info "systemd service installed + enabled (boot-persistent, auto-restart on crash)"

step "5/5 start"
if systemctl is-active --quiet hl-cta 2>/dev/null; then
    systemctl restart hl-cta
else
    systemctl start hl-cta
fi
sleep 3
systemctl status hl-cta --no-pager --lines=15 || true

echo ""
echo -e "${G}${BOLD}done.${N}"
cat << 'TIPS'
  common commands:
    journalctl -u hl-cta -f       # live logs
    systemctl status hl-cta        # service status
    systemctl stop hl-cta          # stop (resting orders are NOT cancelled)
    systemctl restart hl-cta
    .venv/bin/hl-cta --status      # read-only state check
TIPS

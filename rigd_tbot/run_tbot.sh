#!/bin/bash
# run_tbot.sh
# Launch TradeBot Web UI (user service) + daily one-shot supervisor (timer).
# - Never reads .env files; no decryptor changes.
# - Works without a desktop session (SSH/headless) by forcing a usable user-bus.
# - Keeps IBKR installer stub exactly as before.

set -euo pipefail

LOG_TAG="[run_tbot_launcher]"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
SUPERVISOR_TEMPLATE_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor@.service"
SUPERVISOR_TIMER_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor.timer"
WEB_UNIT="$SYSTEMD_UNIT_PATH/tbot_bot.service"

# ---- Helper: robust `systemctl --user` invocations (no GUI session required)
uid="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${uid}"

userctl() {
  # Try with XDG_RUNTIME_DIR only (works on modern systems with lingering)
  if systemctl --user "$@" 2>/dev/null; then
    return 0
  fi
  # Fallback: explicitly tell systemctl which user manager to talk to
  systemctl --user --machine="$(whoami)@.host" "$@"
}

echo "$LOG_TAG Ensuring user lingering is enabled…"
if ! loginctl show-user "$(whoami)" 2>/dev/null | grep -q '^Linger=yes'; then
  sudo loginctl enable-linger "$(whoami)"
fi

echo "$LOG_TAG Preparing user systemd unit directory…"
mkdir -p "$HOME/.config/systemd/user"

echo "$LOG_TAG Linking TradeBot Web UI unit…"
ln -sf "$WEB_UNIT" "$HOME/.config/systemd/user/"

echo "$LOG_TAG Linking daily supervisor units…"
ln -sf "$SUPERVISOR_TEMPLATE_UNIT" "$HOME/.config/systemd/user/"
ln -sf "$SUPERVISOR_TIMER_UNIT"    "$HOME/.config/systemd/user/"

echo "$LOG_TAG Reloading systemd user manager…"
userctl daemon-reload || true
userctl daemon-reexec || true
# Ensure a default target is active (starts user manager if not already)
userctl start default.target || true

# === IB Gateway Auto-Deploy (stub preserved) ===
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"
IBKR_SYSTEMD_UNIT="$SYSTEMD_UNIT_PATH/ibgateway.service"

echo "$LOG_TAG Checking for IB Gateway installer…"
if [ -f "$IBKR_INSTALLER_PATH" ]; then
  echo "$LOG_TAG Found IBKR installer at $IBKR_INSTALLER_PATH"
  mkdir -p "$USER_IBKR_PATH"
  ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
  if [ -f "$IBKR_SYSTEMD_UNIT" ]; then
    ln -sf "$IBKR_SYSTEMD_UNIT" "$HOME/.config/systemd/user/"
    userctl daemon-reload || true
    echo "$LOG_TAG Enabling and starting ibgateway.service…"
    userctl enable --now ibgateway.service || true
  else
    echo "$LOG_TAG [WARN] ibgateway.service not found in systemd_units (stub only)."
  fi
else
  echo "$LOG_TAG [WARN] IBKR installer not found; IB Gateway setup skipped (stub retained)."
fi

echo "$LOG_TAG Enabling and starting Web UI (tbot_bot.service)…"
userctl enable --now tbot_bot.service

echo "$LOG_TAG Enabling daily supervisor timer (UTC 00:01 on trading days)…"
if ! userctl enable --now tbot_supervisor.timer; then
  echo "$LOG_TAG [WARN] Failed to enable/start tbot_supervisor.timer (timer can be enabled later)."
fi

# One-shot for *today* (safe no-op if timer already handled it or if provisioning locks exist)
TODAY_UTC="$(date -u +%F)"
echo "$LOG_TAG Starting today's supervisor instance: tbot_supervisor@${TODAY_UTC}.service"
userctl start "tbot_supervisor@${TODAY_UTC}.service" || true

echo "$LOG_TAG Done. Web UI should be up; supervisor is scheduled daily and kicked for today."

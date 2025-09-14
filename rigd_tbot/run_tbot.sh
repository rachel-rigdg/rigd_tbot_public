#!/bin/bash
# run_tbot.sh
# Launches TradeBot with daily one-shot supervisor via systemd user units.
# - tbot_bot.service: Web UI only
# - tbot_supervisor@.service + tbot_supervisor.timer: daily orchestration (UTC)
# No .env files are read here; runtime decrypts .env_bot.enc itself.

set -e

LOG_TAG="[run_tbot_launcher]"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"

SUPERVISOR_TEMPLATE_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor@.service"
SUPERVISOR_TIMER_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor.timer"

# === IB Gateway (stub kept exactly as requested) ============================
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"
IBKR_SYSTEMD_UNIT="$SYSTEMD_UNIT_PATH/ibgateway.service"
# ===========================================================================

# Try to ensure user systemd is reachable; don't hard-fail if dbus-launch missing
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] && [ -z "$XDG_RUNTIME_DIR" ]; then
  echo "$LOG_TAG [WARN] dbus env not present; continuing (systemctl --user may still work via lingering)."
fi

echo "$LOG_TAG Ensuring user lingering is enabled…"
if ! loginctl show-user "$(id -u)" 2>/dev/null | grep -q "Linger=yes"; then
  sudo loginctl enable-linger "$(whoami)"
fi

echo "$LOG_TAG Preparing user systemd unit directory…"
mkdir -p "$HOME/.config/systemd/user"

echo "$LOG_TAG Linking TradeBot Web UI unit…"
ln -sf "$SYSTEMD_UNIT_PATH/tbot_bot.service" "$HOME/.config/systemd/user/tbot_bot.service"

echo "$LOG_TAG Linking daily supervisor units…"
ln -sf "$SUPERVISOR_TEMPLATE_UNIT" "$HOME/.config/systemd/user/tbot_supervisor@.service"
ln -sf "$SUPERVISOR_TIMER_UNIT" "$HOME/.config/systemd/user/tbot_supervisor.timer"

# === IB Gateway Auto-Deploy (stub retained) =================================
echo "$LOG_TAG Checking for IB Gateway installer…"
if [ -f "$IBKR_INSTALLER_PATH" ]; then
  echo "$LOG_TAG Found IBKR Gateway installer at $IBKR_INSTALLER_PATH"
  mkdir -p "$USER_IBKR_PATH"
  ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
  if [ -f "$IBKR_SYSTEMD_UNIT" ]; then
    ln -sf "$IBKR_SYSTEMD_UNIT" "$HOME/.config/systemd/user/ibgateway.service"
    echo "$LOG_TAG Linked ibgateway.service"
  else
    echo "$LOG_TAG [WARN] ibgateway.service unit not found in systemd_units; provide one to manage IBKR."
  fi
else
  echo "$LOG_TAG [WARN] IBKR installer not found; IB Gateway setup skipped (stub retained)."
fi
# ===========================================================================

echo "$LOG_TAG Reloading systemd user manager…"
systemctl --user daemon-reload || true

echo "$LOG_TAG Enabling and starting Web UI (tbot_bot.service)…"
systemctl --user enable --now tbot_bot.service

echo "$LOG_TAG Enabling daily supervisor timer (UTC 00:01 on trading days)…"
systemctl --user enable --now tbot_supervisor.timer

# Fire today’s one-shot run (safe no-op if already ran/locked)
TODAY_UTC="$(date -u +%F)"
echo "$LOG_TAG Starting today’s supervisor: tbot_supervisor@${TODAY_UTC}.service"
systemctl --user start "tbot_supervisor@${TODAY_UTC}.service" || true

echo "$LOG_TAG Done. Web UI is up; supervisor scheduled daily (and triggered once today)."

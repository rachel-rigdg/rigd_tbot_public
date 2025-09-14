#!/bin/bash
# run_tbot.sh
# Launches TradeBot with daily one-shot supervisor via systemd *user* units.
# - tbot_bot.service: Web UI only
# - tbot_supervisor@.service + tbot_supervisor.timer: daily orchestration (UTC)
# Keeps IBKR stub in place (no changes needed elsewhere).

set -euo pipefail

LOG_TAG="[run_tbot_launcher]"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"

SUPERVISOR_TEMPLATE_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor@.service"
SUPERVISOR_TIMER_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor.timer"
WEB_UNIT="$SYSTEMD_UNIT_PATH/tbot_bot.service"
IBKR_SYSTEMD_UNIT="$SYSTEMD_UNIT_PATH/ibgateway.service"

# IBKR stub (kept intact)
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"

echo "$LOG_TAG Ensuring user lingering is enabled…"
if ! loginctl show-user "$(id -u)" 2>/dev/null | grep -q "Linger=yes"; then
  sudo loginctl enable-linger "$(whoami)"
fi

echo "$LOG_TAG Preparing user systemd unit directory…"
mkdir -p "$HOME/.config/systemd/user/"

echo "$LOG_TAG Linking TradeBot Web UI unit…"
ln -sf "$WEB_UNIT" "$HOME/.config/systemd/user/"

echo "$LOG_TAG Linking daily supervisor units…"
[ -f "$SUPERVISOR_TEMPLATE_UNIT" ] || { echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TEMPLATE_UNIT"; exit 1; }
[ -f "$SUPERVISOR_TIMER_UNIT" ]    || { echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TIMER_UNIT"; exit 1; }
ln -sf "$SUPERVISOR_TEMPLATE_UNIT" "$HOME/.config/systemd/user/"
ln -sf "$SUPERVISOR_TIMER_UNIT"    "$HOME/.config/systemd/user/"

# --- IB Gateway stub (kept) ---
echo "$LOG_TAG Checking for IB Gateway installer…"
if [ -f "$IBKR_INSTALLER_PATH" ]; then
  echo "$LOG_TAG Found IBKR Gateway installer at $IBKR_INSTALLER_PATH"
  mkdir -p "$USER_IBKR_PATH"
  ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
  if [ -f "$IBKR_SYSTEMD_UNIT" ]; then
    ln -sf "$IBKR_SYSTEMD_UNIT" "$HOME/.config/systemd/user/"
  else
    echo "$LOG_TAG [WARN] No ibgateway.service found in systemd_units (stub retained)."
  fi
else
  echo "$LOG_TAG [WARN] IBKR installer not found; IB Gateway setup skipped (stub retained)."
fi

# --- Make systemctl --user usable even on plain SSH sessions ---
# Provide sane defaults if dbus env not present. This does NOT start the bus;
# it just points systemctl at the expected socket path if the user manager is running.
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

echo "$LOG_TAG Reloading systemd user manager…"
if ! systemctl --user daemon-reload 2>/dev/null; then
  echo "$LOG_TAG [WARN] user systemd bus not reachable. Trying to kick it by re-login/lingering."
  echo "$LOG_TAG [HINT] If this persists, log out and back in (or reboot) once after enabling linger."
fi

echo "$LOG_TAG Enabling and starting Web UI (tbot_bot.service)…"
if ! systemctl --user enable --now tbot_bot.service 2>/dev/null; then
  echo "$LOG_TAG [ERROR] Failed to enable/start tbot_bot.service via user systemd."
  echo "$LOG_TAG [FALLBACK] Launching Web UI directly (no systemd) so you can configure the bot…"
  exec /usr/bin/python3 -m tbot_bot.runtime.main
fi

echo "$LOG_TAG Enabling daily supervisor timer (UTC 00:01 on trading days)…"
systemctl --user enable --now tbot_supervisor.timer || {
  echo "$LOG_TAG [WARN] Failed to enable/start tbot_supervisor.timer (will still try one-shot today)."
}

# Kick off today's one-shot run explicitly (safe no-op if lock already exists)
TODAY_UTC="$(date -u +%F)"
echo "$LOG_TAG Starting today's supervisor instance: tbot_supervisor@${TODAY_UTC}.service"
systemctl --user start "tbot_supervisor@${TODAY_UTC}.service" 2>/dev/null || true

echo "$LOG_TAG TradeBot launched. Web UI active; supervisor timer scheduled daily (and started for today when possible)."

#!/bin/bash
# run_tbot.sh
# Launches TradeBot with daily one-shot supervisor via systemd user units.
# - tbot_bot.service: Web UI only
# - tbot_supervisor@.service + tbot_supervisor.timer: daily orchestration (UTC)

set -e

export XDG_RUNTIME_DIR=/run/user/$(id -u)
export FLASK_ENV=development
export FLASK_DEBUG=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"
IBKR_SYSTEMD_UNIT="$ROOT_DIR/systemd_units/ibgateway.service"
LOG_TAG="[run_tbot_launcher]"

SUPERVISOR_TEMPLATE_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor@.service"
SUPERVISOR_TIMER_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor.timer"

# Ensure user session bus is available
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    export $(dbus-launch)
fi

echo "$LOG_TAG Checking if user lingering is enabled..."
if ! loginctl show-user "$(id -u)" | grep -q "Linger=yes"; then
    echo "$LOG_TAG Enabling user lingering for $(whoami)..."
    sudo loginctl enable-linger "$(whoami)"
fi

echo "$LOG_TAG Preparing user systemd unit directory..."
mkdir -p ~/.config/systemd/user/

echo "$LOG_TAG Stopping any existing TradeBot core web service (if running)..."
systemctl --user stop tbot_bot.service || true

echo "$LOG_TAG Reloading systemd user manager..."
systemctl --user daemon-reexec || true
systemctl --user daemon-reload || true

echo "$LOG_TAG Linking systemd unit file for TradeBot Web UI..."
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.service ~/.config/systemd/user/

echo "$LOG_TAG Linking daily supervisor units..."
if [ -f "$SUPERVISOR_TEMPLATE_UNIT" ]; then
  ln -sf "$SUPERVISOR_TEMPLATE_UNIT" ~/.config/systemd/user/
else
  echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TEMPLATE_UNIT"; exit 1
fi
if [ -f "$SUPERVISOR_TIMER_UNIT" ]; then
  ln -sf "$SUPERVISOR_TIMER_UNIT" ~/.config/systemd/user/
else
  echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TIMER_UNIT"; exit 1
fi

# === IB Gateway Auto-Deploy (for remote/server use) ===
echo "$LOG_TAG Checking for IB Gateway installer..."
if [ -f "$IBKR_INSTALLER_PATH" ]; then
    echo "$LOG_TAG Found IBKR Gateway installer at $IBKR_INSTALLER_PATH"
    mkdir -p "$USER_IBKR_PATH"
    ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
    # Copy or update systemd user unit for IB Gateway if available
    if [ -f "$IBKR_SYSTEMD_UNIT" ]; then
        ln -sf "$IBKR_SYSTEMD_UNIT" ~/.config/systemd/user/
        echo "$LOG_TAG Linked IB Gateway systemd service."
        systemctl --user daemon-reload
        echo "$LOG_TAG Enabling and starting ibgateway.service..."
        systemctl --user enable --now ibgateway.service
    else
        echo "$LOG_TAG [WARN] No ibgateway.service found in systemd_units. Please provide a user-level systemd unit for IB Gateway."
    fi
else
    echo "$LOG_TAG [WARN] IBKR Gateway installer not found at $IBKR_INSTALLER_PATH. Skipping IB Gateway setup."
fi

echo "$LOG_TAG Reloading user units after linking…"
systemctl --user daemon-reload

echo "$LOG_TAG Enabling and starting Web UI (tbot_bot.service)…"
systemctl --user enable --now tbot_bot.service

echo "$LOG_TAG Enabling daily supervisor timer (UTC 00:01 on trading days)…"
systemctl --user enable --now tbot_supervisor.timer

# Kick off today's one-shot run explicitly (safe no-op if already ran/locked)
TODAY_UTC="$(date -u +%F)"
echo "$LOG_TAG Starting today's supervisor instance: tbot_supervisor@${TODAY_UTC}.service"
systemctl --user start "tbot_supervisor@${TODAY_UTC}.service" || true

echo "$LOG_TAG TradeBot launched. Web UI is active; supervisor is scheduled daily via timer and started for today."

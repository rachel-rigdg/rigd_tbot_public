#!/bin/bash
# run_tbot.sh
# Launches TradeBot unified entrypoint (main.py is a pure dispatcher: only launches Flask UI and tbot_supervisor.py).
# All persistent worker/watcher/test runner modules are launched exclusively by tbot_supervisor.py (v045+).

set -e

export XDG_RUNTIME_DIR=/run/user/$(id -u)
export FLASK_ENV=development
export FLASK_DEBUG=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
LOG_TAG="[run_tbot_launcher]"

# Ensure user session bus is available
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    export $(dbus-launch)
fi

echo "$LOG_TAG Checking if user lingering is enabled..."
if ! loginctl show-user $(id -u) | grep -q "Linger=yes"; then
    echo "$LOG_TAG Enabling user lingering for $(whoami)..."
    sudo loginctl enable-linger $(whoami)
fi

echo "$LOG_TAG Stopping any existing TradeBot core systemd process..."
systemctl --user stop tbot_bot.service || true

systemctl --user daemon-reexec
systemctl --user daemon-reload

echo "$LOG_TAG Linking systemd unit file for TradeBot core..."
mkdir -p ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.service ~/.config/systemd/user/

systemctl --user daemon-reload

echo "$LOG_TAG Enabling and starting tbot_bot.service..."
systemctl --user enable --now tbot_bot.service

echo "$LOG_TAG TradeBot launched. Supervisor orchestration is enforced. Unified runtime and web UI are ready for testing."

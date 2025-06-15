#!/bin/bash
# run_tbot.sh
# Launches TradeBot unified entrypoint (main.py manages all phases and Flask apps).

set -e

export XDG_RUNTIME_DIR=/run/user/$(id -u)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
LOG_TAG="[run_tbot_launcher]"

echo "$LOG_TAG Stopping any existing TradeBot core systemd process..."
systemctl --user stop tbot_bot.service || true

systemctl --user daemon-reexec
systemctl --user daemon-reload

echo "$LOG_TAG Linking systemd unit file for TradeBot core..."
mkdir -p ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.service ~/.config/systemd/user/

systemctl --user daemon-reload

echo "$LOG_TAG Enabling and starting tbot_bot.service..."
systemctl --user enable tbot_bot.service
systemctl --user start tbot_bot.service

echo "$LOG_TAG TradeBot launched. Unified runtime and web UI are ready for testing."

#!/bin/bash
# run_tbot.sh
# One-time setup: Enables all systemd services for TradeBot (web UI, provisioning, bot), launches Flask web UI for configuration/provisioning.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
LOG_TAG="[run_tbot_webui_launcher]"

echo "$LOG_TAG Killing any existing TradeBot systemd processes..."
sudo systemctl stop tbot_web.service tbot_provisioning.service tbot_bot.service tbot_bot.path || true
sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "$LOG_TAG Copying all systemd unit files for TradeBot..."
sudo cp "$SYSTEMD_UNIT_PATH"/tbot_web.service "$SYSTEMD_UNIT_PATH"/tbot_provisioning.service "$SYSTEMD_UNIT_PATH"/tbot_bot.service "$SYSTEMD_UNIT_PATH"/tbot.target "$SYSTEMD_UNIT_PATH"/tbot_bot.path /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable tbot_web.service tbot_provisioning.service tbot_bot.service tbot_bot.path
sudo systemctl start tbot_web.service
sudo systemctl start tbot_provisioning.service
sudo systemctl start tbot_bot.path

echo "$LOG_TAG TradeBot Web UI launched using systemd (tbot_web.service)."
echo "$LOG_TAG Proceed to configure the bot using the web UI."

PYTHON_BIN="python3"
WEB_DIR="$ROOT_DIR/tbot_web"
HOST=$($PYTHON_BIN - <<EOF
import sys; sys.path.insert(0, "$ROOT_DIR")
from tbot_bot.config.network_config import get_host_ip
print(get_host_ip())
EOF
)
PORT=$($PYTHON_BIN - <<EOF
import sys; sys.path.insert(0, "$ROOT_DIR")
from tbot_bot.config.network_config import get_port
print(get_port())
EOF
)
URL="http://${HOST}:${PORT}"

if command -v open > /dev/null; then
    open "$URL"
elif command -v xdg-open > /dev/null; then
    xdg-open "$URL"
else
    echo "$LOG_TAG No browser launcher available. UI available at: $URL"
fi

echo "$LOG_TAG You may now proceed with configuration. Provisioning and bot launch will be triggered by the web UI workflow."

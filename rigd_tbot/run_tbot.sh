#!/bin/bash
# run_tbot.sh
# Launches phase supervisor, which orchestrates all phases.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
LOG_TAG="[run_tbot_webui_launcher]"

echo "$LOG_TAG Killing any existing TradeBot systemd processes..."
systemctl --user stop tbot_web_bootstrap.service tbot_provisioning.service tbot_web_registration.service tbot_web_main.service tbot_bot.service phase_supervisor.service || true
systemctl --user daemon-reexec
systemctl --user daemon-reload

echo "$LOG_TAG Copying systemd unit files for ALL phases and supervisor..."
mkdir -p ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_web_bootstrap.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_provisioning.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_web_registration.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_web_main.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/phase_supervisor.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.path ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot.target ~/.config/systemd/user/

systemctl --user daemon-reload

systemctl --user enable phase_supervisor.service
systemctl --user start phase_supervisor.service

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

echo "$LOG_TAG Supervisor launched. All phases will be managed automatically."

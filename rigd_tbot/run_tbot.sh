#!/bin/bash
# run_tbot.sh
# Launches TradeBot phase supervisor only (direct Flask apps launched by supervisor).

set -e

export XDG_RUNTIME_DIR=/run/user/$(id -u)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"
LOG_TAG="[run_tbot_webui_launcher]"

echo "$LOG_TAG Stopping any existing TradeBot systemd processes..."
systemctl --user stop tbot_bot.service tbot_web_router.service phase_supervisor.service || true

systemctl --user daemon-reexec
systemctl --user daemon-reload

echo "$LOG_TAG Linking systemd unit files for TradeBot core, web router, and phase supervisor..."
mkdir -p ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_web_router.service ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/tbot_bot.path ~/.config/systemd/user/
ln -sf "$SYSTEMD_UNIT_PATH"/phase_supervisor.service ~/.config/systemd/user/

systemctl --user daemon-reload

echo "$LOG_TAG Disabling and stopping tbot_web_router.service (replaced by phase_supervisor)..."
systemctl --user disable tbot_web_router.service || true
systemctl --user stop tbot_web_router.service || true

echo "$LOG_TAG Enabling and starting phase_supervisor.service..."
systemctl --user enable phase_supervisor.service
systemctl --user start phase_supervisor.service

# DO NOT enable/start tbot_bot.service here; it must be started only after provisioning and registration are complete by phase_supervisor.

PYTHON_BIN="python3"
WEB_DIR="$ROOT_DIR/tbot_web"
HOST=$($PYTHON_BIN - <<EOF
import sys; sys.path.insert(0, "$ROOT_DIR")
from tbot_bot.config.network_config import get_host_ip
print(get_host_ip())
EOF
)
PORT=6900
URL="http://${HOST}:${PORT}"

if command -v open > /dev/null; then
    open "$URL"
elif command -v xdg-open > /dev/null; then
    xdg-open "$URL"
else
    echo "$LOG_TAG No browser launcher available. UI available at: $URL"
fi

echo "$LOG_TAG Phase supervisor launched. TradeBot ready for UI/phase testing."

#!/bin/bash
# run_tbot.sh
# Unified launcher for TradeBot web UI (bootstrap-aware, launches bot after provisioning)

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="python3"
BOT_DIR="$ROOT_DIR/tbot_bot"
WEB_DIR="$ROOT_DIR/tbot_web"
ENC_ENV_ROOT="$ROOT_DIR/.env.enc"
KEY_ENV_ROOT="$ROOT_DIR/tbot_bot/storage/keys/env.key"
ENC_ENV_BOT="$ROOT_DIR/tbot_bot/storage/secrets/.env_bot.enc"
KEY_ENV_BOT="$ROOT_DIR/tbot_bot/storage/keys/env_bot.key"
DB_PATH="$BOT_DIR/core/databases/SYSTEM_USERS.db"
LOG_TAG="[run_tbot_web_bootstrap]"

# Step 0: Decrypt .env.enc in-memory and export each valid KEY=VALUE pair (never write .env to disk)
if [[ -f "$ENC_ENV_ROOT" && -f "$KEY_ENV_ROOT" ]]; then
    echo "$LOG_TAG Decrypting and exporting .env.enc to shell environment..."
    PLAINTEXT=$($PYTHON_BIN - <<EOF
from cryptography.fernet import Fernet
import json
import re
key = open("$KEY_ENV_ROOT","r").read().strip().encode()
f = Fernet(key)
data = json.loads(f.decrypt(open("$ENC_ENV_ROOT","rb").read()).decode())
for k, v in data.items():
    k = k.strip()
    v = str(v).strip()
    # Only export valid shell variables
    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', k):
        print(f"{k}={v}")
EOF
)
    while IFS= read -r line; do
        [[ -z $line ]] && continue
        export "$line"
    done <<< "$PLAINTEXT"
else
    echo "$LOG_TAG Skipping root env decryption — .env.enc or key missing."
fi

# Step 1: (Optional for dev/bootstrap only!) Decrypt .env_bot.enc to .env_bot
if [[ -n "$BOOTSTRAP_DEV" && -f "$ENC_ENV_BOT" && -f "$KEY_ENV_BOT" ]]; then
    echo "$LOG_TAG [DEV ONLY] Decrypting .env_bot.enc..."
    PYTHONPATH="$ROOT_DIR" $PYTHON_BIN -m tbot_bot.config.security_bot write
else
    echo "$LOG_TAG Skipping bot config decryption (prod-safe default)."
fi

# Step 2: Check if port is in use and kill if necessary
PORT_CHECK=$($PYTHON_BIN - <<EOF
import sys; sys.path.insert(0, "$ROOT_DIR")
from tbot_bot.config.network_config import get_port
print(get_port())
EOF
)

if lsof -iTCP:"$PORT_CHECK" -sTCP:LISTEN -t >/dev/null ; then
    echo "$LOG_TAG Port $PORT_CHECK is already in use. Killing existing process."
    kill -9 $(lsof -iTCP:"$PORT_CHECK" -sTCP:LISTEN -t)
    sleep 2
fi

# Step 3: Launch Flask web server in background
export PYTHONPATH="$ROOT_DIR"
echo "$LOG_TAG Starting Flask server..."
$PYTHON_BIN "$WEB_DIR/py/run_web.py" &
WEB_PID=$!

sleep 2

# Step 4: Retrieve host and port from encrypted network config
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

# Step 5: Determine bootstrap status and open browser
if [[ -f "$DB_PATH" ]]; then
    echo "$LOG_TAG Opening normal UI: $URL/"
    TARGET_URL="$URL/"
else
    echo "$LOG_TAG Bootstrapping required. Opening: $URL/"
    TARGET_URL="$URL/"
fi

if command -v open > /dev/null; then
    open "$TARGET_URL"
elif command -v xdg-open > /dev/null; then
    xdg-open "$TARGET_URL"
else
    echo "$LOG_TAG No browser launcher available."
fi

# ---- STEP 6: AUTO-LAUNCH BOT WHEN PROVISIONING IS COMPLETE ----

echo "$LOG_TAG Waiting for provisioning (.env_bot.enc + SYSTEM_USERS.db)..."
while [[ ! -f "$DB_PATH" || ! -f "$ENC_ENV_BOT" ]]; do
    sleep 2
done

echo "$LOG_TAG Provisioning complete. Starting TradeBot core engine..."

# Main bot launch — replace tbot_bot.main with your bot entrypoint/module
$PYTHON_BIN -m tbot_bot.main &

wait $WEB_PID

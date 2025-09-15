#!/bin/bash
# run_tbot.sh
# Single, robust launcher for TradeBot.
# - No systemd required (and none used here).
# - Runs main.py directly and auto-restarts on crash.
# - Binds Flask to 0.0.0.0 by default (override with TBOT_WEB_HOST).
# - Preserves IBKR installer stub behavior.
# - Keeps output verbose and appends to a simple launcher log.
#
# Usage:
#   ./run_tbot.sh
#
# Env overrides (optional):
#   TBOT_WEB_HOST=0.0.0.0
#   TBOT_WEB_PORT=6900
#   TBOT_WAIT_OPS_SECS=90
#   TBOT_WAIT_BOOTSTRAP_SECS=120

set -euo pipefail

LOG_TAG="[run_tbot]"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Defaults (can be overridden by env) ----
export TBOT_WEB_HOST="${TBOT_WEB_HOST:-0.0.0.0}"   # bind to all interfaces by default
export TBOT_WEB_PORT="${TBOT_WEB_PORT:-6900}"
export TBOT_WAIT_OPS_SECS="${TBOT_WAIT_OPS_SECS:-90}"
export TBOT_WAIT_BOOTSTRAP_SECS="${TBOT_WAIT_BOOTSTRAP_SECS:-120}"

MAIN_PY="$ROOT_DIR/tbot_bot/runtime/main.py"

# Simple launcher log (separate from the bot's own logs)
LAUNCHER_LOG="$ROOT_DIR/launcher.log"
log(){ echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') $LOG_TAG $*" | tee -a "$LAUNCHER_LOG"; }

# ---- IB Gateway Auto-Deploy (stub preserved) ----
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"

log "Checking for IB Gateway installer…"
if [ -f "$IBKR_INSTALLER_PATH" ]; then
  log "Found IBKR installer at $IBKR_INSTALLER_PATH"
  mkdir -p "$USER_IBKR_PATH"
  ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
else
  log "[WARN] IBKR installer not found; IB Gateway setup skipped (stub retained)."
fi

# ---- Sanity checks ----
if [ ! -f "$MAIN_PY" ]; then
  log "[FATAL] $MAIN_PY not found."
  exit 1
fi

# ---- Trap & child management ----
child_pid=""
terminate() {
  log "Terminate requested; forwarding to child ($child_pid)…"
  if [[ -n "${child_pid}" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM "$child_pid" || true
    wait "$child_pid" || true
  fi
  log "Exited cleanly."
  exit 0
}
trap terminate INT TERM

# ---- Run loop with simple backoff ----
BACKOFF=3
MAX_BACKOFF=30

log "Starting TradeBot main.py (host=${TBOT_WEB_HOST} port=${TBOT_WEB_PORT})"
while true; do
  # -u for unbuffered stdout so logs stream correctly
  set +e
  python3 -u "$MAIN_PY" 2>&1 | tee -a "$LAUNCHER_LOG" &
  child_pid=$!
  wait "$child_pid"
  exit_code=$?
  set -e

  if [ $exit_code -eq 0 ]; then
    log "main.py exited normally (code 0). Stopping launcher."
    break
  fi

  log "main.py crashed (exit $exit_code). Restarting in ${BACKOFF}s…"
  sleep "$BACKOFF"
  # backoff up to MAX_BACKOFF
  if [ $BACKOFF -lt $MAX_BACKOFF ]; then
    BACKOFF=$(( BACKOFF * 2 ))
    [ $BACKOFF -gt $MAX_BACKOFF ] && BACKOFF=$MAX_BACKOFF
  fi
done

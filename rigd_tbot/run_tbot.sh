#!/bin/bash
# run_tbot.sh
# Launches TradeBot with daily one-shot supervisor via systemd user units.
# - tbot_bot.service: Web UI only
# - tbot_supervisor@.service + tbot_supervisor.timer: daily orchestration (UTC)
# Keeps IBKR Gateway stub wiring (disabled if installer not found).

set -e

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export FLASK_ENV=development
export FLASK_DEBUG=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_PATH="$ROOT_DIR/systemd_units"

# ---- IBKR stub (kept) ----
IBKR_INSTALLER_PATH="$ROOT_DIR/../../IBKR/ibgateway-stable-standalone-linux-x64.sh"
USER_IBKR_PATH="$HOME/IBKR"
IBKR_SYMLINK="$USER_IBKR_PATH/ibgateway.sh"
IBKR_SYSTEMD_UNIT="$SYSTEMD_UNIT_PATH/ibgateway.service"

LOG_TAG="[run_tbot_launcher]"

SUPERVISOR_TEMPLATE_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor@.service"
SUPERVISOR_TIMER_UNIT="$SYSTEMD_UNIT_PATH/tbot_supervisor.timer"
WEB_UI_UNIT="$SYSTEMD_UNIT_PATH/tbot_bot.service"

PROVISION_LOCK="$ROOT_DIR/tbot_bot/control/provisioning.lock"
BOOTSTRAP_LOCK="$ROOT_DIR/tbot_bot/control/bootstrapping.lock"

# Optional: export TBOT_* to the user manager so unit EnvironmentFile isn't required
TBOT_WORKDIR="$ROOT_DIR"
TBOT_PYTHON="$ROOT_DIR/venv/bin/python3"

# Ensure user session bus is available (skip if dbus-launch missing)
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  if command -v dbus-launch >/dev/null 2>&1; then
    # shellcheck disable=SC2046
    export $(dbus-launch)
  else
    echo "$LOG_TAG [WARN] dbus-launch not found; continuing without it."
  fi
fi

echo "$LOG_TAG Ensuring user lingering is enabled…"
if ! loginctl show-user "$(id -u)" 2>/dev/null | grep -q "Linger=yes"; then
  if command -v sudo >/dev/null 2>&1; then
    sudo loginctl enable-linger "$(whoami)" || true
  else
    loginctl enable-linger "$(whoami)" || true
  fi
fi

echo "$LOG_TAG Preparing user systemd unit directory…"
mkdir -p "$HOME/.config/systemd/user"

echo "$LOG_TAG Linking TradeBot Web UI unit…"
ln -sf "$WEB_UI_UNIT" "$HOME/.config/systemd/user/"

echo "$LOG_TAG Linking daily supervisor units…"
[ -f "$SUPERVISOR_TEMPLATE_UNIT" ] || { echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TEMPLATE_UNIT"; exit 1; }
[ -f "$SUPERVISOR_TIMER_UNIT" ]    || { echo "$LOG_TAG [ERROR] Missing $SUPERVISOR_TIMER_UNIT"; exit 1; }
ln -sf "$SUPERVISOR_TEMPLATE_UNIT" "$HOME/.config/systemd/user/"
ln -sf "$SUPERVISOR_TIMER_UNIT"    "$HOME/.config/systemd/user/"

# ---- IBKR stub wiring (safe no-op if assets missing) ----
echo "$LOG_TAG Checking for IB Gateway installer…"
if [ -f "$IBKR_INSTALLER_PATH" ]; then
  echo "$LOG_TAG Found IBKR Gateway installer at $IBKR_INSTALLER_PATH"
  mkdir -p "$USER_IBKR_PATH"
  ln -sf "$IBKR_INSTALLER_PATH" "$IBKR_SYMLINK"
  if [ -f "$IBKR_SYSTEMD_UNIT" ]; then
    ln -sf "$IBKR_SYSTEMD_UNIT" "$HOME/.config/systemd/user/"
    echo "$LOG_TAG Linked ibgateway.service unit."
  else
    echo "$LOG_TAG [WARN] No ibgateway.service found in systemd_units (stub retained)."
  fi
else
  echo "$LOG_TAG [WARN] IBKR installer not found; IB Gateway setup skipped (stub retained)."
fi

echo "$LOG_TAG Reloading systemd user manager…"
systemctl --user daemon-reexec || true
systemctl --user daemon-reload || true

# Pass TBOT_* to the user manager so units can pick them up
echo "$LOG_TAG Exporting TBOT_WORKDIR/TBOT_PYTHON to user manager…"
systemctl --user set-environment TBOT_WORKDIR="$TBOT_WORKDIR" TBOT_PYTHON="$TBOT_PYTHON" || true
systemctl --user import-environment TBOT_WORKDIR TBOT_PYTHON || true

# Start Web UI first so you can configure before orchestration ever runs
echo "$LOG_TAG Enabling and starting Web UI (tbot_bot.service)…"
systemctl --user enable --now tbot_bot.service

# Enable daily supervisor timer (it will be gated by service Conditions)
echo "$LOG_TAG Enabling daily supervisor timer (UTC 00:01 on trading days)…"
systemctl --user enable --now tbot_supervisor.timer || true

# Optional: start today's one-shot supervisor only if NOT in bootstrap/provisioning
TODAY_UTC="$(date -u +%F)"
if [ ! -f "$PROVISION_LOCK" ] && [ ! -f "$BOOTSTRAP_LOCK" ]; then
  echo "$LOG_TAG Starting today's supervisor instance: tbot_supervisor@${TODAY_UTC}.service"
  systemctl --user start "tbot_supervisor@${TODAY_UTC}.service" || true
else
  echo "$LOG_TAG Supervisor launch skipped (bootstrap/provisioning lock present). Timer will handle future runs."
fi

# Start IB Gateway if unit is present (optional)
if systemctl --user list-unit-files | grep -q "^ibgateway.service"; then
  echo "$LOG_TAG Enabling/starting ibgateway.service…"
  systemctl --user enable --now ibgateway.service || true
fi

echo "$LOG_TAG Done. Web UI is active; supervisor is scheduled daily via timer."

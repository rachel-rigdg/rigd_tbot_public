#!/bin/bash
# restart_systemd.sh
# User-mode systemd helper with robust bus handling (no desktop session required).

set -euo pipefail
uid="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${uid}"

userctl() {
  if systemctl --user "$@" 2>/dev/null; then
    return 0
  fi
  systemctl --user --machine="$(whoami)@.host" "$@"
}

SERVICES=(
  "tbot_bot.service"
  "tbot_supervisor.timer"
)

TODAY="tbot_supervisor@$(date -u +%F).service"

PROCESS_PATTERNS=(
  "tbot_bot.runtime.main"
  "tbot_supervisor.py"
  "portal_web_main.py"
)

echo "Select one or more services to restart (separate numbers with spaces):"
for i in "${!SERVICES[@]}"; do
  printf " %d) %s\n" $((i+1)) "${SERVICES[$i]}"
done
echo "  r) Restart ALL listed services"
echo "  k) KILL ALL bot-related processes (hard stop)"
echo "  s) Start today's supervisor instance (${TODAY})"
echo "  e) Enable + start supervisor timer (daily)"
echo "  d) Disable supervisor timer"
echo "  x) Stop today's supervisor instance (${TODAY})"

read -rp "Enter selection(s): " -a CHOICES

case "${CHOICES[0]}" in
  r)
    echo "Restarting ALL services…"
    for S in "${SERVICES[@]}"; do
      echo "Restarting $S …"
      userctl restart "$S" || echo "Failed to restart $S"
    done
    exit 0
    ;;
  k)
    echo "Stopping ALL listed services…"
    for S in "${SERVICES[@]}"; do
      echo "Stopping $S …"
      userctl stop "$S" || true
    done
    echo "Stopping today's supervisor instance (${TODAY}) …"
    userctl stop "$TODAY" || true
    echo "Force killing any orphaned bot-related processes…"
    for P in "${PROCESS_PATTERNS[@]}"; do pkill -f "$P" || true; done
    echo "All relevant processes killed."
    exit 0
    ;;
  s)
    echo "Starting ${TODAY} …"
    userctl start "$TODAY"
    exit 0
    ;;
  e)
    echo "Enabling + starting tbot_supervisor.timer …"
    userctl enable --now tbot_supervisor.timer
    exit 0
    ;;
  d)
    echo "Disabling tbot_supervisor.timer …"
    userctl disable --now tbot_supervisor.timer || true
    exit 0
    ;;
  x)
    echo "Stopping ${TODAY} …"
    userctl stop "$TODAY" || true
    exit 0
    ;;
esac

# Numeric selections => restart those
for sel in "${CHOICES[@]}"; do
  idx=$((sel-1))
  S="${SERVICES[$idx]:-}"
  if [[ -z "$S" ]]; then
    echo "[Invalid selection: $sel]" && exit 1
  fi
  echo "Restarting $S …"
  userctl restart "$S" || echo "Failed to restart $S"
done

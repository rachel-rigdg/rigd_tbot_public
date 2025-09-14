#!/bin/bash
# restart_systemd.sh
# Interactive user-mode systemd service restarter and process killer for RIGD TradeBot.
# Updated for daily one-shot supervisor (tbot_supervisor@.service + tbot_supervisor.timer).

SERVICES=(
  "tbot_bot.service"           # Web UI only
  "tbot_supervisor.timer"      # Daily UTC scheduler (00:01)
)

PROCESS_PATTERNS=(
  "tbot_bot.runtime.main"
  "tbot_bot.runtime.tbot_supervisor"
  "strategy_router.py"
  "portal_web_configuration.py"
  "portal_web_main.py"
)

TODAY_UTC="$(date -u +%F)"
SUPERVISOR_INSTANCE="tbot_supervisor@${TODAY_UTC}.service"

echo "Select one or more services to restart (separate numbers with spaces):"
for i in "${!SERVICES[@]}"; do
  printf "%2d) %s\n" $((i+1)) "${SERVICES[$i]}"
done
echo "  r) Restart ALL listed services"
echo "  k) KILL ALL bot-related processes (hard stop)"
echo "  s) Start today's supervisor instance (${SUPERVISOR_INSTANCE})"
echo "  e) Enable + start supervisor timer (daily)"
echo "  d) Disable supervisor timer"
echo "  x) Stop today's supervisor instance (${SUPERVISOR_INSTANCE})"

read -p "Enter selection(s): " -a choices

case "${choices[0]}" in
  r)
    echo "Restarting ALL listed services..."
    for SERVICE in "${SERVICES[@]}"; do
      echo "Restarting $SERVICE ..."
      systemctl --user restart "$SERVICE"
      STATUS=$?
      if [ $STATUS -eq 0 ]; then
        echo "Service $SERVICE restarted successfully."
      else
        echo "Failed to restart $SERVICE. (Exit code: $STATUS)"
      fi
    done
    exit 0
    ;;
  k)
    echo "Stopping ALL listed services..."
    for SERVICE in "${SERVICES[@]}"; do
      echo "Stopping $SERVICE ..."
      systemctl --user stop "$SERVICE"
    done
    echo "Stopping today's supervisor instance ($SUPERVISOR_INSTANCE) ..."
    systemctl --user stop "$SUPERVISOR_INSTANCE" || true
    echo "Force killing any orphaned bot-related processes..."
    for PATTERN in "${PROCESS_PATTERNS[@]}"; do
      pkill -f "$PATTERN" 2>/dev/null || true
    done
    echo "All relevant processes killed."
    exit 0
    ;;
  s)
    echo "Starting today's supervisor instance: $SUPERVISOR_INSTANCE"
    systemctl --user start "$SUPERVISOR_INSTANCE"
    systemctl --user status --no-pager "$SUPERVISOR_INSTANCE" || true
    exit 0
    ;;
  x)
    echo "Stopping today's supervisor instance: $SUPERVISOR_INSTANCE"
    systemctl --user stop "$SUPERVISOR_INSTANCE"
    systemctl --user status --no-pager "$SUPERVISOR_INSTANCE" || true
    exit 0
    ;;
  e)
    echo "Enabling + starting tbot_supervisor.timer ..."
    systemctl --user enable --now tbot_supervisor.timer
    systemctl --user status --no-pager tbot_supervisor.timer || true
    exit 0
    ;;
  d)
    echo "Disabling tbot_supervisor.timer ..."
    systemctl --user disable --now tbot_supervisor.timer
    systemctl --user status --no-pager tbot_supervisor.timer || true
    exit 0
    ;;
esac

echo "You have selected:"
for i in "${choices[@]}"; do
  idx=$((i-1))
  if [[ $idx -ge 0 && $idx -lt ${#SERVICES[@]} ]]; then
    echo "  - ${SERVICES[$idx]}"
  else
    echo "  [Invalid selection: $i]"
    exit 1
  fi
done

read -p "Proceed with restart? (y/n): " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
  for i in "${choices[@]}"; do
    idx=$((i-1))
    SERVICE="${SERVICES[$idx]}"
    echo "Restarting $SERVICE ..."
    systemctl --user restart "$SERVICE"
    STATUS=$?
    if [ $STATUS -eq 0 ]; then
      echo "Service $SERVICE restarted successfully."
    else
      echo "Failed to restart $SERVICE. (Exit code: $STATUS)"
    fi
  done
else
  echo "No services restarted."
fi

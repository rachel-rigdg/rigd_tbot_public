#!/bin/bash
# restart_systemd.sh
# Interactive user-mode systemd service restarter and process killer (unified core only).

SERVICES=(
  "tbot_bot.service"
)

PROCESS_PATTERNS=(
  "tbot_bot.runtime.main"
  "tbot_runner_supervisor.py"
  "portal_web_configuration.py"
  "portal_web_main.py"
)

echo "Select one or more services to restart (separate numbers with spaces):"
for i in "${!SERVICES[@]}"; do
  printf "%2d) %s\n" $((i+1)) "${SERVICES[$i]}"
done
echo "  r) Restart ALL services"
echo "  k) KILL ALL services"

read -p "Enter number(s) or 'r' or 'k': " -a choices

if [[ "${choices[0]}" == "r" ]]; then
  echo "Restarting ALL services..."
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
elif [[ "${choices[0]}" == "k" ]]; then
  echo "Stopping/KILLING ALL services..."
  for SERVICE in "${SERVICES[@]}"; do
    echo "Stopping $SERVICE ..."
    systemctl --user stop "$SERVICE"
    STATUS=$?
    if [ $STATUS -eq 0 ]; then
      echo "Service $SERVICE stopped successfully."
    else
      echo "Failed to stop $SERVICE. (Exit code: $STATUS)"
    fi
  done
  echo "Force killing any orphaned bot-related processes..."
  for PATTERN in "${PROCESS_PATTERNS[@]}"; do
    pkill -f "$PATTERN"
  done
  echo "All relevant processes killed."
  exit 0
fi

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

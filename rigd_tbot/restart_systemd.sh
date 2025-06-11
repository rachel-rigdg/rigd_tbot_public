#!/bin/bash
# restart_systemd.sh
# Interactive multi-select systemd service restarter with confirmation.
# Recommend: configure passwordless sudo for systemctl commands (edit /etc/sudoers).

SERVICES=(
  "tbot_bot.path"
  "tbot_bot.service"
  "tbot_provisioning.service"
  "tbot_web.service"
  "tbot.target"
)

echo "Select one or more services to restart (separate numbers with spaces):"
for i in "${!SERVICES[@]}"; do
  printf "%2d) %s\n" $((i+1)) "${SERVICES[$i]}"
done

read -p "Enter number(s): " -a choices

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
    sudo systemctl restart "$SERVICE"
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

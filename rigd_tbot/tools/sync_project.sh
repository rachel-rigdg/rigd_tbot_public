#!/bin/bash
# tools/sync_project.sh – Smart two-way sync tool for TradeBot deployments

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/.. && pwd )"
DEV_PATH="$SCRIPT_DIR"

# === CONFIG ===
LIVE_PATH="/Users/rachelwyndunn/Documents/TradeBot/Tradebot-001-Live/rigd_tbot"
REMOTE_USER="tbot"
REMOTE_HOST="45.55.150.216"
REMOTE_PATH="/home/tbot/rigd_tbot/"
IBKR_INSTALLER_PATH="IBKR/ibgateway-stable-standalone-linux-x64.sh"
REMOTE_IBKR_PATH="/home/tbot/IBKR/"
SSH_KEY="$HOME/.ssh/id_ed25519"
SYSTEMD_PATH="systemd_units"
RSYNC_OPTS="--timeout=10 --no-motd"
# ==============

echo ""
echo "======================================================"
echo "   🛰  TradeBot Sync Tool (Interactive)"
echo "======================================================"
echo ""

echo "Choose SYNC DIRECTION:"
echo "1) Dev → Local Live"
echo "2) Local Live → Remote Server"
echo "3) Remote Server → Local Live (recovery)"
echo "4) Local Live → Dev (recovery)"
echo "5) Dev → Remote Server"
echo ""
read -rp "Enter direction [1–5]: " direction

echo ""
echo "Choose SYNC PROFILE:"
echo "1) CODE     – Code only (no secrets, logs, or books)"
echo "2) ARCHIVE  – Logs/reports only (no secrets or books)"
echo "3) ENC      – Encrypted deploy only (.env_bot.enc)"
echo "4) DEV      – Everything except setup scripts and .flux"
echo ""
read -rp "Enter profile [1–4]: " profile

case "$profile" in
  1) IGNORE_FILE="$SCRIPT_DIR/.scpignore_code" ;;
  2) IGNORE_FILE="$SCRIPT_DIR/.scpignore_prod_archive" ;;
  3) IGNORE_FILE="$SCRIPT_DIR/.scpignore_enc" ;;
  4) IGNORE_FILE="$SCRIPT_DIR/.scpignore_dev" ;;
  *) echo "❌ Invalid profile."; exit 1 ;;
esac

if [ ! -f "$IGNORE_FILE" ]; then
  echo "❌ Required ignore file '$IGNORE_FILE' not found at $IGNORE_FILE."
  exit 1
fi

echo ""
echo "==================== SYNC SUMMARY ===================="
case "$direction" in
  1) echo "🔁 Direction : Dev → Local Live"; FROM="$DEV_PATH/"; TO="$LIVE_PATH" ;;
  2) echo "🔁 Direction : Local Live → Remote Server"; FROM="$LIVE_PATH/"; TO="$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH" ;;
  3) echo "🔁 Direction : Remote Server → Local Live (recovery)"; FROM="$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH"; TO="$LIVE_PATH/" ;;
  4) echo "🔁 Direction : Local Live → Dev (recovery)"; FROM="$LIVE_PATH/"; TO="$DEV_PATH/" ;;
  5) echo "🔁 Direction : Dev → Remote Server"; FROM="$DEV_PATH/"; TO="$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH" ;;
  *) echo "❌ Invalid direction."; exit 1 ;;
esac
echo "Profile     : $IGNORE_FILE"
echo "SSH Key     : $SSH_KEY"
if [[ "$direction" == "2" || "$direction" == "5" ]]; then
  echo "IBKR Gateway Installer will also be synced to $REMOTE_IBKR_PATH"
fi
echo "======================================================"
echo ""

echo "🔎 Performing DRY RUN (Preview Only)..."
echo ""
case "$direction" in
  1)
    rsync -avn $RSYNC_OPTS --exclude-from="$IGNORE_FILE" "$DEV_PATH/" "$LIVE_PATH"
    sleep 1
    rsync -avn $RSYNC_OPTS "$DEV_PATH/$SYSTEMD_PATH/" "$LIVE_PATH/$SYSTEMD_PATH/"
    ;;
  2)
    rsync -avn $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$LIVE_PATH/" "$TO"
    sleep 1
    rsync -avn $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LIVE_PATH/$SYSTEMD_PATH/" "$TO$SYSTEMD_PATH/"
    echo ""
    echo "🔎 [IBKR] DRY RUN: Syncing IB Gateway installer to $REMOTE_IBKR_PATH ..."
    rsync -avn $RSYNC_OPTS -e "ssh -i $SSH_KEY" "../../$IBKR_INSTALLER_PATH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_IBKR_PATH"
    ;;
  3)
    rsync -avn $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$FROM" "$LIVE_PATH/"
    sleep 1
    rsync -avn $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$FROM$SYSTEMD_PATH/" "$LIVE_PATH/$SYSTEMD_PATH/"
    ;;
  4)
    rsync -avn $RSYNC_OPTS --exclude-from="$IGNORE_FILE" "$LIVE_PATH/" "$DEV_PATH/"
    sleep 1
    rsync -avn $RSYNC_OPTS "$LIVE_PATH/$SYSTEMD_PATH/" "$DEV_PATH/$SYSTEMD_PATH/"
    ;;
  5)
    rsync -avn $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$DEV_PATH/" "$TO"
    sleep 1
    rsync -avn $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$DEV_PATH/$SYSTEMD_PATH/" "$TO$SYSTEMD_PATH/"
    echo ""
    echo "🔎 [IBKR] DRY RUN: Syncing IB Gateway installer to $REMOTE_IBKR_PATH ..."
    rsync -avn $RSYNC_OPTS -e "ssh -i $SSH_KEY" "../../$IBKR_INSTALLER_PATH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_IBKR_PATH"
    ;;
esac

echo ""
read -rp "Proceed with REAL sync based on the above preview? [y/N]: " confirm1
if [[ "$confirm1" != "y" && "$confirm1" != "Y" ]]; then
  echo "❌ Sync cancelled."
  exit 0
fi

echo ""
read -rp "⚠️  FINAL CONFIRMATION: Are you ABSOLUTELY SURE? Type 'yes' to continue: " confirm2
if [[ "$confirm2" != "yes" ]]; then
  echo "❌ Sync cancelled."
  exit 0
fi

echo ""
echo "🚀 Running real sync now..."
echo ""

case "$direction" in
  1)
    rsync -avz --progress $RSYNC_OPTS --exclude-from="$IGNORE_FILE" "$DEV_PATH/" "$LIVE_PATH"
    rsync -avz --progress $RSYNC_OPTS "$DEV_PATH/$SYSTEMD_PATH/" "$LIVE_PATH/$SYSTEMD_PATH/"
    ;;
  2)
    rsync -avz --progress $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$LIVE_PATH/" "$TO"
    rsync -avz --progress $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LIVE_PATH/$SYSTEMD_PATH/" "$TO$SYSTEMD_PATH/"
    echo ""
    echo "🚀 [IBKR] Syncing IB Gateway installer to $REMOTE_IBKR_PATH ..."
    rsync -avz --progress $RSYNC_OPTS -e "ssh -i $SSH_KEY" "../../$IBKR_INSTALLER_PATH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_IBKR_PATH"
    ;;
  3)
    rsync -avz --progress $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$FROM" "$LIVE_PATH/"
    rsync -avz --progress $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$FROM$SYSTEMD_PATH/" "$LIVE_PATH/$SYSTEMD_PATH/"
    ;;
  4)
    rsync -avz --progress $RSYNC_OPTS --exclude-from="$IGNORE_FILE" "$LIVE_PATH/" "$DEV_PATH/"
    rsync -avz --progress $RSYNC_OPTS "$LIVE_PATH/$SYSTEMD_PATH/" "$DEV_PATH/$SYSTEMD_PATH/"
    ;;
  5)
    rsync -avz --progress $RSYNC_OPTS --exclude-from="$IGNORE_FILE" -e "ssh -i $SSH_KEY" "$DEV_PATH/" "$TO"
    rsync -avz --progress $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$DEV_PATH/$SYSTEMD_PATH/" "$TO$SYSTEMD_PATH/"
    echo ""
    echo "🚀 [IBKR] Syncing IB Gateway installer to $REMOTE_IBKR_PATH ..."
    rsync -avz --progress $RSYNC_OPTS -e "ssh -i $SSH_KEY" "../../$IBKR_INSTALLER_PATH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_IBKR_PATH"
    ;;
esac

if [[ "$direction" == "2" || "$direction" == "5" ]]; then
  echo ""
  read -rp "Do you want to SSH into the remote server and reload/enable/restart systemd units now? [y/N]: " do_systemd
  if [[ "$do_systemd" == "y" || "$do_systemd" == "Y" ]]; then
    ssh -i "$SSH_KEY" "$REMOTE_USER@$REMOTE_HOST" "sudo systemctl daemon-reload && \
      sudo systemctl enable tbot_web.service tbot_provisioning.service && \
      sudo systemctl restart tbot_web.service tbot_provisioning.service && \
      echo 'Systemd units reloaded, enabled, and restarted.'"
  else
    echo "⚠️  Skipped remote systemd reload/enable/restart."
  fi
fi

echo ""
echo "✅ Sync complete."

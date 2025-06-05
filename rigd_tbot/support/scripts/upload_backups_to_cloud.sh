#!/bin/bash

# scripts/upload_backups_to_cloud.sh
# ----------------------------------
# Optional script to upload backup files (ledgers, logs, summaries) to a remote cloud storage.
# Compatible with S3, Dropbox, or remote FTP/SFTP via rclone or native CLI tools.
# Requires setup of cloud credentials and access profiles.

# CONFIGURATION SECTION
# ---------------------
# Update these values to match your target cloud provider and directory path

BACKUP_DIR="backups"
TARGET_REMOTE="s3:rigd-tradebot/backups"      # Example for AWS S3 (requires rclone config)
LOG_FILE="logs/upload_backups.log"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# Optional: enable dry run
DRY_RUN=false   # Set to true for testing without real uploads

# Create log directory if missing
mkdir -p "$(dirname "$LOG_FILE")"

# Write session start to log
echo "[$TIMESTAMP] Starting cloud backup sync..." >> "$LOG_FILE"

# Upload all backup files (*.gnucash, *.json, *.zip) using rclone
if [ "$DRY_RUN" = true ]; then
    echo "Dry run enabled. Showing planned uploads..." >> "$LOG_FILE"
    rclone copy "$BACKUP_DIR" "$TARGET_REMOTE" --dry-run --log-file="$LOG_FILE" --log-level INFO
else
    rclone copy "$BACKUP_DIR" "$TARGET_REMOTE" --log-file="$LOG_FILE" --log-level INFO
fi

# Capture exit code
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date +"%Y-%m-%d %H:%M:%S")] Backup upload completed successfully." >> "$LOG_FILE"
else
    echo "[$(date +"%Y-%m-%d %H:%M:%S")] ERROR during backup upload. Exit code: $EXIT_CODE" >> "$LOG_FILE"
fi

exit $EXIT_CODE

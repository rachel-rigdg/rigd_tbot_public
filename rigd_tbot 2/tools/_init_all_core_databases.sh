#!/bin/bash
# tools/init_all_core_databases.sh — must be run from rigd_tbot/tools/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT"

echo "Initializing all core databases..."

python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_ledger_status.py"
python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_password_reset_tokens.py"
python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_system_logs.py"
python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_system.py"
python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_system_users.py"
python3 "$PROJECT_ROOT/tbot_bot/core/scripts/init_user_activity_monitoring.py"

echo "✓ All core databases initialized."

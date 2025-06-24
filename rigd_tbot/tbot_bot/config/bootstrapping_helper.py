# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from pathlib import Path

BOT_STATE_FILE = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    """
    # If already bootstrapped, mark as registration and return
    if BOT_STATE_FILE.exists():
        state = BOT_STATE_FILE.read_text(encoding="utf-8").strip()
        if state and state not in ("initialize", "provisioning", "bootstrapping"):
            print(f"[bootstrapping_helper] Already bootstrapped (state: {state}) — skipping database bootstrap.")
            return

    # Explicitly set bot state to bootstrapping at the start
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("bootstrapping")

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    print("[bootstrapping_helper] Database bootstrap complete.")
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("registration")

def main():
    bootstrap_databases()

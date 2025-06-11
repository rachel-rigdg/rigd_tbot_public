# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from tbot_bot.runtime.status_bot import update_bot_state
from pathlib import Path

BOT_STATE_FILE = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    """
    # Explicitly set bot state to bootstrapping at the start
    update_bot_state("bootstrapping")
    # If already bootstrapped, mark as idle and return
    if BOT_STATE_FILE.exists():
        state = BOT_STATE_FILE.read_text(encoding="utf-8").strip()
        if state and state != "initialize":
            print(f"[bootstrapping_helper] Already bootstrapped (state: {state}) — skipping database bootstrap.")
            return

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    print("[bootstrapping_helper] Database bootstrap complete.")
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("idle")

def main():
    bootstrap_databases()

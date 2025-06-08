# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from tbot_bot.runtime.status_bot import update_bot_state
from pathlib import Path

BOOTSTRAP_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "BOOTSTRAP_FLAG"

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    """
    update_bot_state("bootstrapping")
    if BOOTSTRAP_FLAG.exists():
        print(f"[bootstrapping_helper] BOOTSTRAP_FLAG already exists at {BOOTSTRAP_FLAG} — skipping database bootstrap.")
        update_bot_state("idle")
        return

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    BOOTSTRAP_FLAG.touch()
    print(f"[bootstrapping_helper] Database bootstrap complete. BOOTSTRAP_FLAG set at {BOOTSTRAP_FLAG}")
    update_bot_state("idle")

def main():
    bootstrap_databases()

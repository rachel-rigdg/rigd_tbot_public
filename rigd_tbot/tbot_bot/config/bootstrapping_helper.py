# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from pathlib import Path

BOOTSTRAP_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / ".bootstrapped"

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    """
    if BOOTSTRAP_FLAG.exists():
        print(f"[bootstrapping_helper] BOOTSTRAP_FLAG already exists at {BOOTSTRAP_FLAG} — skipping database bootstrap.")
        return

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    BOOTSTRAP_FLAG.touch()
    print(f"[bootstrapping_helper] Database bootstrap complete. BOOTSTRAP_FLAG set at {BOOTSTRAP_FLAG}")

def main():
    bootstrap_databases()

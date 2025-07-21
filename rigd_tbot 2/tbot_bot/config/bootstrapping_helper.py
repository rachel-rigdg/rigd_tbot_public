# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from tbot_bot.config.provisioning_helper import load_runtime_config, rotate_all_keys_and_secrets
from pathlib import Path

BOT_STATE_FILE = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    After database bootstrap, automatically rotate all keys and re-encrypt secrets.
    """
    if BOT_STATE_FILE.exists():
        state = BOT_STATE_FILE.read_text(encoding="utf-8").strip()
        if state and state not in ("initialize", "provisioning", "bootstrapping"):
            print(f"[bootstrapping_helper] Already bootstrapped (state: {state}) — skipping database bootstrap.")
            return

    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("bootstrapping")

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    print("[bootstrapping_helper] Database bootstrap complete.")

    config = load_runtime_config()
    if config is not None:
        rotate_all_keys_and_secrets(config)
        print("[bootstrapping_helper] All Fernet keys rotated and all secrets re-encrypted.")

    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("registration")

def main():
    bootstrap_databases()

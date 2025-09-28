# tbot_bot/config/bootstrapping_helper.py

from tbot_bot.config.db_bootstrap import initialize_all
from tbot_bot.config.provisioning_helper import load_runtime_config, rotate_all_keys_and_secrets
from tbot_bot.support.bot_state_manager import get_state, set_state  # <-- added

def bootstrap_databases() -> None:
    """
    Initialize all core system databases by invoking initialize_all().
    Skips if already bootstrapped.
    After database bootstrap, automatically rotate all keys and re-encrypt secrets.
    """
    try:
        state = get_state()
    except Exception:
        state = None

    # If we're already past early provisioning states, skip re-bootstrap
    if state and state not in ("initialize", "provisioning", "bootstrapping"):
        print(f"[bootstrapping_helper] Already bootstrapped (state: {state}) — skipping database bootstrap.")
        return

    # Enter an active provisioning state (no direct file I/O)
    set_state("analyzing", reason="bootstrap:db_init")

    print("[bootstrapping_helper] Starting core database initialization...")
    initialize_all()
    print("[bootstrapping_helper] Database bootstrap complete.")

    config = load_runtime_config()
    if config is not None:
        rotate_all_keys_and_secrets(config)
        print("[bootstrapping_helper] All Fernet keys rotated and all secrets re-encrypted.")

    # On successful completion, move to running (registration/login will proceed via the web)
    set_state("running", reason="bootstrap:complete")

def main():
    bootstrap_databases()

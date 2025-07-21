# tbot_bot/support/rotate_keys.py
# CLI tool: performs atomic Fernet key/secret rotation using canonical config, post-bootstrap only, per RIGD spec

from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

def main():
    if is_first_bootstrap():
        print("[rotate_keys] Key/secret rotation is not allowed during first bootstrap.")
        return
    config = get_live_config_for_rotation()
    if not config:
        print("[rotate_keys] No config found. Aborting rotation.")
        return
    try:
        rotate_all_keys_and_secrets(config)
        print("[rotate_keys] All keys and secrets rotated successfully.")
    except Exception as e:
        print(f"[rotate_keys] Error during rotation: {e}")

if __name__ == "__main__":
    main()

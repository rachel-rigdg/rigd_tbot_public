# tbot_bot/config/settings_bot.py
# Programmatic editor for .env_bot values

"""
settings_bot.py – Handles reading and writing settings in the .env_bot configuration file.
Used by the bot and web interface (settings_web.py) to programmatically update config variables.
"""

import os
from typing import Dict
from tbot_bot.config.env_bot import get_env_bot_path, validate_bot_config
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.utils_log import log_event

BOT_IDENTITY_KEY = "BOT_IDENTITY_STRING"

def read_settings() -> Dict[str, str]:
    """Reads the .env_bot configuration file into a dictionary of key-value pairs (excluding identity)."""
    settings = {}
    path = get_env_bot_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing .env_bot at expected location: {path}")

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key != BOT_IDENTITY_KEY:
                    settings[key] = value
    return settings

def write_settings(updated_settings: Dict[str, str]) -> None:
    """
    Writes updated settings back to .env_bot, preserving comments and formatting.
    Ensures BOT_IDENTITY_STRING is injected from secrets.
    Only modifies keys provided in `updated_settings`.
    """
    path = get_env_bot_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing .env_bot at expected location: {path}")

    with open(path, "r") as f:
        lines = f.readlines()

    new_lines = []
    applied_keys = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, _ = stripped.split("=", 1)
            key = key.strip()
            if key in updated_settings:
                new_lines.append(f"{key}={updated_settings[key]}\n")
                applied_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Append any new keys not in original file
    for key, value in updated_settings.items():
        if key not in applied_keys:
            new_lines.append(f"{key}={value}\n")

    # Inject BOT_IDENTITY_STRING before validation
    identity = load_bot_identity()
    found_identity = False
    for idx, l in enumerate(new_lines):
        if l.strip().startswith(f"{BOT_IDENTITY_KEY}="):
            new_lines[idx] = f"{BOT_IDENTITY_KEY}={identity}\n"
            found_identity = True
            break
    if not found_identity:
        new_lines.insert(0, f"{BOT_IDENTITY_KEY}={identity}\n")

    # Validate before writing
    temp_config = {}
    for l in new_lines:
        if l.strip() and not l.strip().startswith("#") and "=" in l:
            k, v = l.split("=", 1)
            temp_config[k.strip()] = v.strip()
    validate_bot_config(temp_config)

    with open(path, "w") as f:
        f.writelines(new_lines)

    log_event("settings_bot", f".env_bot updated successfully with {len(updated_settings)} keys.")

# -----------------------------------------
# Web interface compatibility aliases
# -----------------------------------------

def read_env_bot() -> Dict[str, str]:
    return read_settings()

def write_env_bot(updated_settings: Dict[str, str]) -> None:
    write_settings(updated_settings)

if __name__ == "__main__":
    print(read_settings())

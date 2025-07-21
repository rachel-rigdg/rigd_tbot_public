# tools/encrypt_json.py
# Encrypts all JSON files in tbot_bot/storage/secrets/ using corresponding Fernet keys in storage/keys/

import os
from pathlib import Path
from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_DIR = BASE_DIR / "tbot_bot" / "storage" / "secrets"
KEYS_DIR = BASE_DIR / "tbot_bot" / "storage" / "keys"

def encrypt_file(json_file: Path, key_file: Path):
    try:
        key = key_file.read_text(encoding="utf-8").strip().encode()
        fernet = Fernet(key)
    except Exception as e:
        print(f"[encrypt_json] Failed to read key {key_file}: {e}")
        return

    try:
        data = json_file.read_bytes()
        encrypted = fernet.encrypt(data)
    except Exception as e:
        print(f"[encrypt_json] Failed to read/encrypt file {json_file}: {e}")
        return

    output_file = json_file.with_suffix(json_file.suffix + ".enc")
    try:
        with open(output_file, "wb") as f:
            f.write(encrypted)
        print(f"[encrypt_json] Encrypted {json_file.name} → {output_file.name}")
    except Exception as e:
        print(f"[encrypt_json] Failed to write encrypted file {output_file}: {e}")

def main():
    # Map secrets filename to corresponding key filename
    key_map = {
        "acct_api_credentials.json": "acct_api.key",
        "alert_channels.json": "login.key",
        "bot_identity.json": "login.key",
        "broker_credentials.json": "broker.key",
        "network_config.json": "env.key",
        "smtp_credentials.json": "smtp.key",
        "screener_api.json": "screener_api.key"
    }

    for secret_filename, key_filename in key_map.items():
        secret_file = SECRETS_DIR / secret_filename
        key_file = KEYS_DIR / key_filename

        if not secret_file.exists():
            print(f"[encrypt_json] Skipping {secret_filename}: file not found")
            continue
        if not key_file.exists():
            print(f"[encrypt_json] Skipping {secret_filename}: key {key_filename} not found")
            continue

        encrypt_file(secret_file, key_file)

if __name__ == "__main__":
    main()

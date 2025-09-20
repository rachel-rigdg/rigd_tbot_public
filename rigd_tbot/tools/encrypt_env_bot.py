#!/usr/bin/env python3

# tools/encrypt_env_bot.py
# Encrypts .env_bot into tbot_bot/support/.env_bot.enc using Fernet key stored in tbot_bot/storage/keys/env_bot.key

import json
import os
import sys
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path
from datetime import datetime

# === Argument Parsing ===
NO_PROMPT = "--no-prompt" in sys.argv

# === Paths (corrected to rigd_tbot structure) ===
BASE_DIR = Path(__file__).resolve().parents[1]
PLAIN_ENV_BOT_PATH = BASE_DIR / ".env_bot"
ENC_OUTPUT_PATH = BASE_DIR / "tbot_bot" / "storage" / "secrets" / ".env_bot.enc"
BACKUP_DIR = BASE_DIR / "tbot_bot" / "storage" / "backups"
KEY_PATH = BASE_DIR / "tbot_bot" / "storage" / "keys" / "env_bot.key"  # ✅ Correct filename

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

# === Step 1: Load and validate plaintext .env_bot at root ===
if not PLAIN_ENV_BOT_PATH.exists():
    print(f"[encrypt_env_bot] .env_bot not found at: {PLAIN_ENV_BOT_PATH}")
    sys.exit(1)

# === Step 2: Backup .env_bot ===
timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
bot_backup = BACKUP_DIR / f".env_bot.before_encrypt_{timestamp}.bak"
with bot_backup.open("w", encoding="utf-8") as f:
    f.write(PLAIN_ENV_BOT_PATH.read_text())
print(f"[encrypt_env_bot] Backup of .env_bot saved to: {bot_backup}")

# === Step 3: Parse key-values from plaintext .env_bot ===
config_dict = {}
with PLAIN_ENV_BOT_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            config_dict[k.strip()] = v.strip()

# === Step 4: Generate new Fernet key ===
new_key = Fernet.generate_key().decode()
print(f"\n[encrypt_env_bot] Generated new ENV_BOT_KEY:\n{new_key}\n")

# === Step 5: Confirm before writing ===
if not NO_PROMPT:
    confirm = input("Write key to env_bot.key and continue? [y/N]: ").strip().lower()
    if confirm != "y":
        print("[encrypt_env_bot] Aborted before writing key or encrypting.")
        sys.exit(1)

# === Step 6: Write key to tbot_bot/storage/keys/env_bot.key ===
with KEY_PATH.open("w", encoding="utf-8") as f:
    f.write(new_key + "\n")
print(f"[encrypt_env_bot] Key written to: {KEY_PATH}")

# === Step 7: Encrypt and write .env_bot.enc ===
fernet = Fernet(new_key.encode())
data = json.dumps(config_dict).encode("utf-8")
ENC_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with ENC_OUTPUT_PATH.open("wb") as f:
    f.write(fernet.encrypt(data))
print(f"[encrypt_env_bot] .env_bot encrypted → {ENC_OUTPUT_PATH}")

# === Step 8: Verify round-trip decryption ===
print("[encrypt_env_bot] Verifying encrypted output...")
try:
    with ENC_OUTPUT_PATH.open("rb") as f:
        decrypted = fernet.decrypt(f.read()).decode()
    restored = json.loads(decrypted)
except InvalidToken:
    print("[encrypt_env_bot] Decryption failed — key mismatch or corruption.")
    sys.exit(1)
except Exception as e:
    print(f"[encrypt_env_bot] Unexpected error: {e}")
    sys.exit(1)

print("[encrypt_env_bot] Decryption verified. Sample config:")
for i, (k, v) in enumerate(restored.items()):
    print(f"   {k} = {v}")
    if i == 4 and len(restored) > 5:
        print("   ...")
        break

print("\n[encrypt_env_bot] Encryption process complete. Output verified and secure.")

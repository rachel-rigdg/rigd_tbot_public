#!/usr/bin/env python3

# tools/encrypt_env.py
# Encrypts .env into .env.enc as JSON and writes ENV_KEY to tbot_bot/storage/keys/env.key

import sys
import json
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path
from datetime import datetime

# === Argument Parsing ===
NO_PROMPT = "--no-prompt" in sys.argv

# === Paths (rigd_tbot root structure) ===
BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
ENC_OUTPUT_PATH = BASE_DIR / ".env.enc"
BACKUP_DIR = BASE_DIR / "tbot_bot" / "storage" / "backups"
KEY_OUTPUT_PATH = BASE_DIR / "tbot_bot" / "storage" / "keys" / "env.key"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
KEY_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# === Step 1: Load .env as key-value pairs (ignoring comments, blanks) ===
if not ENV_PATH.exists():
    print("[encrypt_env] .env not found. Aborting.")
    sys.exit(1)

config_dict = {}
with ENV_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            config_dict[k.strip()] = v.strip()

# === Step 2: Generate new encryption key ===
new_key = Fernet.generate_key().decode()
print(f"\n[encrypt_env] Generated new ENV_KEY:\n{new_key}\n")

# === Step 3: Confirm before proceeding ===
if not NO_PROMPT:
    confirm_env = input("Write key and encrypt .env? [y/N]: ").strip().lower()
    if confirm_env != "y":
        print("[encrypt_env] Aborted before encryption.")
        sys.exit(1)

# === Step 4: Backup .env ===
timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
env_backup = BACKUP_DIR / f".env.before_encrypt_{timestamp}.bak"
with env_backup.open("w", encoding="utf-8") as f:
    f.writelines(line + "\n" for line in config_dict.keys())
print(f"[encrypt_env] Backup of .env saved to: {env_backup}")

# === Step 5: Write ENV_KEY to secure file only (no .env injection) ===
with KEY_OUTPUT_PATH.open("w", encoding="utf-8") as f:
    f.write(new_key + "\n")
print(f"[encrypt_env] Key written to: {KEY_OUTPUT_PATH}")

# === Step 6: Encrypt and write .env.enc as JSON ===
fernet = Fernet(new_key.encode())
data = json.dumps(config_dict, indent=2).encode("utf-8")
with ENC_OUTPUT_PATH.open("wb") as f:
    f.write(fernet.encrypt(data))
print(f"[encrypt_env] .env encrypted as JSON → {ENC_OUTPUT_PATH}")

# === Step 7: Verify ===
print("[encrypt_env] Verifying encrypted output...")
try:
    with ENC_OUTPUT_PATH.open("rb") as f:
        decrypted = fernet.decrypt(f.read()).decode()
    restored = json.loads(decrypted)
except InvalidToken:
    print("[encrypt_env] Decryption failed. Invalid ENV_KEY.")
    sys.exit(1)
except Exception as e:
    print(f"[encrypt_env] Unexpected error: {e}")
    sys.exit(1)

print("[encrypt_env] Decryption successful. Sample restored variables:")
for i, (k, v) in enumerate(restored.items()):
    print(f"   {k} = {v}")
    if i == 4 and len(restored) > 5:
        print("   ...")
        break

print("\n[encrypt_env] Encryption complete. Output verified and secure.")

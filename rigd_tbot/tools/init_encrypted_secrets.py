# tools/init_encrypted_secrets.py
# One-time tool to generate encrypted secrets from plaintext template for bot/bootstrap use

import os
import json
from cryptography.fernet import Fernet
from pathlib import Path
from datetime import datetime
from dotenv import dotenv_values

# === Paths ===
TOOLS_DIR = Path(__file__).resolve().parent
BASE_DIR = TOOLS_DIR.parent
KEYS_DIR = BASE_DIR / "tbot_bot" / "storage" / "keys"
SECRETS_DIR = BASE_DIR / "tbot_bot" / "storage" / "secrets"
INPUT_FILE = TOOLS_DIR / "secrets_template.txt"

KEYS_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_DIR.mkdir(parents=True, exist_ok=True)

# === Load plaintext secrets ===
if not INPUT_FILE.exists():
    print(f"[init_encrypted_secrets] Missing input file: {INPUT_FILE}")
    exit(1)

try:
    flat_data = dotenv_values(INPUT_FILE)
except Exception as e:
    print(f"[init_encrypted_secrets] Failed to parse input: {e}")
    exit(1)

# === Organize secrets by category ===
template = {
    "env": {
        "ENTITY_CODE": flat_data.get("ENTITY_CODE"),
        "JURISDICTION_CODE": flat_data.get("JURISDICTION_CODE"),
        "BROKER_CODE": flat_data.get("BROKER_CODE"),
        "BOT_ID": flat_data.get("BOT_ID"),
        "BOT_IDENTITY_STRING": f'{flat_data.get("ENTITY_CODE")}_{flat_data.get("JURISDICTION_CODE")}_{flat_data.get("BROKER_CODE")}_{flat_data.get("BOT_ID")}'
    },
    "broker": {
        k: v for k, v in flat_data.items() if k.startswith("ALPACA_") or k.startswith("IBKR_")
    },
    "screener_api": {
        "FINNHUB_API_KEY": flat_data.get("FINNHUB_API_KEY")
    },
    "smtp": {
        k: v for k, v in flat_data.items() if k.startswith("SMTP_") or k == "ALERT_EMAIL"
    },
    "acct_api": {},  # Optional: populated externally
    "network_config": {
        "LOCAL_IP": flat_data.get("LOCAL_IP"),
        "LOCAL_PORT": flat_data.get("LOCAL_PORT"),
        "REMOTE_IP": flat_data.get("REMOTE_IP"),
        "REMOTE_PORT": flat_data.get("REMOTE_PORT")
    }
}

# === Required key files per category ===
KEYS = {
    "env": KEYS_DIR / "env.key",
    "broker": KEYS_DIR / "broker.key",
    "screener_api": KEYS_DIR / "screener_api.key",
    "acct_api": KEYS_DIR / "acct_api.key",
    "smtp": KEYS_DIR / "smtp.key",
    "network_config": KEYS_DIR / "env.key"  # Reuses env.key
}

# === Encrypt and write each category ===
for category, key_path in KEYS.items():
    # Always generate fresh Fernet key if file missing or empty
    if not key_path.exists() or key_path.stat().st_size == 0:
        key = Fernet.generate_key()
        key_path.write_text(key.decode(), encoding="utf-8")
        print(f"[init_encrypted_secrets] Created key: {key_path}")
    else:
        key = key_path.read_text(encoding="utf-8").strip().encode()

    fernet = Fernet(key)
    payload = template.get(category)
    if not payload:
        print(f"[init_encrypted_secrets] Skipping {category} — no data found.")
        continue

    # Convert dict to JSON string encoded bytes for encryption
    payload_bytes = json.dumps(payload).encode("utf-8")
    encrypted = fernet.encrypt(payload_bytes)

    output_file = SECRETS_DIR / f"{category}.json.enc"
    with open(output_file, "wb") as f:
        f.write(encrypted)
    print(f"[init_encrypted_secrets] Wrote: {output_file}")

print("[init_encrypted_secrets] Complete.")

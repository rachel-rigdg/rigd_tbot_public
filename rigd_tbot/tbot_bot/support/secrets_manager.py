# tbot_bot/support/secrets_manager.py
# UPDATE: Supports new usage flags ("UNIVERSE_ENABLED_{idx}", "TRADING_ENABLED_{idx}") in get_provider_credentials and update_provider_credentials,
# ensures flags are always included in returned/saved dicts. No data loss for new keys. No business logic change to schema helpers.
# Audit log remains as before.

import os
from typing import Dict, Optional
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.encrypt_secrets import encrypt_json
from tbot_bot.support.path_resolver import get_secret_path
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet

SCREENER_CREDENTIALS_FILENAME = "screener_api"
SCREENER_CREDENTIALS_FILE_ENC = "screener_api.json.enc"
SCREENER_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "core", "schemas", "screener_credentials_schema.json"
)
AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output", "logs", "screener_credentials_audit.log"
)
KEY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "storage", "keys"
)

USAGE_FLAGS = ["UNIVERSE_ENABLED", "TRADING_ENABLED"]

def _ensure_keyfile_exists(name: str):
    key_path = Path(KEY_DIR) / f"{name}.key"
    if not key_path.is_file():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_path.write_text(key.decode("utf-8"))

def _audit_log(action: str, provider: str):
    ts = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    meta = {"provider": provider, "admin_user": "admin"}
    Path(AUDIT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {action} | {json.dumps(meta)}\n")

def get_screener_credentials_path() -> str:
    return get_secret_path(SCREENER_CREDENTIALS_FILE_ENC)

def _load_schema() -> Dict:
    try:
        with open(SCREENER_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        return schema
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials schema: {e}")

def _get_schema_keys() -> list:
    schema = _load_schema()
    keys = [k for k in schema.get("properties", {}).keys() if k != "PROVIDER"]
    # Add usage flags to schema keys if not present
    for flag in USAGE_FLAGS:
        if flag not in keys:
            keys.append(flag)
    return keys

def _create_empty_credentials_from_schema() -> Dict:
    return {}

def load_screener_credentials() -> Dict:
    path = get_screener_credentials_path()
    _ensure_keyfile_exists("screener_api")
    if not os.path.exists(path):
        empty_creds = _create_empty_credentials_from_schema()
        try:
            save_screener_credentials(empty_creds)
        except Exception as e:
            raise RuntimeError(f"[secrets_manager] Failed to create empty screener credentials file: {e}")
        return empty_creds
    try:
        return decrypt_json("screener_api")
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials: {e}")

def save_screener_credentials(credentials: Dict) -> None:
    try:
        _ensure_keyfile_exists("screener_api")
        encrypt_json("screener_api", credentials)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to save screener credentials: {e}")

def get_provider_credentials(provider: str) -> Optional[Dict]:
    creds = load_screener_credentials()
    key_upper = provider.strip().upper()
    provider_keys = [k for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
    for pkey in provider_keys:
        if creds[pkey].strip().upper() == key_upper:
            index = pkey.split("_")[-1]
            result = {}
            schema_keys = _get_schema_keys()
            for base_key in schema_keys:
                k_full = f"{base_key}_{index}"
                result[base_key] = creds.get(k_full, "")
            # Always return usage flags too
            for flag in USAGE_FLAGS:
                k_flag = f"{flag}_{index}"
                result[flag] = creds.get(k_flag, "false")
            return result
    return None

def update_provider_credentials(provider: str, new_values: Dict) -> None:
    try:
        creds = load_screener_credentials()
        schema_keys = _get_schema_keys()
        key_upper = provider.strip().upper()
        provider_keys = [k for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
        index = None
        for pkey in provider_keys:
            if creds[pkey].strip().upper() == key_upper:
                index = pkey.split("_")[-1]
                break
        existed = index is not None
        if index is None:
            existing_indices = sorted([int(k.split("_")[-1]) for k in provider_keys] or [0])
            index = f"{(existing_indices[-1]+1) if existing_indices else 1:02d}"
        keys_to_remove = [k for k in creds if k.endswith(f"_{index}")]
        for k in keys_to_remove:
            del creds[k]
        # Always store all schema keys and usage flags
        for base_key in schema_keys:
            creds[f"{base_key}_{index}"] = new_values.get(base_key, "")
        for flag in USAGE_FLAGS:
            creds[f"{flag}_{index}"] = new_values.get(flag, "false")
        creds[f"PROVIDER_{index}"] = key_upper
        save_screener_credentials(creds)
        _audit_log("CREDENTIAL_UPDATED" if existed else "CREDENTIAL_ADDED", provider)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to update credentials: {e}")

def delete_provider_credentials(provider: str) -> None:
    try:
        creds = load_screener_credentials()
        key_upper = provider.strip().upper()
        provider_keys = [k for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
        index = None
        for pkey in provider_keys:
            if creds[pkey].strip().upper() == key_upper:
                index = pkey.split("_")[-1]
                break
        if index:
            keys_to_remove = [k for k in creds if k.endswith(f"_{index}")]
            for k in keys_to_remove:
                del creds[k]
            del creds[f"PROVIDER_{index}"]
            save_screener_credentials(creds)
            _audit_log("CREDENTIAL_DELETED", provider)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to delete credentials: {e}")

def list_providers() -> list:
    creds = load_screener_credentials()
    provider_keys = [v for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
    return provider_keys

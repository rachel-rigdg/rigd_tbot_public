# tbot_bot/support/secrets_manager.py
# Central encryption/decryption/loader for all screener API credentials. (Called by all loaders/adapters.)
# 100% compliant with screener universe/credential spec using generic indexed keys and schema initialization.

import os
from typing import Dict, Optional
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.encrypt_secrets import encrypt_json
from tbot_bot.support.path_resolver import get_secret_path
import re
import json

SCREENER_CREDENTIALS_FILENAME = "screener_api.json.enc"
SCREENER_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),  # tbot_bot/support/
    "core", "schemas", "screener_credentials_schema.json"
)

def get_screener_credentials_path() -> str:
    return get_secret_path(SCREENER_CREDENTIALS_FILENAME)

def _load_schema() -> Dict:
    try:
        with open(SCREENER_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        return schema
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials schema: {e}")

def _create_empty_credentials_from_schema() -> Dict:
    schema = _load_schema()
    # Only create empty indexed block, not populate all fields for all indices
    return {}

def load_screener_credentials() -> Dict:
    """
    Loads decrypted screener/universe adapter credentials from dedicated encrypted secrets file.
    If missing, creates an empty dict file (no providers) based on schema.
    Returns dict with indexed provider blocks, e.g. PROVIDER_01, SCREENER_NAME_01, etc.
    """
    path = get_screener_credentials_path()
    if not os.path.exists(path):
        empty_creds = _create_empty_credentials_from_schema()
        try:
            save_screener_credentials(empty_creds)
        except Exception as e:
            raise RuntimeError(f"[secrets_manager] Failed to create empty screener credentials file: {e}")
        return empty_creds
    try:
        return decrypt_json(SCREENER_CREDENTIALS_FILENAME)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials: {e}")

def save_screener_credentials(credentials: Dict) -> None:
    """
    Saves (encrypts) the provided credentials dict to the dedicated secrets file atomically.
    """
    try:
        encrypt_json(SCREENER_CREDENTIALS_FILENAME, credentials)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to save screener credentials: {e}")

def get_provider_credentials(provider: str) -> Optional[Dict]:
    """
    Returns the dict of credentials for a given provider label by searching generic indexed keys.
    Example: provider = "FINNHUB" or "IBKR"
    """
    creds = load_screener_credentials()
    key_upper = provider.strip().upper()
    provider_keys = [k for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
    for pkey in provider_keys:
        if creds[pkey].strip().upper() == key_upper:
            index = pkey.split("_")[-1]
            result = {}
            for k, v in creds.items():
                if k.endswith(f"_{index}"):
                    result[k.rsplit("_", 1)[0]] = v
            return result
    return None

def update_provider_credentials(provider: str, new_values: Dict) -> None:
    """
    Updates credentials for the given provider (add/edit) by replacing the indexed block and saving.
    Only fields found in the schema properties are allowed.
    """
    try:
        creds = load_screener_credentials()
        schema = _load_schema()
        allowed = set(schema.get("properties", {}).keys())
        key_upper = provider.strip().upper()
        provider_keys = [k for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
        index = None
        for pkey in provider_keys:
            if creds[pkey].strip().upper() == key_upper:
                index = pkey.split("_")[-1]
                break
        if index is None:
            existing_indices = sorted(int(k.split("_")[-1]) for k in provider_keys)
            index = f"{(existing_indices[-1]+1) if existing_indices else 1:02d}"
        keys_to_remove = [k for k in creds if k.endswith(f"_{index}")]
        for k in keys_to_remove:
            del creds[k]
        for base_key, val in new_values.items():
            if base_key in allowed and base_key != "PROVIDER":
                creds[f"{base_key}_{index}"] = val
        creds[f"PROVIDER_{index}"] = key_upper
        save_screener_credentials(creds)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to update credentials: {e}")

def delete_provider_credentials(provider: str) -> None:
    """
    Deletes credentials for the given provider by removing all indexed keys with matching provider.
    """
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
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to delete credentials: {e}")

def list_providers() -> list:
    """
    Returns list of provider names from the indexed credentials file.
    """
    creds = load_screener_credentials()
    provider_keys = [v for k, v in creds.items() if re.match(r"PROVIDER_\d{2}", k)]
    return provider_keys

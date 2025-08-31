# tbot_bot/support/secrets_manager.py
# Fully compliant with modular, indexed, secure screener credential management.
# - Supports dynamic provider indexing (PROVIDER_1, PROVIDER_2, ...).
# - Usage flags (UNIVERSE_ENABLED, TRADING_ENABLED, ENRICHMENT_ENABLED) always present per provider.
# - Atomic encrypted file I/O.
# - UTC audit log for all add/update/delete.
# - Never stores or logs secrets in plaintext.

import os
from typing import Dict, Optional, List
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
    "tbot_bot", "output", "logs", "screener_credentials_audit.log"
)
KEY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tbot_bot", "storage", "keys"
)

USAGE_FLAGS = ["UNIVERSE_ENABLED", "TRADING_ENABLED", "ENRICHMENT_ENABLED"]

_PROVIDER_KEY_RE = re.compile(r"^PROVIDER_\d+$")

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
        if not os.path.exists(SCREENER_SCHEMA_PATH):
            return {}
        with open(SCREENER_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        return schema
    except Exception:
        # Soft fail if schema not present, return empty schema
        return {}

def _get_schema_keys() -> List[str]:
    schema = _load_schema()
    keys = [k for k in schema.get("properties", {}).keys() if k != "PROVIDER"]
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
        # NOTE: decrypt_json expects the base name (without extension)
        return decrypt_json("screener_api")
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials: {e}")

def save_screener_credentials(credentials: Dict) -> None:
    try:
        _ensure_keyfile_exists("screener_api")
        # NOTE: encrypt_json expects the base name (without extension)
        encrypt_json("screener_api", credentials)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to save screener credentials: {e}")

def _iter_provider_indices(creds: Dict) -> List[int]:
    indices: List[int] = []
    for k, v in creds.items():
        if _PROVIDER_KEY_RE.match(k):
            try:
                indices.append(int(k.split("_")[-1]))
            except ValueError:
                continue
    return sorted(indices)

def get_provider_credentials(provider: str) -> Optional[Dict]:
    creds = load_screener_credentials()
    key_upper = provider.strip().upper()
    # Find index for this provider
    index = None
    for k, v in creds.items():
        if _PROVIDER_KEY_RE.match(k) and str(v).strip().upper() == key_upper:
            index = k.split("_")[-1]
            break
    if index is None:
        return None

    result: Dict[str, str] = {}
    schema_keys = _get_schema_keys()
    for base_key in schema_keys:
        k_full = f"{base_key}_{index}"
        result[base_key] = creds.get(k_full, "")
    for flag in USAGE_FLAGS:
        k_flag = f"{flag}_{index}"
        result[flag] = creds.get(k_flag, "false")
    return result

def update_provider_credentials(provider: str, new_values: Dict) -> None:
    """
    Create or update credentials for a provider. Ensures:
    - A mapping key PROVIDER_<idx> exists and maps to the provider name.
    - All per-provider fields are written as KEY_<idx>.
    - Usage flags are normalized to strings ("true"/"false").
    """
    try:
        creds = load_screener_credentials()
        schema_keys = _get_schema_keys()
        key_upper = provider.strip().upper()

        # Locate existing index (any digit length), or allocate next integer index
        existing_index: Optional[str] = None
        for k, v in creds.items():
            if _PROVIDER_KEY_RE.match(k) and str(v).strip().upper() == key_upper:
                existing_index = k.split("_")[-1]
                break

        if existing_index is None:
            indices = _iter_provider_indices(creds)
            next_idx_int = (indices[-1] + 1) if indices else 1
            index = str(next_idx_int)  # no zero-padding for simplicity/compatibility
            existed = False
        else:
            index = existing_index
            existed = True

        # Remove any prior keys for this index to avoid stale fields
        keys_to_remove = [k for k in list(creds.keys()) if k.endswith(f"_{index}")]
        for k in keys_to_remove:
            del creds[k]

        # Write per-provider fields (base schema keys)
        for base_key in schema_keys:
            creds[f"{base_key}_{index}"] = new_values.get(base_key, "")

        # Normalize and persist usage flags
        for flag in USAGE_FLAGS:
            raw = new_values.get(flag, "false")
            val = "true" if str(raw).strip().lower() in ("1", "true", "yes", "y", "on") else "false"
            creds[f"{flag}_{index}"] = val

        # Mapping key: PROVIDER_<idx>
        creds[f"PROVIDER_{index}"] = key_upper

        # Persist encrypted
        save_screener_credentials(creds)

        _audit_log("CREDENTIAL_UPDATED" if existed else "CREDENTIAL_ADDED", provider)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to update credentials: {e}")

def delete_provider_credentials(provider: str) -> None:
    """
    Delete credentials for a provider (by name), remove all KEY_<idx> fields and
    the PROVIDER_<idx> mapping. Always appends CREDENTIAL_DELETED to the audit log
    when a mapping existed.
    """
    try:
        creds = load_screener_credentials()
        key_upper = provider.strip().upper()

        # Find index
        index = None
        for k, v in creds.items():
            if _PROVIDER_KEY_RE.match(k) and str(v).strip().upper() == key_upper:
                index = k.split("_")[-1]
                break

        if index is None:
            return  # nothing to delete; silent no-op

        # Remove per-index keys
        keys_to_remove = [k for k in list(creds.keys()) if k.endswith(f"_{index}")]
        for k in keys_to_remove:
            del creds[k]

        # Remove provider mapping
        del creds[f"PROVIDER_{index}"]

        # Persist encrypted
        save_screener_credentials(creds)

        # Audit
        _audit_log("CREDENTIAL_DELETED", provider)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to delete credentials: {e}")

def list_providers() -> List[str]:
    creds = load_screener_credentials()
    return [v for k, v in creds.items() if _PROVIDER_KEY_RE.match(k)]

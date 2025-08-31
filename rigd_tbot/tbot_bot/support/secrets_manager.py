# tbot_bot/support/secrets_manager.py
# Fully compliant with modular, indexed, secure screener credential management.
# - Supports dynamic provider indexing (PROVIDER_01, PROVIDER_02, ...).
# - Usage flags (UNIVERSE_ENABLED, TRADING_ENABLED, ENRICHMENT_ENABLED) always present per provider.
# - Atomic encrypted file I/O with resolved paths.
# - UTC audit log for all add/update/delete/rotate (append-only).
# - Never stores or logs secrets in plaintext.

import os
import re
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet

from tbot_bot.support.path_resolver import get_secret_path

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
SECRET_FIELDS = {"SCREENER_PASSWORD", "SCREENER_API_KEY", "SCREENER_TOKEN"}

_PROVIDER_KEY_RE = re.compile(r"^PROVIDER_\d+$")


# --------------------------
# Key & Audit Helpers
# --------------------------
def _ensure_keyfile_exists(name: str):
    key_path = Path(KEY_DIR) / f"{name}.key"
    if not key_path.is_file():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_path.write_bytes(key)

def _get_fernet(name: str) -> Fernet:
    _ensure_keyfile_exists(name)
    key_path = Path(KEY_DIR) / f"{name}.key"
    key = key_path.read_bytes()
    return Fernet(key)

def _audit_log(action: str, provider: str):
    ts = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    meta = {"provider": provider, "admin_user": "admin"}
    p = Path(AUDIT_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {action} | {json.dumps(meta)}\n")


# --------------------------
# Path & Schema Helpers
# --------------------------
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
        return {}

def _get_schema_keys() -> List[str]:
    schema = _load_schema()
    keys = [k for k in schema.get("properties", {}).keys() if k != "PROVIDER"]
    # Ensure usage flags always present
    for flag in USAGE_FLAGS:
        if flag not in keys:
            keys.append(flag)
    return keys


# --------------------------
# Encrypted File I/O (Atomic)
# --------------------------
def _atomic_encrypt_write(path: str, data: Dict, key_name: str):
    fernet = _get_fernet(key_name)
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = fernet.encrypt(serialized)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    with open(tmp_path, "wb") as f:
        f.write(token)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, target)

def _decrypt_read(path: str, key_name: str) -> Dict:
    target = Path(path)
    if not target.exists():
        return {}
    fernet = _get_fernet(key_name)
    with open(target, "rb") as f:
        token = f.read()
    decrypted = fernet.decrypt(token)
    return json.loads(decrypted.decode("utf-8"))


# --------------------------
# Credentials CRUD
# --------------------------
def _create_empty_credentials_from_schema() -> Dict:
    # Use flat generic model; no pre-seeding indices.
    return {}

def load_screener_credentials() -> Dict:
    try:
        path = get_screener_credentials_path()
        if not os.path.exists(path):
            empty = _create_empty_credentials_from_schema()
            save_screener_credentials(empty)  # create encrypted file atomically
            return empty
        return _decrypt_read(path, SCREENER_CREDENTIALS_FILENAME)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials: {e}")

def save_screener_credentials(credentials: Dict) -> None:
    try:
        path = get_screener_credentials_path()
        _atomic_encrypt_write(path, credentials, SCREENER_CREDENTIALS_FILENAME)
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

def _find_index_for_provider(creds: Dict, provider_upper: str) -> Optional[str]:
    for k, v in creds.items():
        if _PROVIDER_KEY_RE.match(k) and str(v).strip().upper() == provider_upper:
            return k.split("_")[-1]
    return None

def _alloc_new_index(creds: Dict) -> str:
    indices = _iter_provider_indices(creds)
    next_idx_int = (indices[-1] + 1) if indices else 1
    return f"{next_idx_int:02d}"  # zero-padded per spec (01, 02, ...)

def _collect_index_view(creds: Dict, index: str) -> Dict[str, str]:
    """Return a base-key→value mapping for a given index (without suffix)."""
    view: Dict[str, str] = {}
    schema_keys = _get_schema_keys()
    for base_key in schema_keys:
        view[base_key] = creds.get(f"{base_key}_{index}", "")
    for flag in USAGE_FLAGS:
        view[flag] = creds.get(f"{flag}_{index}", "false")
    return view

def _normalize_flag(v) -> str:
    return "true" if str(v).strip().lower() in ("1", "true", "yes", "y", "on") else "false"

def get_provider_credentials(provider: str) -> Optional[Dict]:
    creds = load_screener_credentials()
    idx = _find_index_for_provider(creds, provider.strip().upper())
    if idx is None:
        return None
    return _collect_index_view(creds, idx)

def update_provider_credentials(provider: str, new_values: Dict) -> None:
    """
    Create or update credentials for a provider. Ensures:
    - Stable index per provider (PROVIDER_XX).
    - All per-provider fields written as KEY_XX.
    - Usage flags normalized to 'true'/'false'.
    - Append-only audit: ADDED / UPDATED / ROTATED.
    """
    provider_upper = provider.strip().upper()
    try:
        creds = load_screener_credentials()
        schema_keys = _get_schema_keys()

        existing_idx = _find_index_for_provider(creds, provider_upper)
        if existing_idx is None:
            index = _alloc_new_index(creds)
            existed = False
            old_view = {}
        else:
            index = existing_idx
            existed = True
            old_view = _collect_index_view(creds, index)

        # Remove any prior keys for this index to avoid stale fields
        for k in [k for k in list(creds.keys()) if k.endswith(f"_{index}")]:
            del creds[k]

        # Write per-provider fields
        for base_key in schema_keys:
            creds[f"{base_key}_{index}"] = new_values.get(base_key, "")

        # Normalize and persist usage flags
        for flag in USAGE_FLAGS:
            raw = new_values.get(flag, "false")
            creds[f"{flag}_{index}"] = _normalize_flag(raw)

        # Mapping key: PROVIDER_XX
        creds[f"PROVIDER_{index}"] = provider_upper

        # Persist encrypted
        save_screener_credentials(creds)

        # Audit actions
        if not existed:
            _audit_log("CREDENTIAL_ADDED", provider_upper)
        else:
            _audit_log("CREDENTIAL_UPDATED", provider_upper)
            # Rotation detection on secret fields
            new_view = _collect_index_view(creds, index)
            rotated = any((old_view.get(k, "") != new_view.get(k, "")) for k in SECRET_FIELDS)
            if rotated:
                _audit_log("CREDENTIAL_ROTATED", provider_upper)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to update credentials: {e}")

def delete_provider_credentials(provider: str) -> None:
    """
    Delete credentials for a provider (by name). Removes all KEY_XX fields and
    the PROVIDER_XX mapping. Always appends CREDENTIAL_DELETED when mapping existed.
    """
    provider_upper = provider.strip().upper()
    try:
        creds = load_screener_credentials()
        idx = _find_index_for_provider(creds, provider_upper)
        if idx is None:
            return  # idempotent no-op

        # Remove per-index keys
        for k in [k for k in list(creds.keys()) if k.endswith(f"_{idx}")]:
            del creds[k]

        # Remove provider mapping
        del creds[f"PROVIDER_{idx}"]

        # Persist
        save_screener_credentials(creds)

        # Audit
        _audit_log("CREDENTIAL_DELETED", provider_upper)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to delete credentials: {e}")

def list_providers() -> List[str]:
    creds = load_screener_credentials()
    return [str(v) for k, v in creds.items() if _PROVIDER_KEY_RE.match(k)]

def screener_creds_exist() -> bool:
    creds = load_screener_credentials()
    return any(_PROVIDER_KEY_RE.match(k) for k in creds.keys())

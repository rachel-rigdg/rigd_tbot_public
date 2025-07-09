# tbot_bot/support/secrets_manager.py
# Central encryption/decryption/loader for all screener API credentials. (Called by all loaders/adapters.)
# 100% compliant with v046 screener universe/credential spec.

import os
from typing import Dict, Optional
from tbot_bot.support.decrypt_secrets import decrypt_json, encrypt_json

SCREENER_CREDENTIALS_FILENAME = "screener_api.json.enc"

def get_screener_credentials_path() -> str:
    from tbot_bot.support.path_resolver import get_secret_path
    return get_secret_path(SCREENER_CREDENTIALS_FILENAME)

def load_screener_credentials() -> Dict:
    """
    Loads decrypted screener/universe adapter credentials from dedicated encrypted secrets file.
    Returns dict with provider-labeled keys and secret values.
    """
    try:
        return decrypt_json("screener_api")
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to load screener credentials: {e}")

def save_screener_credentials(credentials: Dict) -> None:
    """
    Saves (encrypts) the provided credentials dict to the dedicated secrets file.
    """
    try:
        encrypt_json("screener_api", credentials)
    except Exception as e:
        raise RuntimeError(f"[secrets_manager] Failed to save screener credentials: {e}")

def get_provider_credentials(provider: str) -> Optional[Dict]:
    """
    Returns the dict of credentials for a given provider label.
    Example: provider = "FINNHUB" or "IBKR"
    """
    creds = load_screener_credentials()
    key = provider.strip().upper()
    for k in creds:
        if k.strip().upper() == key:
            return creds[k]
    return None

def update_provider_credentials(provider: str, new_values: Dict) -> None:
    """
    Updates credentials for the given provider (add/edit), writes encrypted file atomically.
    """
    creds = load_screener_credentials()
    key = provider.strip().upper()
    creds[key] = new_values
    save_screener_credentials(creds)

def delete_provider_credentials(provider: str) -> None:
    """
    Deletes credentials for the given provider.
    """
    creds = load_screener_credentials()
    key = provider.strip().upper()
    if key in creds:
        del creds[key]
        save_screener_credentials(creds)

def list_providers() -> list:
    """
    Returns list of provider keys in the credential file.
    """
    creds = load_screener_credentials()
    return list(creds.keys())

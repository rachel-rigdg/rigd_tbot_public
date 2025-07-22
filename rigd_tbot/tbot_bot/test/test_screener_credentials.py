# test/test_screener_credentials.py
# Unit tests for TradeBot Screener Credential Management
# 100% specification-compliant: tests persistent, indexed, multi-provider handling, usage flags (UNIVERSE_ENABLED, TRADING_ENABLED), and audit log writes.

import os
import tempfile
import shutil
import pytest
import json
from tbot_bot.support import secrets_manager
from tbot_bot.support.path_resolver import resolve_control_path

# Patch locations for isolation
ORIG_KEY_DIR = secrets_manager.KEY_DIR
ORIG_AUDIT_LOG_PATH = secrets_manager.AUDIT_LOG_PATH

@pytest.fixture(scope="function")
def temp_credential_env(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    secrets_dir = os.path.join(tmpdir, "secrets")
    keys_dir = os.path.join(tmpdir, "keys")
    logs_dir = os.path.join(tmpdir, "logs")
    os.makedirs(secrets_dir)
    os.makedirs(keys_dir)
    os.makedirs(logs_dir)
    monkeypatch.setattr(secrets_manager, "KEY_DIR", keys_dir)
    monkeypatch.setattr(secrets_manager, "AUDIT_LOG_PATH", os.path.join(logs_dir, "screener_credentials_audit.log"))
    monkeypatch.setattr(secrets_manager, "get_screener_credentials_path", lambda: os.path.join(secrets_dir, "screener_api.json.enc"))
    yield
    shutil.rmtree(tmpdir)

def test_add_and_update_credentials(temp_credential_env):
    provider1 = "FINNHUB"
    values1 = {
        "SCREENER_NAME": "FINNHUB",
        "SCREENER_USERNAME": "u1",
        "SCREENER_PASSWORD": "pw1",
        "SCREENER_URL": "url1",
        "SCREENER_API_KEY": "ak1",
        "SCREENER_TOKEN": "tk1",
        "UNIVERSE_ENABLED": "true",
        "TRADING_ENABLED": "false"
    }
    secrets_manager.update_provider_credentials(provider1, values1)
    creds = secrets_manager.load_screener_credentials()
    idx1 = [k.split("_")[-1] for k, v in creds.items() if k.startswith("PROVIDER_") and v == provider1][0]
    for key, val in values1.items():
        assert creds.get(f"{key}_{idx1}") == val
    assert creds.get(f"PROVIDER_{idx1}") == provider1
    provider2 = "IBKR"
    values2 = {
        "SCREENER_NAME": "IBKR",
        "SCREENER_USERNAME": "u2",
        "SCREENER_PASSWORD": "pw2",
        "SCREENER_URL": "url2",
        "SCREENER_API_KEY": "ak2",
        "SCREENER_TOKEN": "tk2",
        "UNIVERSE_ENABLED": "false",
        "TRADING_ENABLED": "true"
    }
    secrets_manager.update_provider_credentials(provider2, values2)
    creds = secrets_manager.load_screener_credentials()
    idx2 = [k.split("_")[-1] for k, v in creds.items() if k.startswith("PROVIDER_") and v == provider2][0]
    for key, val in values2.items():
        assert creds.get(f"{key}_{idx2}") == val
    assert creds.get(f"PROVIDER_{idx2}") == provider2
    secrets_manager.update_provider_credentials(provider1, {**values1, "TRADING_ENABLED": "true"})
    creds = secrets_manager.load_screener_credentials()
    assert creds.get(f"TRADING_ENABLED_{idx1}") == "true"

def test_delete_credentials(temp_credential_env):
    provider = "FINNHUB"
    values = {
        "SCREENER_NAME": "FINNHUB",
        "SCREENER_USERNAME": "u1",
        "SCREENER_PASSWORD": "pw1",
        "SCREENER_URL": "url1",
        "SCREENER_API_KEY": "ak1",
        "SCREENER_TOKEN": "tk1",
        "UNIVERSE_ENABLED": "true",
        "TRADING_ENABLED": "false"
    }
    secrets_manager.update_provider_credentials(provider, values)
    creds = secrets_manager.load_screener_credentials()
    idx = [k.split("_")[-1] for k, v in creds.items() if k.startswith("PROVIDER_") and v == provider][0]
    secrets_manager.delete_provider_credentials(provider)
    creds = secrets_manager.load_screener_credentials()
    assert not any(k.endswith(f"_{idx}") or k == f"PROVIDER_{idx}" for k in creds)

def test_list_providers(temp_credential_env):
    secrets_manager.update_provider_credentials("FINNHUB", {"SCREENER_NAME": "FINNHUB"})
    secrets_manager.update_provider_credentials("IBKR", {"SCREENER_NAME": "IBKR"})
    providers = secrets_manager.list_providers()
    assert "FINNHUB" in providers
    assert "IBKR" in providers

def test_audit_log_written(temp_credential_env):
    provider = "FINNHUB"
    values = {
        "SCREENER_NAME": "FINNHUB",
        "UNIVERSE_ENABLED": "true",
        "TRADING_ENABLED": "false"
    }
    secrets_manager.update_provider_credentials(provider, values)
    audit_path = secrets_manager.AUDIT_LOG_PATH
    with open(audit_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "CREDENTIAL_ADDED" in content
    secrets_manager.delete_provider_credentials(provider)
    with open(audit_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "CREDENTIAL_DELETED" in content

def test_flags_for_usage(temp_credential_env):
    secrets_manager.update_provider_credentials("FINNHUB", {
        "SCREENER_NAME": "FINNHUB",
        "UNIVERSE_ENABLED": "true",
        "TRADING_ENABLED": "false"
    })
    secrets_manager.update_provider_credentials("IBKR", {
        "SCREENER_NAME": "IBKR",
        "UNIVERSE_ENABLED": "false",
        "TRADING_ENABLED": "true"
    })
    from tbot_bot.screeners import screener_utils
    uni = screener_utils.get_universe_screener_secrets()
    assert uni["SCREENER_NAME"] == "FINNHUB"

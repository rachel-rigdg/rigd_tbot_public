# tbot_web/support/security_users.py
# Manages user roles, permissions, security policies, and key provisioning for RIGD TradeBot Web UI

from typing import Optional, Dict
from enum import Enum
from tbot_bot.support.utils_log import log_event
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
import os
import json

class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    VIEWER = "viewer"

ROLE_PERMISSIONS = {
    UserRole.ADMIN: {
        "view_dashboard",
        "edit_configuration",
        "manage_users",
        "start_stop_bot",
        "view_logs",
        "edit_coa",
        "view_coa",
        "export_reports"
    },
    UserRole.OPERATOR: {
        "view_dashboard",
        "start_stop_bot",
        "view_logs",
        "view_coa",
        "export_reports"
    },
    UserRole.AUDITOR: {
        "view_dashboard",
        "view_logs",
        "view_coa",
        "export_reports"
    },
    UserRole.VIEWER: {
        "view_dashboard"
    }
}

class SecurityUsers:
    def __init__(self):
        self._user_roles: Dict[str, UserRole] = {}
        self.bot_identity_string = self._load_bot_identity_string()

    def _load_bot_identity_string(self) -> str:
        tmp_config_path = Path(__file__).resolve().parents[2] / "support" / "tmp" / "bootstrap_config.json"
        if tmp_config_path.exists():
            try:
                with open(tmp_config_path, "r") as f:
                    config = json.load(f)
                bot_identity = config.get("bot_identity", {})
                return bot_identity.get("BOT_IDENTITY_STRING", "")
            except Exception as e:
                log_event("security_users", f"Failed to load BOT_IDENTITY_STRING from tmp config: {e}", level="error")
                return ""
        return ""

    def set_user_role(self, username: str, role: UserRole) -> None:
        self._user_roles[username] = role
        log_event("security_users", f"Role '{role}' assigned to user '{username}' at {datetime.utcnow().isoformat()}")

    def get_user_role(self, username: str) -> Optional[UserRole]:
        return self._user_roles.get(username)

    def check_permission(self, username: str, permission: str) -> bool:
        role = self.get_user_role(username)
        if role is None:
            log_event("security_users", f"Permission check failed: unknown user '{username}'", level="warning")
            return False
        allowed = permission in ROLE_PERMISSIONS.get(role, set())
        log_event("security_users", f"Permission check for user '{username}' on '{permission}': {allowed}")
        return allowed

    def user_can_view_dashboard(self, username: str) -> bool:
        return self.check_permission(username, "view_dashboard")

    def user_can_edit_configuration(self, username: str) -> bool:
        return self.check_permission(username, "edit_configuration")

    def user_can_manage_users(self, username: str) -> bool:
        return self.check_permission(username, "manage_users")

    def user_can_start_stop_bot(self, username: str) -> bool:
        return self.check_permission(username, "start_stop_bot")

    def user_can_view_logs(self, username: str) -> bool:
        return self.check_permission(username, "view_logs")

    def user_can_edit_coa(self, username: str) -> bool:
        return self.check_permission(username, "edit_coa")

    def user_can_view_coa(self, username: str) -> bool:
        return self.check_permission(username, "view_coa")

    def user_can_export_reports(self, username: str) -> bool:
        return self.check_permission(username, "export_reports")

def _resolve_log_output_dir():
    # Use output/<BOT_IDENTITY_STRING>/logs always (compliant with build spec)
    bot_identity_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    if not (bot_identity_path.exists() and key_path.exists()):
        return Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "bootstrap" / "logs"
    try:
        key = key_path.read_bytes()
        fernet = Fernet(key)
        data = json.loads(fernet.decrypt(bot_identity_path.read_bytes()).decode("utf-8"))
        identity = data.get("BOT_IDENTITY_STRING", None)
        if identity:
            outdir = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / identity / "logs"
            outdir.mkdir(parents=True, exist_ok=True)
            return outdir
    except Exception:
        pass
    return Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "bootstrap" / "logs"

KEYS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys"
KEYS_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets"
SECRETS_DIR.mkdir(parents=True, exist_ok=True)

def _log_event(category, message, level="info"):
    log_dir = _resolve_log_output_dir()
    log_file = log_dir / f"{category}.log"
    ts = datetime.utcnow().isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {message}\n")

def _write_key_file(filename: str) -> None:
    key_path = KEYS_DIR / filename
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)
    _log_event("security_users", f"Generated new Fernet key (overwritten): {key_path}")

def _encrypt_and_write_json(category: str, data: dict):
    key_path = KEYS_DIR / f"{category}.key"
    secret_path = SECRETS_DIR / f"{category}.json.enc"
    if not key_path.exists():
        raise FileNotFoundError(f"Missing Fernet key: {key_path}")
    key = key_path.read_bytes()
    fernet = Fernet(key)
    plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
    ciphertext = fernet.encrypt(plaintext)
    secret_path.write_bytes(ciphertext)
    os.chmod(secret_path, 0o600)
    _log_event("security_users", f"Encrypted {category} secret: {secret_path}")

def write_encrypted_bot_identity_secret(data: dict):
    _encrypt_and_write_json("bot_identity", data)

def write_encrypted_network_config_secret(data: dict):
    _encrypt_and_write_json("network_config", data)

def write_encrypted_alert_secret(data: dict):
    _encrypt_and_write_json("alert_channels", data)

def write_encrypted_broker_secret(data: dict):
    _encrypt_and_write_json("broker_credentials", data)

def write_encrypted_smtp_secret(data: dict):
    _encrypt_and_write_json("smtp_credentials", data)

def write_encrypted_screener_api_secret(data: dict):
    _encrypt_and_write_json("screener_api", data)

def write_encrypted_acctapi_secret(data: dict):
    _encrypt_and_write_json("acct_api_credentials", data)

def generate_and_save_bot_identity_key() -> None:
    _write_key_file("bot_identity.key")

def generate_or_load_login_keypair() -> None:
    _write_key_file("login.key")

def generate_and_save_broker_keys() -> None:
    _write_key_file("broker_credentials.key")

def generate_and_save_smtp_keys() -> None:
    _write_key_file("smtp_credentials.key")

def generate_and_save_screener_keys() -> None:
    _write_key_file("screener_api.key")

def generate_and_save_acctapi_keys() -> None:
    _write_key_file("acct_api_credentials.key")

def generate_and_save_alert_keys() -> None:
    _write_key_file("alert_channels.key")

def generate_and_save_network_config_keys() -> None:
    _write_key_file("network_config.key")

security_users = SecurityUsers()

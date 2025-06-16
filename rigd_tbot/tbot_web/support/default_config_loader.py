# tbot_web/py/default_config_loader.py
# Loads key/value config defaults from tools/secrets_template.txt and server_template.txt

from pathlib import Path
import re
import sys
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

TEMPLATE_PATHS = [
    Path(__file__).resolve().parents[2] / "tools" / "secrets_template.txt",
    Path(__file__).resolve().parents[2] / "tools" / "server_template.txt"
]

def parse_env_template(path):
    """Parse key=value pairs from a .txt/.env template, stripping quotes."""
    if not Path(path).is_file():
        print(f"[default_config_loader] WARNING: Template file not found: {path}", file=sys.stderr)
        return {}
    config = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'([A-Z0-9_]+)\s*=\s*"?([^"\n#]+)"?', line)
            if match:
                key, value = match.groups()
                config[key] = value.strip()
    return config

def get_default_config():
    if not is_first_bootstrap():
        return {}
    config = {}
    for path in TEMPLATE_PATHS:
        config.update(parse_env_template(path))
    # Adapt keys to UI field names
    mapping = {
        "ENTITY_CODE": "entity_code",
        "JURISDICTION_CODE": "jurisdiction_code",
        "BOT_ID": "bot_id",
        "BROKER_CODE": "broker_name",
        "BROKER_URL": "broker_url",
        "BROKER_API_KEY": "broker_api_key",
        "BROKER_SECRET_KEY": "broker_secret_key",
        "BROKER_USERNAME": "broker_username",
        "BROKER_ACCOUNT_NUMBER": "broker_account_number",
        "BROKER_PASSWORD": "broker_password",
        "FINNHUB_API_KEY": "screener_api_key",
        "SCREENER_NAME": "screener_name",
        # SMTP / Alerts
        "ALERT_EMAIL": "alert_email",
        "SMTP_USER": "smtp_user",
        "SMTP_PASS": "smtp_pass",
        "SMTP_HOST": "smtp_host",
        "SMTP_PORT": "smtp_port",
        # Network config
        "HOSTNAME": "network_name",
        "HOST_IP": "ip",
        "PORT": "port",
    }
    result = {v: config.get(k, "") for k, v in mapping.items()}
    # Add defaults for new required fields if not present (current bot_state logic)
    if "bot_state" not in result:
        result["bot_state"] = "initialize"
    print(f"[default_config_loader] DEBUG: Loaded default config: {result}", file=sys.stderr)
    return result

# Example usage (for testing/dev only):
if __name__ == "__main__":
    print(get_default_config())

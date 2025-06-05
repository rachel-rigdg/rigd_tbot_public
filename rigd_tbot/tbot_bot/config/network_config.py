# tbot_bot/config/network_config.py
# Loads and decrypts network configuration from encrypted JSON secrets.
# Provides getters for HOST_IP, PORT, and HOSTNAME for runtime usage.
# Never falls back to plaintext .env or unencrypted files.

from typing import Dict
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.utils_time import utc_now

# Constants for default network config
KEY_NAME = "network_config"
DEFAULT_HOST_IP = "192.168.1.67"
DEFAULT_PORT = 6900
DEFAULT_HOSTNAME = "localhost"

def get_network_config() -> Dict[str, str]:
    """
    Decrypts and returns the network configuration as a dictionary.
    Falls back to default values only if decryption fails.
    """
    try:
        config = decrypt_json(KEY_NAME)
        log_event("network_config", f"Loaded network config at {utc_now().isoformat()}")
        return config
    except FileNotFoundError:
        log_event("network_config", f"Network config or key file not found at {utc_now().isoformat()}", level="error")
        return {
            "HOST_IP": DEFAULT_HOST_IP,
            "PORT": str(DEFAULT_PORT),
            "HOSTNAME": DEFAULT_HOSTNAME
        }
    except Exception as e:
        log_event("network_config", f"Failed to decrypt network config: {e}", level="error")
        return {
            "HOST_IP": DEFAULT_HOST_IP,
            "PORT": str(DEFAULT_PORT),
            "HOSTNAME": DEFAULT_HOSTNAME
        }

def get_host_ip() -> str:
    """
    Returns the decrypted HOST_IP or the default.
    """
    config = get_network_config()
    return config.get("HOST_IP", DEFAULT_HOST_IP)

def get_port() -> int:
    """
    Returns the decrypted PORT as int or the default.
    """
    config = get_network_config()
    try:
        return int(config.get("PORT", DEFAULT_PORT))
    except Exception:
        return DEFAULT_PORT

def get_hostname() -> str:
    """
    Returns the decrypted HOSTNAME or the default.
    """
    config = get_network_config()
    return config.get("HOSTNAME", DEFAULT_HOSTNAME)
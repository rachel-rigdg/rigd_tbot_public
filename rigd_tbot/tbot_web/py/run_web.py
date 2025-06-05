# tbot_web/py/run_web.py
# NOTE: Never loads or sources any plaintext .env—launcher must inject all ENV vars

import sys
from pathlib import Path

# Ensure tbot_web and its parent are in sys.path for absolute imports
WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR.parent))  # Add project root for full module resolution

# FIX: portal_web.py lives under tbot_web/py/, not tbot_web/support/
from tbot_web.py.portal_web import create_app  # Correct absolute import

# All ENV vars (Flask secret key, DB config) injected by launcher, never loaded here.
from tbot_bot.config.network_config import get_host_ip, get_port

app = create_app()

HOST = get_host_ip()
PORT = get_port()

if __name__ == "__main__":
    print(f"[run_web.py] Launching Flask app on {HOST}:{PORT} (network_config loaded via encrypted secrets)")
    app.run(host=HOST, port=PORT)

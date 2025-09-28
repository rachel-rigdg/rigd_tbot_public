# tbot_web/py/run_web.py
# Phase-detecting Flask launcher. Loads correct app for bootstrap, registration, or main.
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR.parent))  # Project root for full module resolution

from tbot_bot.config.network_config import get_host_ip, get_port
from tbot_bot.support.bot_state_manager import get_state  # ADDED

# --- Phase detection ---
def detect_phase():
    try:
        state = (get_state() or "").strip()
    except Exception:
        return "bootstrap"
    if state in ("initialize", "provisioning", "bootstrapping", ""):
        return "bootstrap"
    elif state == "registration":
        return "registration"
    else:
        return "main"

phase = detect_phase()
if phase == "bootstrap":
    from tbot_web.py.portal_web_bootstrap import create_bootstrap_app
    app = create_bootstrap_app()
elif phase == "registration":
    from tbot_web.py.portal_web_registration import create_registration_app
    app = create_registration_app()
else:
    from tbot_web.py.portal_web_main import create_unified_app
    app = create_unified_app()

HOST = get_host_ip()
PORT = get_port()

if __name__ == "__main__":
    print(f"[run_web.py] Launching Flask app ({phase}) on {HOST}:{PORT} (network_config loaded via encrypted secrets)")
    app.run(host="0.0.0.0", port=PORT)

# tbot_web/py/portal_web_provision.py
# Flask entry point for provisioning phase

import os
from tbot_web.py import run_web

if __name__ == "__main__":
    os.environ["BOT_WEB_PHASE"] = "provisioning"
    os.environ["FLASK_SECRET_KEY"] = "changeme-unsafe-dev-key"
    run_web.launch_flask_app()

#!/usr/bin/env python3
# tbot_web/py/portal_web_router.py
# Routes HTTP to the correct running Flask app based on bot_state.txt.
# Does NOT launch Flask apps; assumes supervisor manages lifecycle.

import sys
from flask import Flask, redirect, request
from pathlib import Path
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

app = Flask(__name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
PHASE_PORTS = {
    "initialize":                   6901,
    "configuration":                6901,
    "provisioning":                 6900,
    "bootstrapping":                6900,
    "registration":                 6900,
    "main":                         6900,
    "idle":                         6900,
    "analyzing":                    6900,
    "monitoring":                   6900,
    "trading":                      6900,
    "updating":                     6900,
    "shutdown":                     6900,
    "graceful_closing_positions":   6900,
    "emergency_closing_positions":  6900,
    "shutdown_triggered":           6900,
    "error":                        6900,
}

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

def get_bot_state():
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return state if state in PHASE_PORTS else "initialize"
    except Exception:
        return "initialize"

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def router(path):
    state = get_bot_state()
    target_port = PHASE_PORTS.get(state, 6901)
    if not is_port_open(target_port):
        if target_port == 6901:
            return "TradeBot: System initializing. Please refresh in a moment.", 200
        else:
            return "TradeBot: Phase UI not ready. Please refresh shortly.", 503
    query = request.query_string.decode("utf-8")
    dest = f"http://{request.host.split(':')[0]}:{target_port}/{path}"
    if query:
        dest += f"?{query}"
    return redirect(dest, code=302)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6900)

#!/usr/bin/env python3
# tbot_web/py/portal_web_router.py
# routs to correct flask app 

from flask import Flask, redirect
from pathlib import Path

app = Flask(__name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
PORT_MAP = {
    "initialize":                   6901,
    "provisioning":                 6902,
    "bootstrapping":                6903,
    "registration":                 6904,
    "main":                         6905,
    "idle":                         6905,
    "analyzing":                    6905,
    "monitoring":                   6905,
    "trading":                      6905,
    "updating":                     6905,
    "shutdown":                     6905,
    "graceful_closing_positions":   6905,
    "emergency_closing_positions":  6905,
    "shutdown_triggered":           6905,
    "error":                        6905,
}


def get_bot_state():
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return state if state in PORT_MAP else "initialize"
    except Exception:
        return "initialize"

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def router(path):
    state = get_bot_state()
    target_port = PORT_MAP.get(state, 6901)
    if target_port == 6901:
        return "TradeBot: System initializing. Please refresh in a moment.", 200
    from flask import request
    query = request.query_string.decode("utf-8")
    dest = f"http://{request.host.split(':')[0]}:{target_port}/{path}"
    if query:
        dest += f"?{query}"
    return redirect(dest, code=302)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6900)

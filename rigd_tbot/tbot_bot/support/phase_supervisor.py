#!/usr/bin/env python3
# tbot_bot/support/phase_supervisor.py

import subprocess
import time
from pathlib import Path
import sys

sys.stdout = open("/home/tbot/rigd_tbot/output/bootstrap/logs/phase_supervisor.log", "a")
sys.stderr = sys.stdout

ROOT_DIR = Path(__file__).resolve().parents[1]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_DIR = ROOT_DIR.parent / "tbot_web" / "py"

PHASE_APPS = {
    "initialize":      "portal_web_configuration.py",
    "provisioning":    "portal_web_provision.py",
    "bootstrapping":   "portal_web_bootstrap.py",
    "registration":    "portal_web_registration.py",
    "main":            "portal_web_main.py",
    "idle":            "portal_web_main.py",
    "analyzing":       "portal_web_main.py",
    "monitoring":      "portal_web_main.py",
    "trading":         "portal_web_main.py",
    "updating":        "portal_web_main.py",
    "shutdown":        "portal_web_main.py",
    "graceful_closing_positions": "portal_web_main.py",
    "emergency_closing_positions": "portal_web_main.py",
    "shutdown_triggered": "portal_web_main.py",
    "error":           "portal_web_main.py",
}

BOT_START_PHASES = {
    "main", "idle", "analyzing", "monitoring", "trading", "updating"
}

def read_bot_state():
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "initialize"

def is_port_open(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

def start_flask_app(script_path, port):
    if is_port_open(port):
        return None  # Already running
    return subprocess.Popen(
        ["python3", str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def supervisor_loop():
    print("[phase_supervisor] Starting TradeBot phase supervisor...")
    active_process = None
    last_phase = None
    while True:
        phase = read_bot_state()
        if phase not in PHASE_APPS:
            phase = "initialize"
        if phase != last_phase:
            print(f"[phase_supervisor] Phase changed: {last_phase} -> {phase}")
            # Kill previous phase app
            if active_process:
                active_process.terminate()
                try:
                    active_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    active_process.kill()
                active_process = None
            # Do NOT launch portal_web_router.py here; only manage phase Flask apps below
            port_map = {
                "initialize": 6901,
                "provisioning": 6902,
                "bootstrapping": 6903,
                "registration": 6904,
                "main": 6905,
                "idle": 6905,
                "analyzing": 6905,
                "monitoring": 6905,
                "trading": 6905,
                "updating": 6905,
                "shutdown": 6905,
                "graceful_closing_positions": 6905,
                "emergency_closing_positions": 6905,
                "shutdown_triggered": 6905,
                "error": 6905,
            }
            port = port_map.get(phase, 6901)
            script = PHASE_APPS[phase]
            script_path = WEB_DIR / script
            active_process = start_flask_app(script_path, port)
            # Start bot only after registration phase or later
            if phase in BOT_START_PHASES:
                subprocess.run(["systemctl", "--user", "start", "tbot_bot.service"])
        last_phase = phase
        time.sleep(3)

if __name__ == "__main__":
    supervisor_loop()

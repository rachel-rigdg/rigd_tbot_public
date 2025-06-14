#!/usr/bin/env python3
# tbot_bot/support/phase_supervisor.py

import subprocess
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sys

sys.stdout = open("/home/tbot/rigd_tbot/tbot_bot/output/bootstrap/logs/phase_supervisor.log", "a")
sys.stderr = sys.stdout

ROOT_DIR = Path(__file__).resolve().parents[1]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_DIR = ROOT_DIR.parent / "tbot_web" / "py"

PHASE_APPS = {
    "initialize":      "portal_web_configuration",
    "provisioning":    "portal_web_provision",
    "bootstrapping":   "portal_web_bootstrap",
    "registration":    "portal_web_registration",
    "main":            "portal_web_main",
    "idle":            "portal_web_main",
    "analyzing":       "portal_web_main",
    "monitoring":      "portal_web_main",
    "trading":         "portal_web_main",
    "updating":        "portal_web_main",
    "shutdown":        "portal_web_main",
    "graceful_closing_positions": "portal_web_main",
    "emergency_closing_positions": "portal_web_main",
    "shutdown_triggered": "portal_web_main",
    "error":           "portal_web_main",
}

BOT_START_PHASES = {
    "main", "idle", "analyzing", "monitoring", "trading", "updating"
}

def read_bot_state():
    try:
        val = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        print(f"[phase_supervisor] BOT_STATE_PATH: {BOT_STATE_PATH}  value: {val}")
        return val
    except Exception as ex:
        print(f"[phase_supervisor] ERROR reading bot_state.txt: {ex}")
        return "initialize"

def is_port_open(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", port)) == 0
        print(f"[phase_supervisor] is_port_open({port}): {result}")
        return result

def start_flask_app(module_name, port):
    if is_port_open(port):
        print(f"[phase_supervisor] Flask app for port {port} already running: {module_name}")
        return None  # Already running
    print(f"[phase_supervisor] Launching Flask app: python3 -m tbot_web.py.{module_name} (port {port})")
    try:
        proc = subprocess.Popen(
            ["python3", "-m", f"tbot_web.py.{module_name}"],
        )
        print(f"[phase_supervisor] Launched process PID={proc.pid} for {module_name}")
        return proc
    except Exception as ex:
        print(f"[phase_supervisor] ERROR launching {module_name}: {ex}")
        return None

def supervisor_loop():
    print("[phase_supervisor] Starting TradeBot phase supervisor...")
    active_process = None
    last_phase = None
    while True:
        phase = read_bot_state()
        if phase not in PHASE_APPS:
            print(f"[phase_supervisor] Unrecognized phase '{phase}', defaulting to 'initialize'")
            phase = "initialize"
        if phase != last_phase:
            print(f"[phase_supervisor] Phase changed: {last_phase} -> {phase}")
            # Kill previous phase app
            if active_process:
                print(f"[phase_supervisor] Terminating previous phase Flask app...")
                active_process.terminate()
                try:
                    active_process.wait(timeout=5)
                    print(f"[phase_supervisor] Flask app process terminated.")
                except subprocess.TimeoutExpired:
                    print(f"[phase_supervisor] Flask app process did not terminate in time, killing...")
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
            module_name = PHASE_APPS[phase]
            active_process = start_flask_app(module_name, port)
            # Start bot only after registration phase or later
            if phase in BOT_START_PHASES:
                print(f"[phase_supervisor] Starting tbot_bot.service for phase: {phase}")
                subprocess.run(["systemctl", "--user", "start", "tbot_bot.service"])
        last_phase = phase
        time.sleep(3)

if __name__ == "__main__":
    supervisor_loop()

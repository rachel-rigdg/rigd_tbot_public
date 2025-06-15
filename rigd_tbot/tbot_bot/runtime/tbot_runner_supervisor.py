#!/usr/bin/env python3
# tbot_bot/runtime/tbot_runner_supervisor.py
# Unified bot phase and UI supervisor. Controls initialization, configuration, provisioning, bootstrapping, registration, and launches the operational bot as specified.

import subprocess
import time
import sys
from pathlib import Path
import signal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_DIR = ROOT_DIR / "tbot_web" / "py"
LOG_PATH = ROOT_DIR / "tbot_bot" / "output" / "bootstrap" / "logs" / "tbot_runner_supervisor.log"

PHASE_APPS = {
    "initialize":      ("portal_web_configuration", 6901),
    "configuration":   ("portal_web_configuration", 6901),
    "provisioning":    ("portal_web_main", 6900),
    "bootstrapping":   ("portal_web_main", 6900),
    "registration":    ("portal_web_main", 6900),
    "main":            ("portal_web_main", 6900),
    "idle":            ("portal_web_main", 6900),
    "analyzing":       ("portal_web_main", 6900),
    "monitoring":      ("portal_web_main", 6900),
    "trading":         ("portal_web_main", 6900),
    "updating":        ("portal_web_main", 6900),
    "shutdown":        ("portal_web_main", 6900),
    "graceful_closing_positions": ("portal_web_main", 6900),
    "emergency_closing_positions": ("portal_web_main", 6900),
    "shutdown_triggered": ("portal_web_main", 6900),
    "error":           ("portal_web_main", 6900),
}

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")

def read_bot_state():
    try:
        val = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        log(f"[supervisor] BOT_STATE_PATH: {BOT_STATE_PATH} value: {val}")
        return val
    except Exception as ex:
        log(f"[supervisor] ERROR reading bot_state.txt: {ex}")
        return "initialize"

def start_flask_app(module_name, port):
    log(f"[supervisor] Launching Flask app: python3 -m tbot_web.py.{module_name} (port {port})")
    env = dict(os.environ)
    env["PORT"] = str(port)
    try:
        proc = subprocess.Popen(
            ["python3", "-m", f"tbot_web.py.{module_name}"],
            cwd=WEB_DIR,
            env=env
        )
        log(f"[supervisor] Launched process PID={proc.pid} for {module_name}")
        return proc
    except Exception as ex:
        log(f"[supervisor] ERROR launching {module_name}: {ex}")
        return None

def kill_process(proc):
    if not proc:
        return
    try:
        log(f"[supervisor] Terminating Flask app PID={proc.pid}")
        proc.terminate()
        proc.wait(timeout=5)
        log(f"[supervisor] Flask app PID={proc.pid} terminated.")
    except Exception:
        log(f"[supervisor] Killing Flask app PID={proc.pid}")
        proc.kill()

def supervisor_loop():
    log("[supervisor] tbot_runner_supervisor started.")
    active_process = None
    last_phase = None

    while True:
        phase = read_bot_state()
        if phase not in PHASE_APPS:
            log(f"[supervisor] Unrecognized phase '{phase}', defaulting to 'initialize'")
            phase = "initialize"

        if phase != last_phase:
            log(f"[supervisor] Phase changed: {last_phase} -> {phase}")

            # Kill any previous Flask app
            kill_process(active_process)
            active_process = None

            module_name, port = PHASE_APPS[phase]
            active_process = start_flask_app(module_name, port)

        last_phase = phase
        time.sleep(2)

def handle_sigterm(sig, frame):
    log("[supervisor] SIGTERM received, shutting down supervisor.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    supervisor_loop()

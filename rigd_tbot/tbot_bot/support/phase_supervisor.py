#!/usr/bin/env python3
# tbot_bot/support/phase_supervisor.py

import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

PHASE_SEQUENCE = [
    "initialize",
    "provisioning",
    "bootstrapping",
    "registration",
    "main"
]

PHASE_UNITS = {
    "initialize":      "tbot_web_bootstrap.service",
    "provisioning":    "tbot_provisioning.service",
    "bootstrapping":   "tbot_web_bootstrap.service",
    "registration":    "tbot_web_registration.service",
    "main":            "tbot_web_main.service",
    "bot":             "tbot_bot.service"
}

ALL_UNITS = [
    "tbot_web_bootstrap.service",
    "tbot_provisioning.service",
    "tbot_web_registration.service",
    "tbot_web_main.service",
    "tbot_bot.service"
]

def read_bot_state():
    if not BOT_STATE_PATH.exists():
        return "initialize"
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "initialize"

def stop_all_services(except_unit=None):
    for unit in ALL_UNITS:
        if unit != except_unit:
            subprocess.run(["sudo", "-n", "systemctl", "stop", unit], check=False)

def start_service(unit):
    subprocess.run(["sudo", "-n", "systemctl", "restart", unit], check=False)

def supervisor_loop():
    print("[phase_supervisor] TradeBot phase supervisor started. Monitoring bot_state.txt...")
    last_phase = None
    while True:
        phase = read_bot_state()
        print(f"[phase_supervisor] read_bot_state() returned: {phase}")
        if phase not in PHASE_UNITS:
            phase = "initialize"
        active_unit = PHASE_UNITS[phase]

        if phase != last_phase:
            print(f"[phase_supervisor] Phase transition detected: {last_phase} -> {phase}")
            stop_all_services(except_unit=active_unit)
            start_service(active_unit)
            if phase == "main":
                start_service(PHASE_UNITS["bot"])
            else:
                subprocess.run(["sudo", "-n", "systemctl", "stop", PHASE_UNITS["bot"]], check=False)
        last_phase = phase
        time.sleep(2)

if __name__ == "__main__":
    supervisor_loop()

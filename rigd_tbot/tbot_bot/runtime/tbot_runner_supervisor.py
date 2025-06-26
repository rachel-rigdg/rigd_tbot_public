# tbot_bot/runtime/tbot_runner_supervisor.py
# WATCHER. Only launched by main.py (never by another process, never standalone except for test/dev).
# Oversees session state, handles retries, enforces global watchdog logic, and updates bot_state.txt.
# Never watches or acts on control flags for test_mode; only handles control_start.flag and control_stop.flag as main lifecycle triggers.
# Never launches or supervises other watchers or workers. Does not start in TEST_MODE unless future spec requires.

import os
import time
import subprocess
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.runtime.status_bot import update_bot_state

config = get_bot_config()
SLEEP_TIME_RAW = str(config.get("SLEEP_TIME", "2s")).strip()
SLEEP_TIME = float(SLEEP_TIME_RAW[:-1]) if SLEEP_TIME_RAW.endswith("s") else float(SLEEP_TIME_RAW)

CONTROL_DIR = Path("tbot_bot/control")
START_FILE = CONTROL_DIR / "control_start.flag"
STOP_FILE = CONTROL_DIR / "control_stop.flag"

LOG_PATH = get_output_path("logs", "supervisor.log")
BOT_ENTRY = Path("tbot_bot/runtime/main.py")

CONTROL_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")

def clear_flags():
    for flag in [START_FILE, STOP_FILE]:
        try:
            if flag.exists():
                flag.unlink()
        except Exception as e:
            log(f"Failed to clear flag {flag.name}: {e}")

def main():
    bot_process = None
    log("Supervisor launched and monitoring control flags...")

    while True:
        try:
            # Launch bot if START_FILE is present and no bot is running
            if START_FILE.exists() and not bot_process:
                log("START signal detected.")
                update_bot_state("idle")
                clear_flags()
                bot_process = subprocess.Popen(
                    ["python3", str(BOT_ENTRY)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=BOT_ENTRY.parent,
                    text=True
                )
                log(f"Bot launched with PID {bot_process.pid}")

            # Terminate bot if STOP_FILE is present
            elif STOP_FILE.exists() and bot_process:
                log("STOP signal detected.")
                update_bot_state("shutdown")
                clear_flags()
                bot_process.terminate()
                try:
                    bot_process.wait(timeout=10)
                    log("Bot terminated gracefully.")
                except subprocess.TimeoutExpired:
                    bot_process.kill()
                    log("Bot forcibly killed after timeout.")
                bot_process = None

            # Check if process exited unexpectedly
            if bot_process and bot_process.poll() is not None:
                exit_code = bot_process.returncode
                log(f"Bot exited with code {exit_code}")
                update_bot_state("idle")
                bot_process = None

        except Exception as e:
            log(f"Supervisor exception: {e}")
            log_event("supervisor", f"Loop error: {e}")

        time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    main()

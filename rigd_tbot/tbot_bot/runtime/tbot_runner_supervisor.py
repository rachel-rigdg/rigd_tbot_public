# tbot_bot/runtime/tbot_runner_supervisor.py
# Oversees session state, handles retries, enforces global watchdog logic

import os
import time
import subprocess
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event  # UPDATED: from utils_log
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.runtime.status_bot import update_bot_state

print("[supervisor] Importing configuration and utilities...")

# Load configuration (post-v1.0.0 — single-broker compliant)
config = get_bot_config()
print(f"[supervisor] Loaded config: {config}")
SLEEP_TIME_RAW = str(config.get("SLEEP_TIME", "2s")).strip()
SLEEP_TIME = float(SLEEP_TIME_RAW[:-1]) if SLEEP_TIME_RAW.endswith("s") else float(SLEEP_TIME_RAW)

# Control flag directory and files (systemd-safe)
CONTROL_DIR = Path("tbot_bot/control")
START_FILE = CONTROL_DIR / "control_start.txt"
STOP_FILE = CONTROL_DIR / "control_stop.txt"

# Log output path (resolved via identity-aware path_resolver)
LOG_PATH = get_output_path("logs", "supervisor.log")

# Bot entrypoint — must reference updated session runner
BOT_ENTRY = Path("tbot_bot/runtime/main.py")

# Ensure directories exist
print(f"[supervisor] Ensuring control and log directories exist...")
CONTROL_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    """
    Internal logger for supervisor actions — writes to output/logs/supervisor.log
    """
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"[supervisor][log] {msg}")

def clear_flags():
    """
    Clears control_start.txt and control_stop.txt to avoid stale triggers.
    """
    print("[supervisor][clear_flags] Clearing start/stop flags if present...")
    for flag in [START_FILE, STOP_FILE]:
        try:
            if flag.exists():
                flag.unlink()
                print(f"[supervisor][clear_flags] Cleared {flag}")
        except Exception as e:
            log(f"Failed to clear flag {flag.name}: {e}")
            print(f"[supervisor][clear_flags] Exception clearing {flag}: {e}")

def main():
    print("[supervisor][main] Entering supervisor main loop...")
    bot_process = None
    log("Supervisor launched and monitoring control flags...")

    while True:
        try:
            print(f"[supervisor][main] Checking flags... START: {START_FILE.exists()}, STOP: {STOP_FILE.exists()}, BOT_PROCESS: {bot_process is not None}")
            # Launch bot if START_FILE is present and no bot is running
            if START_FILE.exists() and not bot_process:
                log("START signal detected.")
                print("[supervisor][main] Detected START signal.")
                update_bot_state("idle")  # Ensure bot starts in idle state
                clear_flags()
                bot_process = subprocess.Popen(
                    ["python3", str(BOT_ENTRY)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=BOT_ENTRY.parent,
                    text=True
                )
                log(f"Bot launched with PID {bot_process.pid}")
                print(f"[supervisor][main] Bot process started, PID: {bot_process.pid}")

            # Terminate bot if STOP_FILE is present
            elif STOP_FILE.exists() and bot_process:
                log("STOP signal detected.")
                print("[supervisor][main] Detected STOP signal.")
                update_bot_state("shutdown")  # Set state to shutdown before killing bot
                clear_flags()
                bot_process.terminate()
                try:
                    bot_process.wait(timeout=10)
                    log("Bot terminated gracefully.")
                    print("[supervisor][main] Bot terminated gracefully.")
                except subprocess.TimeoutExpired:
                    bot_process.kill()
                    log("Bot forcibly killed after timeout.")
                    print("[supervisor][main] Bot forcibly killed after timeout.")
                bot_process = None

            # Check if process exited unexpectedly
            if bot_process and bot_process.poll() is not None:
                exit_code = bot_process.returncode
                log(f"Bot exited with code {exit_code}")
                print(f"[supervisor][main] Bot exited with code {exit_code}")
                update_bot_state("idle")  # Set state back to idle if bot unexpectedly exits
                bot_process = None

        except Exception as e:
            log(f"Supervisor exception: {e}")
            print(f"[supervisor][main] Exception: {e}")
            log_event("supervisor", f"Loop error: {e}")

        time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    print("[supervisor] Supervisor starting...")
    main()

# tbot_bot/runtime/tbot_runner_supervisor.py
# Oversees session state, handles retries, enforces global watchdog logic

import os
import time
import subprocess
from pathlib import Path

print("[supervisor] Importing configuration and utilities...")

CONTROL_DIR = Path("tbot_bot/control")
START_FILE = CONTROL_DIR / "control_start.txt"
STOP_FILE = CONTROL_DIR / "control_stop.txt"
BOT_STATE_FILE = CONTROL_DIR / "bot_state.txt"
STATUS_BOT_PATH = Path("tbot_bot/runtime/status_bot.py")

def log(msg: str):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_path = CONTROL_DIR.parent / "output" / "logs" / "supervisor.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"[supervisor][log] {msg}")

def clear_flags():
    print("[supervisor][clear_flags] Clearing start/stop flags if present...")
    for flag in [START_FILE, STOP_FILE]:
        try:
            if flag.exists():
                flag.unlink()
                print(f"[supervisor][clear_flags] Cleared {flag}")
        except Exception as e:
            log(f"Failed to clear flag {flag.name}: {e}")
            print(f"[supervisor][clear_flags] Exception clearing {flag}: {e}")

def is_operational_state():
    try:
        state = BOT_STATE_FILE.read_text(encoding="utf-8").strip().lower()
        return state in {"main", "idle", "analyzing", "monitoring", "trading", "updating"}
    except Exception:
        return False

def main():
    print("[supervisor][main] Entering supervisor main loop...")
    bot_process = None
    status_proc = None
    log("Supervisor launched and monitoring control flags...")

    while True:
        try:
            print(f"[supervisor][main] Checking flags... START: {START_FILE.exists()}, STOP: {STOP_FILE.exists()}, BOT_PROCESS: {bot_process is not None}, STATUS_PROC: {status_proc is not None}")

            # Launch bot if START_FILE is present and no bot is running
            if START_FILE.exists() and not bot_process:
                log("START signal detected.")
                print("[supervisor][main] Detected START signal.")
                clear_flags()
                bot_process = subprocess.Popen(
                    ["python3", "tbot_bot/runtime/main.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=".",
                    text=True
                )
                log(f"Bot launched with PID {bot_process.pid}")
                print(f"[supervisor][main] Bot process started, PID: {bot_process.pid}")

            # Check for operational state to launch status_bot.py (if not running)
            if bot_process and is_operational_state() and not status_proc:
                status_proc = subprocess.Popen(
                    ["python3", str(STATUS_BOT_PATH)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=".",
                )
                log(f"status_bot.py launched with PID {status_proc.pid}")
                print(f"[supervisor][main] status_bot.py process started, PID: {status_proc.pid}")

            # Terminate bot if STOP_FILE is present
            elif STOP_FILE.exists() and bot_process:
                log("STOP signal detected.")
                print("[supervisor][main] Detected STOP signal.")
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

            # If bot_process exits, terminate status_proc too
            if bot_process and bot_process.poll() is not None:
                exit_code = bot_process.returncode
                log(f"Bot exited with code {exit_code}")
                print(f"[supervisor][main] Bot exited with code {exit_code}")
                if status_proc:
                    status_proc.terminate()
                    try:
                        status_proc.wait(timeout=5)
                        log("status_bot.py terminated with bot exit.")
                        print("[supervisor][main] status_bot.py terminated with bot exit.")
                    except Exception:
                        status_proc.kill()
                    status_proc = None
                bot_process = None

            # If status_proc crashed, clear ref (will restart on next operational state)
            if status_proc and status_proc.poll() is not None:
                log(f"status_bot.py exited unexpectedly with code {status_proc.returncode}")
                print(f"[supervisor][main] status_bot.py exited unexpectedly with code {status_proc.returncode}")
                status_proc = None

        except Exception as e:
            log(f"Supervisor exception: {e}")
            print(f"[supervisor][main] Exception: {e}")

        time.sleep(2)

if __name__ == "__main__":
    print("[supervisor] Supervisor starting...")
    main()

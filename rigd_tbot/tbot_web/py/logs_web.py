# tbot_web/py/logs_web.py
# Displays latest bot log output to the web UI with multi-directory fallback and hour filtering

from flask import Blueprint, render_template, request
# from tbot_web.py.login_web import login_required
from pathlib import Path
from datetime import datetime, timedelta

from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity
from tbot_bot.support.decrypt_secrets import load_bot_identity

print("Loaded BOT_IDENTITY:", load_bot_identity())

logs_blueprint = Blueprint("logs_web", __name__)

LOG_FILES_TO_INCLUDE = [
    "main_bot.log",
    "strategy_open.log",
    "strategy_mid.log",
    "strategy_close.log",
    "heartbeat.log",
    "watchdog_bot.log",
    "router.log",
    "screener.log",
    "kill_switch.log",
    "provisioning.log",
    "error_tracebacks.log",
    "auth_web.log",
    "security_users.log",
    "init_system_logs.log",
    "init_system_users.log",
    "init_user_activity_monitoring.log",
    "init_password_reset_tokens.log"
]

TIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
]

def parse_timestamp(line):
    for tag in ('"timestamp":', "'timestamp':", "timestamp=", "timestamp:"):
        idx = line.find(tag)
        if idx != -1:
            ts_start = idx + len(tag)
            sub = line[ts_start:].lstrip(' =:"\'')
            ts_str = sub.split('"')[0].split("'")[0].split(",")[0].split("}")[0].split("]")[0].split()[0]
            for fmt in TIME_FORMATS:
                try:
                    ts = datetime.strptime(ts_str.replace("Z", "+0000"), fmt)
                    return ts.replace(tzinfo=None)
                except Exception:
                    continue
    import re
    alt_match = re.search(r"\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:Z|\+00:00)?\]?", line)
    if alt_match:
        try:
            return datetime.fromisoformat(alt_match.group(1))
        except Exception:
            pass
    return None

def find_log_file(selected_log, warn_list=None):
    paths = []
    bot_identity_error = None
    try:
        bot_identity_string = load_bot_identity()
        validate_bot_identity(bot_identity_string)
        identity_logs = Path(get_output_path(bot_identity_string, "logs"))
        paths.append(identity_logs / selected_log)
    except Exception as e:
        bot_identity_error = str(e)
        if warn_list is not None:
            warn_list.append(f"Warning: Could not resolve active bot identity. Using fallback log locations. Reason: {bot_identity_error}")
    # Always try fallback locations
    paths.append(Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "logs" / selected_log)
    paths.append(Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "bootstrap" / "logs" / selected_log)
    for p in paths:
        if p.is_file():
            return p
    return None

@logs_blueprint.route("/")
# @login_required
def logs_page():
    selected_log = request.args.get("file", LOG_FILES_TO_INCLUDE[0])
    if selected_log not in LOG_FILES_TO_INCLUDE:
        selected_log = LOG_FILES_TO_INCLUDE[0]

    selected_hours = request.args.get("hours", "24")
    now = datetime.utcnow()
    try:
        hour_window = None if selected_hours == "all" else int(selected_hours)
    except Exception:
        hour_window = 24

    log_content = ""
    warnings = []
    file_path = find_log_file(selected_log, warn_list=warnings)
    if file_path:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if hour_window:
            cutoff = now - timedelta(hours=hour_window)
            filtered = []
            for line in lines:
                ts = parse_timestamp(line)
                if ts and ts >= cutoff:
                    filtered.append(line)
                elif ts is None:
                    filtered.append(line)
            log_content = "\n".join(filtered)
        else:
            log_content = "\n".join(lines)
    else:
        log_content = f"Selected log unavailable: {selected_log}"

    return render_template(
        "logs.html",
        log_text=log_content,
        selected_log=selected_log,
        log_files=LOG_FILES_TO_INCLUDE,
        selected_hours=selected_hours,
        warnings=warnings
    )

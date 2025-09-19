# tbot_bot/runtime/holdings_maintenance.py
# Single-run holdings maintenance worker.
# - Guarded by per-day lock to avoid multiple runs.
# - Reads encrypted holdings config via holdings_manager.perform_holdings_cycle().
# - Posts ledger entries and writes audit via the ledger modules (delegated to holdings_manager).
# - Uses path_resolver for logs/locks. No hardcoded paths. Exits 0/≠0.

from datetime import datetime
from pathlib import Path
import sys

from tbot_bot.trading.holdings_manager import perform_holdings_cycle
from tbot_bot.support.path_resolver import (
    get_bot_state_path,
    get_output_path,
    get_holdings_lock_path,
)
# NEW: stamp for status page
from tbot_bot.support.path_resolver import get_stamp_path

from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from tbot_bot.support.utils_log import get_logger

log = get_logger(__name__)


def _is_bot_ready() -> bool:
    # During bootstrap we do not run holdings maintenance.
    try:
        if is_first_bootstrap(quiet_mode=True):
            return False
    except TypeError:
        # Backward compatibility for is_first_bootstrap() without quiet_mode
        if is_first_bootstrap():
            return False

    state_path = Path(get_bot_state_path())
    try:
        state = state_path.read_text(encoding="utf-8").strip()
        # Avoid running while still initializing/provisioning
        return state not in ("initialize", "provisioning", "bootstrapping")
    except Exception:
        return False


def _write_local_log(line: str) -> None:
    """Append a simple operational line to holdings_maintenance.log via path_resolver."""
    try:
        log_path = Path(get_output_path(category="logs", filename="holdings_maintenance.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} [holdings_maintenance] {line}\n")
    except Exception:
        # best-effort only
        pass


def _parse_session(argv) -> str:
    """
    Supports: --session=open|mid  (default: open)
    Anything else silently falls back to 'open' to preserve legacy behavior.
    """
    for a in argv or []:
        if a.startswith("--session="):
            v = a.split("=", 1)[1].strip().lower()
            if v in ("open", "mid"):
                return v
    return "open"


def main() -> int:
    # Determine session (open|mid) to allow two runs per day with distinct locks.
    session = _parse_session(sys.argv[1:])
    session_tag = f"[session={session}] "

    # Single-run guard & readiness checks
    trading_date = datetime.utcnow().date().isoformat()
    base_lock = Path(get_holdings_lock_path(trading_date))
    # Reuse resolver's directory, but specialize the filename per session.
    if base_lock.name.endswith(".lock"):
        lock_name = base_lock.name.replace(".lock", f"_{session}.lock")
    else:
        lock_name = f"{base_lock.name}_{session}.lock"
    lock_path = base_lock.with_name(lock_name)

    # If we've already run for this session today, exit cleanly (idempotent behavior).
    if lock_path.exists():
        msg = f"{session_tag}Lock exists ({lock_path.name}); holdings maintenance already ran for {trading_date}."
        log.info(msg)
        _write_local_log(msg)
        # Still update the stamp to reflect "last seen" OK state since a prior run exists.
        try:
            Path(get_stamp_path("holdings_manager_last.txt")).write_text(
                f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} OK\n", encoding="utf-8"
            )
        except Exception:
            pass
        return 0

    if not _is_bot_ready():
        msg = f"{session_tag}Bot not ready (bootstrap or initializing); skipping holdings maintenance."
        log.info(msg)
        _write_local_log(msg)
        # Stamp as a benign skip (not a failure)
        try:
            Path(get_stamp_path("holdings_manager_last.txt")).write_text(
                f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} OK\n", encoding="utf-8"
            )
        except Exception:
            pass
        return 0

    # Run once, relying on holdings_manager to:
    # - decrypt holdings secrets/config
    # - post ledger entries
    # - write audit artifacts
    try:
        log.info(f"{session_tag}Starting holdings maintenance cycle (single-run).")
        _write_local_log(f"{session_tag}Starting holdings maintenance cycle.")
        perform_holdings_cycle()
        # Success → stamp lock
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ") + "\n", encoding="utf-8")
        msg = f"{session_tag}Holdings maintenance completed; lock written: {lock_path.name}"
        log.info(msg)
        _write_local_log(msg)
        # Status-page stamp
        try:
            Path(get_stamp_path("holdings_manager_last.txt")).write_text(
                f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} OK\n", encoding="utf-8"
            )
        except Exception:
            pass
        return 0
    except Exception as e:
        # Failure → do NOT create lock; allow external retry policy if desired
        err = f"{session_tag}Exception in holdings_maintenance: {e}"
        log.error(err)
        _write_local_log(err)
        # Status-page stamp
        try:
            Path(get_stamp_path("holdings_manager_last.txt")).write_text(
                f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} Failed\n", encoding="utf-8"
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

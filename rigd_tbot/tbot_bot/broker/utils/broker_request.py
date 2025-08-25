# tbot_bot/broker/utils/broker_request.py

import hashlib
import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Union, Optional

import requests
from tbot_bot.support.utils_log import log_event


ISO_DT_KEYS_HINTS = {
    "time", "timestamp", "datetime", "created_at", "updated_at",
    "filled_at", "submitted_at", "settled_at", "expires_at"
}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_iso_like(s: str) -> bool:
    # Quick heuristic to avoid heavy parsing; catches most ISO-8601 variants
    if not isinstance(s, str):
        return False
    if "T" not in s:
        return False
    # Allow trailing Z or offset
    return any(tok in s for tok in ("Z", "+", "-"))


def _to_utc_iso(s: str) -> Optional[str]:
    """
    Convert an ISO-like string to strict UTC (Z) ISO-8601.
    Returns None if parsing fails.
    """
    try:
        # Normalize Z to +00:00 for fromisoformat
        si = s.replace("Z", "+00:00") if "Z" in s else s
        dt = datetime.fromisoformat(si)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except Exception:
        return None


def _coerce_datetimes_utc(obj: Any, key_hint: Optional[str] = None) -> Any:
    """
    Recursively coerce ISO-like datetime strings to UTC '...Z' strings.
    Leaves non-datetime content unchanged.
    """
    if isinstance(obj, dict):
        return {
            k: _coerce_datetimes_utc(v, k)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_coerce_datetimes_utc(v, key_hint) for v in obj]
    if isinstance(obj, str):
        # Favor keys that imply datetime to reduce false positives
        if key_hint and any(h in key_hint.lower() for h in ISO_DT_KEYS_HINTS):
            iso = _to_utc_iso(obj)
            return iso if iso is not None else obj
        # Fallback heuristic for strings that look like datetimes
        if _is_iso_like(obj):
            iso = _to_utc_iso(obj)
            return iso if iso is not None else obj
    return obj


def _response_hash(resp: requests.Response) -> str:
    try:
        content = resp.content if resp.content is not None else b""
        return hashlib.sha256(content).hexdigest()
    except Exception:
        return "unhashable"


def _json_or_text(resp: requests.Response) -> Union[Dict[str, Any], Any]:
    try:
        return resp.json()
    except Exception:
        return resp.text


def safe_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    max_retries: int = 5,
    backoff_base: float = 0.5,
) -> Any:
    """
    Resilient HTTP request with retry/backoff and UTC datetime coercion.
    - Adds X-Request-ID (UUID4) header to each call.
    - Retries on 429/5xx and common network exceptions.
    - Honors Retry-After on 429 when present (seconds).
    - Logs request_id and response_hash; returns parsed JSON (with UTC '...Z' datetimes coerced) or text.
    """
    request_id = str(uuid.uuid4())
    hdrs = dict(headers or {})
    hdrs.setdefault("X-Request-ID", request_id)

    attempt = 0
    last_exc = None
    while attempt <= max_retries:
        attempt += 1
        t0 = _now_utc_iso()
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=hdrs,
                json=json_data,
                params=params,
                timeout=timeout,
            )
            status = resp.status_code
            rhash = _response_hash(resp)

            # Rate-limit handling
            if status == 429:
                # Prefer server-provided delay
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = min(max(float(retry_after), 0.0), 60.0)
                    except Exception:
                        delay = None
                else:
                    delay = None
                if delay is None:
                    # Exponential backoff with jitter
                    delay = min(60.0, (backoff_base * (2 ** (attempt - 1))) + random.uniform(0, 0.333))
                log_event(
                    "broker_request",
                    f"rate_limited 429; will retry in {delay:.3f}s "
                    f"(attempt {attempt}/{max_retries}) request_id={request_id} url={url} hash={rhash}",
                    level="warning",
                )
                if attempt > max_retries:
                    resp.raise_for_status()
                time.sleep(delay)
                continue

            # Retry on 5xx
            if 500 <= status < 600:
                delay = min(60.0, (backoff_base * (2 ** (attempt - 1))) + random.uniform(0, 0.333))
                log_event(
                    "broker_request",
                    f"server_error {status}; retry in {delay:.3f}s "
                    f"(attempt {attempt}/{max_retries}) request_id={request_id} url={url} hash={rhash}",
                    level="warning",
                )
                if attempt > max_retries:
                    resp.raise_for_status()
                time.sleep(delay)
                continue

            # Success or client error (non-retry)
            resp.raise_for_status()
            data = _json_or_text(resp)
            if isinstance(data, (dict, list)):
                data = _coerce_datetimes_utc(data)

            log_event(
                "broker_request",
                f"success method={method} status={status} request_id={request_id} "
                f"t0={t0} t1={_now_utc_iso()} url={url} hash={rhash}",
                level="info",
            )
            return data

        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            delay = min(60.0, (backoff_base * (2 ** (attempt - 1))) + random.uniform(0, 0.333))
            log_event(
                "broker_request",
                f"network_error retry in {delay:.3f}s (attempt {attempt}/{max_retries}) "
                f"request_id={request_id} url={url} err={e}",
                level="warning",
            )
            if attempt > max_retries:
                break
            time.sleep(delay)
            continue
        except requests.RequestException as e:
            # Non-retryable client errors or exhaust retries
            last_exc = e
            log_event(
                "broker_request",
                f"request_exception method={method} request_id={request_id} url={url} err={e}",
                level="error",
            )
            break
        except Exception as e:
            last_exc = e
            log_event(
                "broker_request",
                f"unexpected_error request_id={request_id} url={url} err={e}",
                level="error",
            )
            break

    # Exhausted retries or error
    raise last_exc if last_exc else RuntimeError("safe_request failed without explicit exception")

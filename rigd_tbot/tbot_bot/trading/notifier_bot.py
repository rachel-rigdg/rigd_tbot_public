# tbot_bot/trading/notifier_bot.py
# Alerts via email or Slack/SMS/PagerDuty with TEST_MODE suppression

"""
Handles notifications for trade fills, exits, and critical errors.
Uses SMTP (email) and optional Slack/PagerDuty/SMS settings from env/config.
Suppresses non-critical notifications when TEST_MODE is active.
"""

import smtplib
from email.mime.text import MIMEText
from pathlib import Path

import json
import base64
import requests

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now

config = get_bot_config()

# --- Email (SMTP) ---
SMTP_USER = config.get("SMTP_USER")
SMTP_PASS = config.get("SMTP_PASS")
SMTP_HOST = config.get("SMTP_HOST", "localhost")
SMTP_PORT = int(config.get("SMTP_PORT", 25))
ALERT_EMAIL = config.get("ALERT_EMAIL")

# Feature toggles
NOTIFY_ON_FILL = bool(config.get("NOTIFY_ON_FILL", False))
NOTIFY_ON_EXIT = bool(config.get("NOTIFY_ON_EXIT", False))

# --- Optional Slack webhook ---
SLACK_WEBHOOK_URL = config.get("SLACK_WEBHOOK_URL")

# --- Optional PagerDuty Events v2 ---
PAGERDUTY_ROUTING_KEY = config.get("PAGERDUTY_ROUTING_KEY")  # Integration key

# --- Optional Twilio SMS ---
TWILIO_ACCOUNT_SID = config.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = config.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = config.get("TWILIO_FROM_NUMBER")
ALERT_PHONE = config.get("ALERT_PHONE")  # destination phone number

# --- TEST_MODE flag file ---
CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def is_test_mode_active() -> bool:
    return TEST_MODE_FLAG.exists()


def _notify_guard(override: bool = False) -> bool:
    """
    Returns False when TEST_MODE is active and override is not set.
    Use override=True only for critical, non-suppressible alerts.
    """
    if is_test_mode_active() and not override:
        return False
    return True


# ---------------------------
# Delivery channels
# ---------------------------

def send_email(subject: str, message: str, override: bool = False):
    """Send an email via SMTP if enabled or override is set; suppressed in TEST_MODE unless override."""
    if not _notify_guard(override):
        return
    if not ALERT_EMAIL:
        return
    if not override and not (NOTIFY_ON_FILL or NOTIFY_ON_EXIT):
        return
    if not (SMTP_USER and SMTP_PASS and SMTP_HOST and SMTP_PORT):
        return

    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            try:
                server.starttls()
            except Exception:
                # If TLS not supported, continue without it
                pass
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())
    except Exception as e:
        print(f"[notifier_bot] Failed to send email: {e}")


def send_slack(subject: str, message: str, override: bool = False):
    """Post to Slack webhook if configured; suppressed in TEST_MODE unless override."""
    if not _notify_guard(override):
        return
    if not SLACK_WEBHOOK_URL:
        return
    payload = {"text": f"*{subject}*\n{message}"}
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[notifier_bot] Failed to send Slack message: {e}")


def send_pagerduty_event(summary: str, severity: str = "error", source: str = "tbot", override: bool = False):
    """Send PagerDuty Events v2 trigger; suppressed in TEST_MODE unless override."""
    if not _notify_guard(override):
        return
    if not PAGERDUTY_ROUTING_KEY:
        return

    url = "https://events.pagerduty.com/v2/enqueue"
    payload = {
        "routing_key": PAGERDUTY_ROUTING_KEY,
        "event_action": "trigger",
        "payload": {
            "summary": summary,
            "source": source,
            "severity": severity,
            "timestamp": utc_now().isoformat(),
        },
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[notifier_bot] Failed to send PagerDuty event: {e}")


def send_sms(message: str, to_number: str = None, override: bool = False):
    """Send SMS via Twilio if configured; suppressed in TEST_MODE unless override."""
    if not _notify_guard(override):
        return
    to = to_number or ALERT_PHONE
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER and to):
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "From": TWILIO_FROM_NUMBER,
        "To": to,
        "Body": message,
    }
    try:
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        requests.post(url, data=data, auth=auth, timeout=5)
    except Exception as e:
        print(f"[notifier_bot] Failed to send SMS: {e}")


# ---------------------------
# Public notification helpers
# ---------------------------

def notify_trade_fill(ticker, side, size, price, strategy, broker):
    """Notify when a trade is filled (suppressed in TEST_MODE)."""
    if is_test_mode_active():
        return
    if not NOTIFY_ON_FILL:
        return
    subject = f"TradeBot Fill Alert - {ticker}"
    body = (
        f"Trade Filled:\n"
        f"Time: {utc_now().isoformat()}\n"
        f"Strategy: {strategy}\n"
        f"Ticker: {ticker}\n"
        f"Side: {side}\n"
        f"Size: {size}\n"
        f"Entry Price: {price}\n"
        f"Broker: {broker}"
    )
    send_email(subject, body, override=False)
    send_slack(subject, body, override=False)


def notify_trade_exit(ticker, size, entry_price, exit_price, pnl, strategy, broker):
    """Notify when a trade is exited (suppressed in TEST_MODE)."""
    if is_test_mode_active():
        return
    if not NOTIFY_ON_EXIT:
        return
    subject = f"TradeBot Exit Alert - {ticker}"
    body = (
        f"Trade Closed:\n"
        f"Time: {utc_now().isoformat()}\n"
        f"Strategy: {strategy}\n"
        f"Ticker: {ticker}\n"
        f"Size: {size}\n"
        f"Entry Price: {entry_price}\n"
        f"Exit Price: {exit_price}\n"
        f"P&L: {pnl}\n"
        f"Broker: {broker}"
    )
    send_email(subject, body, override=False)
    send_slack(subject, body, override=False)


def notify_critical_error(summary, detail):
    """
    Send high priority alerts for critical failure.
    Critical notifications are allowed even in TEST_MODE (override=True).
    """
    subject = f"TradeBot ERROR - {summary}"
    body = (
        f"A critical error occurred:\n\n"
        f"{summary}\n\n"
        f"Details:\n{detail}\n\n"
        f"Time: {utc_now().isoformat()}"
    )
    # Always send critical errors (override=True)
    send_email(subject, body, override=True)
    send_slack(subject, body, override=True)
    # Optional: escalate to PagerDuty as well
    send_pagerduty_event(summary=summary, severity="error", source="tbot", override=True)

# tbot_bot/trading/notifier_bot.py
# Alerts via email or Slack

"""
Handles email alerts for trade fills, exits, and critical errors.
Uses SMTP settings from .env_bot or equivalent secure config.
"""

import smtplib
from email.mime.text import MIMEText
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from pathlib import Path

config = get_bot_config()
SMTP_USER = config.get("SMTP_USER")
SMTP_PASS = config.get("SMTP_PASS")
SMTP_HOST = config.get("SMTP_HOST", "localhost")
SMTP_PORT = int(config.get("SMTP_PORT", 25))
ALERT_EMAIL = config.get("ALERT_EMAIL")
NOTIFY_ON_FILL = config.get("NOTIFY_ON_FILL", False)
NOTIFY_ON_EXIT = config.get("NOTIFY_ON_EXIT", False)

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def send_email(subject, message, override=False):
    """Send an email via SMTP if enabled or override is set, suppress if TEST_MODE active"""
    if is_test_mode_active() and not override:
        # Suppress non-critical notifications during TEST_MODE
        return
    if not ALERT_EMAIL or (not override and not (NOTIFY_ON_FILL or NOTIFY_ON_EXIT)):
        return

    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = ALERT_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())
    except Exception as e:
        print(f"[notifier_bot] Failed to send email: {e}")

def notify_trade_fill(ticker, side, size, price, strategy, broker):
    """Notify when a trade is filled"""
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
    send_email(subject, body)

def notify_trade_exit(ticker, size, entry_price, exit_price, pnl, strategy, broker):
    """Notify when a trade is exited"""
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
    send_email(subject, body)

def notify_critical_error(summary, detail):
    """Send high priority email alert for critical failure"""
    subject = f"TradeBot ERROR - {summary}"
    body = (
        f"A critical error occurred:\n\n"
        f"{summary}\n\n"
        f"Details:\n{detail}\n\n"
        f"Time: {utc_now().isoformat()}"
    )
    # Always send critical errors even in TEST_MODE
    send_email(subject, body, override=True)

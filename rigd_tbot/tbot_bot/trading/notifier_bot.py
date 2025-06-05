# tbot_bot/trading/notifier_bot.py
# Alerts via email or Slack

"""
Handles email alerts for trade fills, exits, and critical errors.
Uses SMTP settings from .env_bot or equivalent secure config.
"""

import smtplib
from email.mime.text import MIMEText
from tbot_bot.config.env_bot import env_config
from tbot_bot.support.utils_time import utc_now

# Load config from env_config (single-broker identity enforced)
SMTP_USER = env_config.get("SMTP_USER")
SMTP_PASS = env_config.get("SMTP_PASS")
SMTP_HOST = env_config.get("SMTP_HOST", "localhost")
SMTP_PORT = int(env_config.get("SMTP_PORT", 25))
ALERT_EMAIL = env_config.get("ALERT_EMAIL")
NOTIFY_ON_FILL = env_config.get("NOTIFY_ON_FILL", False)
NOTIFY_ON_EXIT = env_config.get("NOTIFY_ON_EXIT", False)

def send_email(subject, message, override=False):
    """Send an email via SMTP if enabled or override is set"""
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
    if not NOTIFY_ON_FILL:
        return
    subject = f"TradeBot Fill Alert - {ticker}"
    # Mode is unified now; no live/paper dichotomy
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
    send_email(subject, body, override=True)

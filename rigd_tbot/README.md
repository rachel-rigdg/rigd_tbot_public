# TradeBot v1.0.0

README.md – System Overview and Developer Reference

Overview:
TradeBot is a modular, headless trading automation engine designed for high-speed intraday trade execution, real-time risk enforcement, and audit-compliant reporting via GnuCash. It supports long equity, inverse ETFs, and long put options. Strategies include Opening Range Breakout, VWAP Mean Reversion, and EOD Momentum/Fade.

Core Components:
- tbot_bot/ – Main runtime logic and broker execution
- tbot_api/ – FastAPI server for remote config and control
- tbot_web/ – Optional HTML frontend for live monitoring
- logs/, backups/, and GnuCash ledgers for traceability

---

Quick Start (Paper Mode Only)

1. Install Dependencies:
   pip install -r requirements.txt

2. Configure .env and .env_bot with your credentials and parameters

3. Encrypt your .env_bot:
   python tbot_bot/security_bot.py encrypt

4. Run a paper session:
   python tbot_bot/start_bot.py

5. Monitor logs in logs/bot/paper/
   View export in gnu_paper.gnucash

---

Live Trading Mode

1. In .env_bot:
   - Set TEST_MODE=false
   - Set ALPACA_MODE=live or IBKR_MODE=live
   - Ensure FORCE_PAPER_EXPORT=false

2. Confirm API credentials are valid and risk settings are configured

3. Start the bot:
   python tbot_bot/start_bot.py

4. Outputs go to:
   - logs/bot/live/
   - gnu_live.gnucash
   - daily_summary_live.json

---

Web Dashboard (Optional)

1. Launch API Server:
   uvicorn tbot_api.main_api:app --host 0.0.0.0 --port 6900 --reload

2. Visit in browser:
   http://localhost:6900/index.html

3. Use AES-encrypted login credentials from .env

---

Configuration Files

.env:
- Broker keys
- Finnhub API
- SMTP settings
- Encryption key

.env_bot:
- Strategy logic
- Trade timing
- Capital allocation
- Risk limits
- Logging and mode control

Encrypted:
- Run security_bot.py to encrypt/decrypt .env_bot

---

File Output Summary

Paper Mode:
- open_paper.log
- mid_paper.log
- close_paper.log
- trade_history_paper.csv / .json
- daily_summary_paper.json
- gnu_paper.gnucash

Live Mode:
- open_live.log
- mid_live.log
- close_live.log
- trade_history_live.csv / .json
- daily_summary_live.json
- gnu_live.gnucash

---

Key Features

- Broker Support: Alpaca, IBKR (live + paper)
- Strategy Modules: open, mid, close (toggle independently)
- Risk Management: stop-loss, allocation caps, daily loss limits
- Trade Direction: long and bearish (put/ETF)
- Log Format: JSON or CSV (configurable)
- Failover: kill switch, error handler, watchdog
- GnuCash: double-entry exports with backups
- Enhancements: ADX, Bollinger, VIX, imbalance scanner
- Test Mode: safe API-only test of entire system
- Web UI: optional control and monitoring interface
- Backtesting: fully compatible with strategy logic

---

Testing & Validation

1. Run Unit Tests:
   pytest tbot_bot/tests/

2. Confirm integration:
   python tbot_bot/tests/integration_test_runner.py

3. Verify:
   - Paper trade logs
   - GnuCash export
   - No errors or invalid trades

---

Security Best Practices

- Always encrypt .env_bot before deployment
- Exclude .env, .env_bot, and *.gnucash from git/SCP
- Never write to gnu_live.gnucash while TEST_MODE=true
- Use FORCE_PAPER_EXPORT=true to test live trades safely
- Use GNC_EXPORT_MODE=auto for automatic ledger writes

---

Supported Assets

- Long equity (Alpaca, IBKR)
- Inverse ETFs (all brokers)
- Long puts (IBKR only)
- Shorting disabled unless explicitly configured

---

Compatible Platforms

- macOS 15.2+
- Ubuntu 22.04 LTS (DigitalOcean)
- Python 3.11+
- FastAPI, Uvicorn, Pydantic, requests, cryptography

---

Version

VERSION=v1.0.0
See VERSION.md for full changelog

---

License

© 2025 Knetoscope Inc. Internal use only. All rights reserved.

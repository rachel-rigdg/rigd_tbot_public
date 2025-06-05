# VERSION.md — TradeBot v1.0.0

---

## Version Tag: `v1.0.0`
### Build Date: 2025-04-17

---

## Summary

This release marks the **first full production deployment** of TradeBot: a modular, intraday, bi-directional trading system that supports real-money execution, full logging, and automated accounting via GnuCash.

This version is fully operational on a local machine or cloud server (e.g., DigitalOcean), and has been structured to support long-term expansion into international markets with isolated, ledger-specific instances.

---

## Major Features

- Real-time intraday strategies:
  - `strategy_open.py`: Opening Range Breakout
  - `strategy_mid.py`: VWAP Mean Reversion
  - `strategy_close.py`: EOD Momentum or Fade
- Broker support:
  - Alpaca (stocks, ETFs, paper/live)
  - IBKR (stocks, long puts, inverse ETFs, paper/live)
- Strategy-specific routing and timing from `.env_bot`
- Dynamic ticker screening via Finnhub API
- GnuCash integration with:
  - Auto XML ledger exports
  - Structured COA for equity, puts, inverse ETFs
  - Ledger backup system (`gnu_backup.py`)
- Modular safety systems:
  - Kill switch (`kill_switch.py`)
  - API watchdog (`watchdog_bot.py`)
  - Real-time risk evaluation (`risk_bot.py`)
  - Global error capture (`error_handler.py`)
- Flask-secured web portal (`tbot_web/`):
  - View-only logs, runtime state, and control buttons (start/stop/kill)
  - Encrypted login using AES/bcrypt
  - Live dashboard metrics streamed via status module
- Full paper/live mode isolation:
  - TEST_MODE and FORCE_PAPER_EXPORT support
  - No bleed-through into live ledgers during testing
- Fully self-contained bot logic:
  - `tbot_bot/` requires no active connection to UI or web interface
  - Runs independently via cron, CLI, or supervisor
- Audit-ready structure:
  - All trades logged to `.csv`, `.json`, `.log`
  - All variables validated at runtime
  - `.env_bot.enc` support for encrypted deployment
- Testing framework (`tbot_bot/tests/`) with full integration dry-run

---

## Architectural Highlights

- **Modular directory structure** with strict separation of concerns
- **No external web triggers**—all trading logic resides in `tbot_bot/`
- Web dashboard uses **Flask only**; no FastAPI or backend API required
- Configurability and future international expansion baked into system

---

## Future Roadmap (`v1.1.x` Series)

- Real-time PnL metrics in web dashboard
- Slack/webhook alerting system
- Docker + cron bootstrap support (`run.sh`)
- Market-by-market bot replication (e.g., LSE, TSE)
- Auto-generated local accounting exports for international compliance

---

## Notes

- Strategy configuration, broker toggles, and trade filters are governed exclusively by `.env_bot`.
- `.env` contains API keys, encryption secrets, and SMTP login for alerts.
- All logs, ledgers, and summary files route to `/logs/`, `/backups/`, and the active runtime folders (`/tbot_bot/`).
- No platform-specific code; supports macOS and Linux.


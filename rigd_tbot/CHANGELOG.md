# CHANGELOG.md — TradeBot v1.x Development Log

---

## v1.0.0 – Initial Production Build (2025-04-17)

### Core Features:
- Added all three primary strategies:
  - Opening Range Breakout (`strategy_open.py`)
  - VWAP Mean Reversion (`strategy_mid.py`)
  - End-of-Day Momentum/Fade (`strategy_close.py`)
- Broker support:
  - Alpaca (stocks, ETFs, live/paper)
  - IBKR (stocks, long puts, inverse ETFs, live/paper)
- `.env_bot` parser (`env_bot.py`) with full validation and runtime enforcement
- Finnhub screener integration for dynamic ticker selection
- Risk control:
  - Max risk per trade
  - Max daily loss enforcement
  - Trailing stop-loss
  - Position size management
- Safety systems:
  - Kill switch
  - API watchdog
  - Global error handler
- Logging:
  - JSON and CSV formats
  - Paper/live separation
  - Session summary exports
- GnuCash integration:
  - XML ledger exports
  - Encrypted ledger files
  - Timestamped backups

### UI and Control:
- Web dashboard (`tbot_web/`) implemented using Flask
  - View-only metrics and logs
  - Manual control buttons for start, stop, kill
  - Secured login with bcrypt+AES encryption
- FastAPI removed (`tbot_api/` deprecated)

### DevOps and Compliance:
- `.scpignore` profile for secure server deployment
- Dual-ledger architecture for live/paper tracking
- `setup_tradebot.py` and `setup_server.sh` scripts
- Audit-ready logging and ledger separation
- VERSION and CHANGELOG files introduced


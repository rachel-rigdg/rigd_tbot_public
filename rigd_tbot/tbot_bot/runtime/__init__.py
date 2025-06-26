# tbot_bot/runtime/__init__.py
# Runtime package initialization for TradeBot.
# All persistent process supervision and phase orchestration is managed by tbot_supervisor.py,
# launched only by main.py after successful configuration/provisioning via the Web UI.
# No watcher, worker, or test runner in this package may be launched directly or by CLI.
# All process entry must occur via tbot_supervisor.py (see project specification v045).

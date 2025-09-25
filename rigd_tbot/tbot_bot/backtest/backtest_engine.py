# tbot_bot/backtest/backtest_engine.py
# Core simulator to replay past trades

# ------------------------------------
# Backtesting engine for TradeBot strategies.
# Simulates historical trades using OHLCV data and current strategy logic.
# Produces trade logs and summary outputs in backtest mode.

import os
import json
import argparse
from datetime import datetime, timezone
import pandas as pd

from tbot_bot.backtest.load_historical_data import load_data
from tbot_bot.backtest.performance_metrics import calculate_metrics
from tbot_bot.backtest.plot_results import plot_equity_curve
from tbot_bot.config.env_bot import get_bot_config

from tbot_bot.strategy.strategy_open import simulate_open
from tbot_bot.strategy.strategy_mid import simulate_mid
from tbot_bot.strategy.strategy_close import simulate_close

# Output folder for backtest results
BACKTEST_DIR = "tbot_bot/backtest/results"
os.makedirs(BACKTEST_DIR, exist_ok=True)

# Map strategies to their simulation entry points
STRATEGY_SIMULATORS = {
    "open": simulate_open,
    "mid": simulate_mid,
    "close": simulate_close
}

def backtest(strategy: str, data_path: str, start_date: str, end_date: str):
    if strategy not in STRATEGY_SIMULATORS:
        raise ValueError(f"[backtest_engine] Unknown strategy: {strategy}")

    # Load OHLCV historical data
    df = load_data(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)].copy()

    if df.empty:
        raise ValueError("[backtest_engine] No data in selected range.")

    print(f"[backtest_engine] Running backtest for {strategy} strategy...")
    simulate_func = STRATEGY_SIMULATORS[strategy]
    config = get_bot_config()
    trades = simulate_func(df, config)

    # Output log file
    timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"{strategy}_backtest_{timestamp}"

    trades_json = os.path.join(BACKTEST_DIR, f"trade_history_{base_name}.json")
    trades_csv = os.path.join(BACKTEST_DIR, f"trade_history_{base_name}.csv")
    summary_json = os.path.join(BACKTEST_DIR, f"daily_summary_{base_name}.json")

    pd.DataFrame(trades).to_csv(trades_csv, index=False)
    with open(trades_json, "w") as f_json:
        json.dump(trades, f_json, indent=2)

    summary = calculate_metrics(trades)
    with open(summary_json, "w") as f_summary:
        json.dump(summary, f_summary, indent=2)

    print(f"[backtest_engine] Backtest complete. Logs saved to:")
    print(f"  - {trades_csv}")
    print(f"  - {trades_json}")
    print(f"  - {summary_json}")

    plot_equity_curve(trades, title=f"{strategy.capitalize()} Strategy")

# ---- surgical: provide the expected public API name used by tests ----
def run_backtest(strategy: str, data_path: str, start_date: str, end_date: str):
    """
    Thin wrapper kept for test compatibility.
    """
    return backtest(strategy=strategy, data_path=data_path, start_date=start_date, end_date=end_date)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeBot Backtest Engine")
    parser.add_argument("--strategy", required=True, choices=["open", "mid", "close"], help="Which strategy to test")
    parser.add_argument("--data", required=True, help="Path to historical OHLCV CSV file")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    backtest(
        strategy=args.strategy,
        data_path=args.data,
        start_date=args.start,
        end_date=args.end
    )

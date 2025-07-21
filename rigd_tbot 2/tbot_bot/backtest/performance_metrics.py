# tbot_bot/backtest/performance_metrics.py
# Computes performance metrics for backtest results - Sharpe, win %, drawdown, etc.

import pandas as pd
import numpy as np

def calculate_metrics(trades: pd.DataFrame) -> dict:
    """
    Computes standard performance metrics from trade history.

    Args:
        trades (pd.DataFrame): Trade history with columns:
            - entry_price
            - exit_price
            - PnL
            - timestamp (datetime)
            - strategy_name

    Returns:
        dict: Dictionary of performance metrics.
    """
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0
        }

    total_trades = len(trades)
    wins = trades[trades["PnL"] > 0]
    losses = trades[trades["PnL"] < 0]

    win_rate = len(wins) / total_trades if total_trades else 0.0
    avg_pnl = trades["PnL"].mean()

    # Equity curve for drawdown
    trades = trades.sort_values("timestamp").reset_index(drop=True)
    trades["cumulative_pnl"] = trades["PnL"].cumsum()
    peak = trades["cumulative_pnl"].cummax()
    drawdown = peak - trades["cumulative_pnl"]
    max_drawdown = drawdown.max()

    # Sharpe Ratio (assuming 0% risk-free rate and daily trades)
    returns = trades["PnL"]
    sharpe_ratio = (
        returns.mean() / returns.std() * np.sqrt(252)
        if returns.std() > 0 else 0.0
    )

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 4),
        "max_drawdown": round(max_drawdown, 4),
        "sharpe_ratio": round(sharpe_ratio, 4)
    }

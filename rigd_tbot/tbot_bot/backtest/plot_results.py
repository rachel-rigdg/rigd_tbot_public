# tbot_bot/backtest/plot_results.py
# Graphs equity curves, trades, and heatmaps
# ---------------------------------
# Generates equity curve and trade distribution plots for backtest analysis.

import matplotlib.pyplot as plt
import pandas as pd

def plot_equity_curve(trades: pd.DataFrame, title: str = "Equity Curve"):
    """
    Plots the cumulative PnL (equity curve) from trade history.

    Args:
        trades (pd.DataFrame): Trade history with at least:
            - timestamp (datetime)
            - PnL (float)
        title (str): Title of the chart
    """
    if trades.empty:
        print("[plot_results] No trade data to plot.")
        return

    trades = trades.sort_values("timestamp").reset_index(drop=True)
    trades["cumulative_pnl"] = trades["PnL"].cumsum()

    plt.figure(figsize=(12, 6))
    plt.plot(trades["timestamp"], trades["cumulative_pnl"], label="Cumulative PnL")
    plt.xlabel("Timestamp (UTC)")
    plt.ylabel("Cumulative PnL")
    plt.title(title)
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

def plot_trade_distribution(trades: pd.DataFrame):
    """
    Plots histogram of trade PnL distribution.

    Args:
        trades (pd.DataFrame): Trade history with "PnL" column
    """
    if trades.empty:
        print("[plot_results] No trade data to plot.")
        return

    plt.figure(figsize=(10, 5))
    plt.hist(trades["PnL"], bins=30, edgecolor="black")
    plt.title("Trade PnL Distribution")
    plt.xlabel("PnL")
    plt.ylabel("Frequency")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

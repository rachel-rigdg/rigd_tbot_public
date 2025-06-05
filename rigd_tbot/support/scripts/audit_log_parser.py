# scripts/audit_log_parser.py
# CLI utility to review logs and summarize behavior

import argparse
import json
import os
from datetime import datetime


def load_json_file(path):
    """Load a JSON log file into memory"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def summarize_trade_history(log_data):
    """Summarize trade history for audit or dashboard"""
    summary = {
        "total_trades": len(log_data),
        "winning_trades": 0,
        "losing_trades": 0,
        "total_pnl": 0.0,
        "most_profitable": None,
        "least_profitable": None,
        "tickers_traded": set(),
        "brokers": set(),
    }

    max_profit = float("-inf")
    max_loss = float("inf")

    for entry in log_data:
        pnl = entry.get("PnL", 0.0)
        ticker = entry.get("ticker", "N/A")
        broker = entry.get("broker", "N/A")
        summary["total_pnl"] += pnl
        summary["tickers_traded"].add(ticker)
        summary["brokers"].add(broker)

        if pnl >= 0:
            summary["winning_trades"] += 1
        else:
            summary["losing_trades"] += 1

        if pnl > max_profit:
            summary["most_profitable"] = entry
            max_profit = pnl

        if pnl < max_loss:
            summary["least_profitable"] = entry
            max_loss = pnl

    summary["tickers_traded"] = list(summary["tickers_traded"])
    summary["brokers"] = list(summary["brokers"])
    return summary


def print_summary(summary):
    """Print a summarized report to stdout"""
    print("\n=== Trade Summary ===")
    print(f"Total Trades:        {summary['total_trades']}")
    print(f"Winners:             {summary['winning_trades']}")
    print(f"Losers:              {summary['losing_trades']}")
    print(f"Total PnL:           {summary['total_pnl']:.2f}")
    print(f"Tickers Traded:      {', '.join(summary['tickers_traded'])}")
    print(f"Brokers Used:        {', '.join(summary['brokers'])}")

    if summary["most_profitable"]:
        mp = summary["most_profitable"]
        print(f"\nMost Profitable Trade: {mp['ticker']} | PnL: {mp['PnL']:.2f} | Strategy: {mp['strategy_name']}")

    if summary["least_profitable"]:
        lp = summary["least_profitable"]
        print(f"Least Profitable Trade: {lp['ticker']} | PnL: {lp['PnL']:.2f} | Strategy: {lp['strategy_name']}")


def main():
    parser = argparse.ArgumentParser(description="Parse and summarize TradeBot audit logs.")
    parser.add_argument("--file", required=True, help="Path to trade_history JSON file (e.g., trade_history_live.json)")
    args = parser.parse_args()

    try:
        data = load_json_file(args.file)
        summary = summarize_trade_history(data)
        print_summary(summary)
    except Exception as e:
        print(f"[ERROR] {str(e)}")


if __name__ == "__main__":
    main()

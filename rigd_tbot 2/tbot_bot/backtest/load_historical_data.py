# tbot_bot/backtest/load_historical_data.py
# Load from CSV, OHLCV, or tick sources
# -----------------------------------------
# Loads and normalizes OHLCV data for use in backtest simulations.

import pandas as pd

def load_data(filepath: str) -> pd.DataFrame:
    """
    Loads OHLCV data from a CSV file and returns a normalized DataFrame.

    Required columns: timestamp, open, high, low, close, volume

    Args:
        filepath (str): Path to the historical data CSV file.

    Returns:
        pd.DataFrame: Parsed and normalized OHLCV data.
    """
    try:
        df = pd.read_csv(filepath)

        required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"[load_historical_data] Missing required columns: {missing}")

        # Normalize and sanitize
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

        df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        return df

    except Exception as e:
        raise RuntimeError(f"[load_historical_data] Failed to load or parse file: {filepath}\n{e}")

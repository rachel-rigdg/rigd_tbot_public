# tbot_bot/screeners/providers/nyse_provider.py
# NYSE provider adapter: fetches NYSE symbols and quotes via IBKR using credentials from secrets_manager.
# Fully self-contained: pulls credentials, authenticates, fetches, returns.

from typing import List, Dict
from ib_insync import IB, Stock
from tbot_bot.support.secrets_manager import get_provider_credentials

def _make_ibkr_client() -> IB:
    """
    Loads IBKR credentials from the central secrets manager and returns an authenticated IB instance.
    Fails fast if credentials are missing or connection fails.
    """
    creds = get_provider_credentials("IBKR")
    if not creds:
        raise RuntimeError("[nyse_provider] Missing IBKR credentials in secrets_manager.")
    ibkr = IB()
    ibkr.connect(
        creds["BROKER_HOST"],
        int(creds["BROKER_PORT"]),
        clientId=int(creds.get("BROKER_CLIENT_ID", 1))
    )
    return ibkr

def fetch_nyse_symbols_ibkr() -> List[Dict]:
    """
    Fetches all NYSE-listed equity symbols from IBKR using credentials from secrets manager.
    Returns a list of dicts: [{symbol, exchange, companyName}]
    """
    ibkr_client = _make_ibkr_client()
    contracts = ibkr_client.reqMatchingSymbols('NYSE')
    syms = []
    for con in contracts:
        contract = getattr(con, 'contract', None)
        if contract and getattr(contract, 'exchange', '') == 'NYSE' and getattr(contract, 'symbol', None):
            syms.append({
                "symbol": contract.symbol,
                "exchange": "NYSE",
                "companyName": getattr(contract, 'localSymbol', "") or ""
            })
    ibkr_client.disconnect()
    return syms

def fetch_nyse_quote_ibkr(symbol: str) -> Dict:
    """
    Fetches live quote data for a given NYSE symbol from IBKR using credentials from secrets manager.
    Returns dict: {symbol, c, o, vwap}
    """
    ibkr_client = _make_ibkr_client()
    contract = Stock(symbol, "NYSE", "USD")
    ticker = ibkr_client.reqMktData(contract, "", False, False)
    ibkr_client.sleep(2)  # Wait for market data to populate
    result = {
        "symbol": symbol,
        "c": float(getattr(ticker, 'last', 0) or 0),
        "o": float(getattr(ticker, 'open', 0) or 0),
        "vwap": float(getattr(ticker, 'vwap', 0) or 0)
    }
    ibkr_client.disconnect()
    return result

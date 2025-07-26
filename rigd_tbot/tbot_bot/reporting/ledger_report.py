# tbot_bot/reporting/ledger_report.py
# Grouped row reporting, summary/expand logic for double-entry trades.

from tbot_bot.accounting.ledger_modules.ledger_query import fetch_trades_by_group, fetch_grouped_trades_summary

def get_grouped_ledger_report(expand_group_ids=None):
    """
    Returns a list of grouped ledger rows for reporting.
    expand_group_ids: set of group_ids to expand (show full double-entry detail), otherwise show summary row only.
    """
    if expand_group_ids is None:
        expand_group_ids = set()
    report_rows = []
    grouped = fetch_grouped_trades_summary()
    for group in grouped:
        group_id = group["group_id"]
        summary_row = {
            "group_id": group_id,
            "trade_id": group["trade_id"],
            "datetime_utc": group["datetime_utc"],
            "symbol": group["symbol"],
            "action": group["action"],
            "quantity": group["quantity"],
            "price": group["price"],
            "fee": group["fee"],
            "total_value": group["total_value"],
            "status": group["status"],
            "running_balance": group.get("running_balance"),
            "collapsed": group_id not in expand_group_ids
        }
        report_rows.append(summary_row)
        if group_id in expand_group_ids:
            trades = fetch_trades_by_group(group_id)
            for t in trades:
                detail_row = dict(t)
                detail_row["group_id"] = group_id
                detail_row["expanded"] = True
                report_rows.append(detail_row)
    return report_rows

def get_ledger_summary_totals():
    """
    Returns aggregate totals for reporting: sums of quantity, total_value, fees, by action, symbol, etc.
    """
    grouped = fetch_grouped_trades_summary()
    summary = {}
    for group in grouped:
        symbol = group["symbol"]
        if symbol not in summary:
            summary[symbol] = {"quantity": 0, "total_value": 0, "fee": 0}
        summary[symbol]["quantity"] += group.get("quantity", 0) or 0
        summary[symbol]["total_value"] += group.get("total_value", 0) or 0
        summary[symbol]["fee"] += group.get("fee", 0) or 0
    return summary

def get_trade_details(trade_id):
    """
    Returns both entries (debit/credit) for a specific trade_id.
    """
    return fetch_trades_by_group(trade_id)

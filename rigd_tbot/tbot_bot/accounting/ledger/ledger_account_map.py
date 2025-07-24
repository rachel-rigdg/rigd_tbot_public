# tbot_bot/accounting/ledger/ledger_account_map.py

ACCOUNT_MAP = {
    "cash":               "Assets:Brokerage Accounts – Equities:Cash",
    "equity":             "Assets:Brokerage Accounts – Equities",
    "gain":               "Income:Realized Gains",
    "fee":                "Expenses:Broker fee",
    "slippage":           "Expenses:Slippage / Execution Losses",
    "failures":           "System Integrity:Failures & Rejected Orders",
    "infra":              "Expenses:Bot Infrastructure Costs",
    "float_ledger":       "Equity:Capital Float Ledger",
    "float_history":      "Equity:Daily Float Allocation History",
    "retained":           "Equity:Accumulated Profit",
    "opening":            "Equity:Opening Balance",
    "meta_trade":         "Logging / Execution References:Trade UUID",
    "meta_strategy":      "Logging / Execution References:Strategy Tag",
    "meta_recon":         "Logging / Execution References:Reconciliation Passed Flag",
    "meta_lock":          "System Integrity:Ledger Lock Flag (YES/NO)"
}

def get_account_path(key):
    return ACCOUNT_MAP.get(key, "")

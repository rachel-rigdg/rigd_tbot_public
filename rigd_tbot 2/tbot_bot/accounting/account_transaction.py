# tbot_bot/accounting/account_transaction.py
# Builds accounting journal entries for trade export to accounting (never manages/provisions secrets/keys)

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

class AccountTransaction:
    """
    Represents a single accounting transaction entry with double-entry support.
    Used by all exporters (e.g., Manager.io) for consistent ledger generation.
    """

    def __init__(self, timestamp, description, debit_account, credit_account, amount, currency="USD", metadata=None):
        """
        Initializes a double-entry transaction.

        Args:
            timestamp (datetime): The timestamp of the transaction in UTC.
            description (str): Description for the transaction.
            debit_account (str): Full path to the debit account (e.g., 'Assets:Brokerage Accounts – Equities:Alpaca – Cash').
            credit_account (str): Full path to the credit account (e.g., 'Income:Realized Gains – Alpaca').
            amount (float or Decimal): Transaction amount (positive number).
            currency (str): ISO currency code (default = "USD").
            metadata (dict): Optional metadata (UUID, trade ID, strategy, etc.)
        """
        self.timestamp = (
            timestamp.astimezone(timezone.utc)
            if isinstance(timestamp, datetime)
            else datetime.utcnow().replace(tzinfo=timezone.utc)
        )
        self.description = description
        self.debit_account = debit_account
        self.credit_account = credit_account
        self.amount = Decimal(str(amount))
        self.currency = currency
        self.metadata = metadata if metadata else {}
        self.transaction_id = self.metadata.get("uuid", str(uuid4()))
        # Ensure transaction_id is always present in metadata for downstream integrity
        self.metadata["uuid"] = self.transaction_id

    def to_dict(self):
        """
        Returns a dictionary representation of the transaction for serialization.

        Returns:
            dict: Structured transaction data.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "debit_account": self.debit_account,
            "credit_account": self.credit_account,
            "amount": str(self.amount),
            "currency": self.currency,
            "metadata": self.metadata,
            "transaction_id": self.transaction_id
        }

    def __repr__(self):
        return f"<Txn {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | {self.amount} {self.currency} | {self.debit_account} ⇄ {self.credit_account}>"

================================================================================
RIGD TradeBot - Accounting & Ledger System Documentation
================================================================================

This module implements a full-featured, double-entry, audit-grade accounting ledger
for all trading operations, float, payroll, tax, and compliance actions.

-------------------------------------------------------------------------------
DIRECTORY OVERVIEW & MODULE ORGANIZATION
-------------------------------------------------------------------------------

tbot_bot/accounting/
│
├── account_transaction.py      # Core data structure for transactions
├── accounting_api.py           # API for dispatching to external accounting systems
├── accounting_config.py        # General accounting configuration
├── coa_mapping_table.py        # COA mapping rules, apply_mapping_rule, load_mapping_table
├── coa_utils.py                # COA utilities for validation and operations
├── init_coa_db.py              # COA DB initialization
├── init_ledger_db.py           # Ledger DB initialization (runs tbot_ledger_schema.sql)
├── reconciliation_log.py       # Reconciliation log for sync, audit, and matching
├── tbot_ledger_coa_template.json # Default COA template
├── tbot_ledger_schema.sql      # Full normalized ledger schema
├── README_COA.md               # COA design doc & reference
│
└── ledger/                     # Ledger core and helpers (ALL transaction ops)
    ├── ledger_account_map.py   # Account path/key helpers, broker/account loader, COA account fetch
    ├── ledger_audit.py         # Audit logging (audit_trail table), log_audit_event
    ├── ledger_balance.py       # Balance/running balance calculation
    ├── ledger_core.py          # (Reserved for low-level shared logic)
    ├── ledger_db.py            # Schema validation, connection, identity, schema checks
    ├── ledger_double_entry.py  # Double-entry posting, validation (debit/credit enforcement)
    ├── ledger_edit.py          # Entry editing, updating, deleting, resolving
    ├── ledger_entry.py         # Single-entry add/fetch, load_internal_ledger, entry retrieval
    ├── ledger_hooks.py         # Tax, payroll, float, rebalance entry hooks (special operations)
    ├── ledger_misc.py          # Miscellaneous/utility functions
    ├── ledger_snapshot.py      # Atomic ledger snapshot/rollback for sync or backup
    └── ledger_sync.py          # Orchestration for broker sync and posting

-------------------------------------------------------------------------------
KEY FUNCTIONALITY (BY MODULE)
-------------------------------------------------------------------------------

- **ledger_account_map.py:**  
  Loads broker/account identifiers, COA account keys, and logical account path lookups.

- **ledger_audit.py:**  
  Full audit log recording (writes to audit_trail for all edits, deletions, corrections, compliance).

- **ledger_balance.py:**  
  Computes per-account balances, running balances, and summary/aggregate values for reporting.

- **ledger_db.py:**  
  Enforces schema compliance, validates all required tables/fields, identity checks.

- **ledger_double_entry.py:**  
  True double-entry posting; posts debit/credit for each transaction, enforces balance,
  raises on imbalance or error.

- **ledger_edit.py:**  
  Updates, deletes, and resolves individual ledger entries (safe audit tracked).

- **ledger_entry.py:**  
  Handles entry creation (legacy or compat), bulk fetch, and load_internal_ledger.

- **ledger_hooks.py:**  
  Posting helpers for tax reserve, payroll reserve, float allocation, and rebalance
  (calls double-entry logic internally).

- **ledger_snapshot.py:**  
  Snapshots ledger db for rollback/backup before sync or destructive operations.

- **ledger_sync.py:**  
  Orchestrates sync with broker, posting all new transactions, mapping via COA, posting
  with full double-entry, and logging reconciliation.

-------------------------------------------------------------------------------
USAGE GUIDELINES
-------------------------------------------------------------------------------

- **ALL transaction posting should use `post_ledger_entries_double_entry`**  
  (single-entry legacy functions remain for compatibility only).

- **Editing or deleting entries must use ledger_edit.py functions**  
  (always audit-logged).

- **Balance and reconciliation always use the dedicated balance and reconciliation modules.**

- **All modules automatically load required config/identity from the encrypted secrets files.**

-------------------------------------------------------------------------------
INTEGRATION
-------------------------------------------------------------------------------

- UI and web routes should import specific helpers:
    - Posting entries:         from ledger.ledger_double_entry import post_double_entry
    - Audit logging:           from ledger.ledger_audit import log_audit_event
    - Schema validation:       from ledger.ledger_db import validate_ledger_schema
    - Entry edit/update/del:   from ledger.ledger_edit import edit_ledger_entry, delete_ledger_entry, mark_entry_resolved
    - Sync/reconciliation:     from ledger.ledger_sync import sync_broker_ledger

- Old imports from ledger_utils.py and ledger.py must be updated to new helpers.

-------------------------------------------------------------------------------
COMPLIANCE AND EXTENSIBILITY
-------------------------------------------------------------------------------

- **Every transaction, edit, and sync is fully double-entry, compliant, and audit-logged.**
- **Supports internationalization, compliance flags, and multi-jurisdiction logic.**
- **Easy to extend: drop in new modules or expand hooks as needed.**

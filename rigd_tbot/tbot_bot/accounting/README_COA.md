# README_COA.md

# Chart of Accounts (COA) – Human-Readable Documentation

This document summarizes the Chart of Accounts (COA) implementation, schema enforcement, update process, and UI-editing instructions for the RIGD TradeBot system. All information is fully aligned with the current specification and mandatory build rules.

---

## Overview

- The COA defines the account structure for all TradeBot-generated SQLite ledgers, ensuring OFX compliance, double-entry integrity, and audit traceability.
- COA management is self-contained within each bot instance; all creation, update, and export actions are strictly handled via the dedicated Web UI.
- All COA logic, validation, and schema enforcement utilize:
    - `tbot_bot/support/utils_coa_web.py` (Web UI/admin logic)
    - `tbot_bot/accounting/coa_utils_ledger.py` (ledger/schema integration)

---

## COA Metadata (Required Fields)

Each COA (in both JSON and SQLite/DB forms) must include the following metadata, as a dedicated table `coa_metadata`:

| Field            | Example         | Description                              |
|------------------|-----------------|------------------------------------------|
| currency_code    | "USD"           | Ledger/account currency                  |
| entity_code      | "RGL"           | Entity identifier                        |
| jurisdiction_code| "USA"           | Jurisdiction identifier                  |
| coa_version      | "v1.0.0"        | Version for migration/compatibility      |
| created_at_utc   | ISO 8601 string | Creation timestamp (UTC)                 |
| last_updated_utc | ISO 8601 string | Last update timestamp (UTC)              |

---

## COA Account Hierarchy (Example Structure)

See `tbot_bot/accounting/tbot_ledger_coa.json` for the full hierarchical account structure. Top-level categories include:

- **1000 Bank and Cash Accounts**
- **1100 Assets**
- **2000 Liabilities**
- **3000 Equity**
- **4000 Income**
- **5000 Expenses**
- **9100 Exports**
- **9200 Logging / Execution References**
- **9300 System Integrity**

All account codes, names, and hierarchy are version-controlled and validated at runtime.

---

## Schema Enforcement

- All ledger files **must** match the schema in `tbot_bot/accounting/tbot_ledger_schema.sql` and the account structure in `tbot_bot/accounting/tbot_ledger_coa.json`.
- Any mismatch or invalid COA structure detected by `utils_coa_web.py` or `coa_utils_ledger.py` will halt execution and log a fatal error.
- COA is stored and validated as both a JSON structure and an SQLite table (`coa_metadata`, `coa_accounts`).

---

## Update Process & Audit Log

1. **All COA edits must be performed via the Web UI at `/coa`**:
    - Accessible only to admin users (RBAC-enforced).
    - UI displays current COA, version, and change history.
2. **Edit Process**:
    - Click "Edit COA" (admin only).
    - Modify JSON (full structure) in the editor.
    - On submit, system validates structure using `utils_coa_web.py`.
    - Validated COA is saved, metadata updated, and a diff is recorded.
    - Full change history/audit log visible under "COA Change History".
3. **All changes are audit-logged**:
    - Includes UTC timestamp, user, summary, diff preview.
    - Log is capped (last 100 changes); full history exportable.

---

## Export and Reference

- Export current COA as **Markdown** or **CSV** for compliance/audit via Web UI buttons.
- Exports generated from live structure using `utils_coa_web.py` methods.
- No CLI or direct file editing is permitted.

---

## Compliance Notes

- **No COA changes are permitted via CLI, external scripts, or accounting system pushes.**
- COA is always local to the bot instance; changes never propagate automatically between bots or to accounting.
- All COA management must use the canonical modules and the Web UI as mandated above.

---

## Quick Reference

| Action          | Module                  | Interface / Path           |
|-----------------|------------------------|----------------------------|
| Load/validate   | utils_coa_web.py        | `/coa`, `/coa/api`         |
| Save/update     | utils_coa_web.py        | `/coa/edit` (admin only)   |
| Export MD/CSV   | utils_coa_web.py        | `/coa/export/markdown`<br>`/coa/export/csv` |
| Ledger schema   | coa_utils_ledger.py     | Ledger/DB enforcement      |
| Audit log       | utils_coa_web.py        | `/coa/api` (history)       |

---

*For full COA account definitions, see `tbot_bot/accounting/tbot_ledger_coa.json` and in-UI hierarchy display.*

*End of Document*

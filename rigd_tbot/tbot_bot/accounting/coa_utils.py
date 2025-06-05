# tbot_bot/accounting/coa_utils.py
# COA DB utilities: create/import/export/validate COA db (metadata + hierarchy), supports Web UI editing

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet

from tbot_bot.support.path_resolver import (
    resolve_coa_json_path,
    resolve_coa_metadata_path,
    resolve_coa_db_path,
    resolve_coa_template_path,
)

# --- Load COA Metadata and Accounts (from JSON and SQLite) ---
def load_coa_metadata() -> Dict[str, Any]:
    metadata_path = resolve_coa_metadata_path()
    if not os.path.exists(metadata_path):
        raise FileNotFoundError("COA metadata file not found.")
    with open(metadata_path, "r", encoding="utf-8") as mdf:
        return json.load(mdf)

def load_coa_accounts() -> List[Dict[str, Any]]:
    coa_json_path = resolve_coa_json_path()
    if not os.path.exists(coa_json_path):
        raise FileNotFoundError("COA JSON file not found.")
    with open(coa_json_path, "r", encoding="utf-8") as cf:
        return json.load(cf)

def _get_identity_from_secret():
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    return identity.split("_")

# --- Import COA from SQLite COA DB ---
def import_coa_from_db(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> Dict[str, Any]:
    if not all([entity_code, jurisdiction_code, broker_code, bot_id]):
        entity_code, jurisdiction_code, broker_code, bot_id = _get_identity_from_secret()
    db_path = resolve_coa_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not os.path.exists(db_path):
        raise FileNotFoundError("COA DB not found.")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT currency_code, entity_code, jurisdiction_code, coa_version, created_at_utc, last_updated_utc FROM coa_metadata LIMIT 1")
    meta_row = cur.fetchone()
    metadata = {
        "currency_code": meta_row[0],
        "entity_code": meta_row[1],
        "jurisdiction_code": meta_row[2],
        "coa_version": meta_row[3],
        "created_at_utc": meta_row[4],
        "last_updated_utc": meta_row[5],
    }
    cur.execute("SELECT account_json FROM coa_accounts ORDER BY id ASC")
    accounts = [json.loads(row[0]) for row in cur.fetchall()]
    conn.close()
    return {"metadata": metadata, "accounts": accounts}

# --- Export COA to Markdown (human-readable) ---
def export_coa_markdown(metadata: Dict[str, Any], accounts: List[Dict[str, Any]]) -> str:
    out = []
    out.append(f"# Chart of Accounts — {metadata.get('entity_code','')}/{metadata.get('jurisdiction_code','')} v{metadata.get('coa_version','')}")
    out.append(f"**Currency:** {metadata.get('currency_code','')}\n")
    out.append(f"**COA Version:** {metadata.get('coa_version','')}")
    out.append(f"**Created:** {metadata.get('created_at_utc','')}")
    out.append(f"**Last Updated:** {metadata.get('last_updated_utc','')}\n")
    def walk(accs, depth=0):
        for acc in accs:
            out.append(f"{'  '*depth}- **{acc['code']}**: {acc['name']}")
            if acc.get("children"):
                walk(acc["children"], depth+1)
    walk(accounts)
    return "\n".join(out)

# --- Export COA to CSV ---
def export_coa_csv(accounts: List[Dict[str, Any]]) -> str:
    rows = ["code,name,depth"]
    def walk(accs, depth=0):
        for acc in accs:
            rows.append(f"{acc['code']},{acc['name']},{depth}")
            if acc.get("children"):
                walk(acc["children"], depth+1)
    walk(accounts)
    return "\n".join(rows)

# --- Schema Check: Validate COA Table and Metadata in COA DB ---
def validate_coa_db_schema(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None) -> bool:
    if not all([entity_code, jurisdiction_code, broker_code, bot_id]):
        entity_code, jurisdiction_code, broker_code, bot_id = _get_identity_from_secret()
    db_path = resolve_coa_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    if not os.path.exists(db_path):
        raise FileNotFoundError("COA DB not found.")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for table in ("coa_metadata", "coa_accounts"):
        result = cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone()
        if not result:
            conn.close()
            raise RuntimeError(f"Required table '{table}' missing in COA DB: {db_path}")
    cur.execute("PRAGMA table_info(coa_metadata)")
    columns = {row[1] for row in cur.fetchall()}
    required_fields = {
        "currency_code", "entity_code", "jurisdiction_code",
        "coa_version", "created_at_utc", "last_updated_utc"
    }
    if not required_fields.issubset(columns):
        conn.close()
        raise RuntimeError(f"COA metadata schema missing required fields in COA DB: {db_path}")
    conn.close()
    return True

# --- Save COA to JSON and Metadata (for UI export) ---
def save_coa_json_and_metadata(accounts: List[Dict[str, Any]], metadata: Dict[str, Any]):
    coa_json_path = resolve_coa_json_path()
    coa_metadata_path = resolve_coa_metadata_path()
    with open(coa_json_path, "w", encoding="utf-8") as cf:
        json.dump(accounts, cf, indent=2)
    with open(coa_metadata_path, "w", encoding="utf-8") as mdf:
        json.dump(metadata, mdf, indent=2)

# --- Utility: UTC Now String ---
def utc_now() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

# --- Validate COA Structure ---
def validate_coa_structure(accounts: Any):
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("COA accounts must be a non-empty list.")
    def check(acc):
        if "code" not in acc or "name" not in acc:
            raise ValueError("Each account must have 'code' and 'name'.")
        if "children" in acc and not isinstance(acc["children"], list):
            raise ValueError("'children' must be a list if present.")
        for c in acc.get("children", []):
            check(c)
    for acc in accounts:
        check(acc)

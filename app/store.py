"""Read-only SQLite access; all data queries use bound parameters."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path


def database_path() -> Path:
    return Path(os.getenv('FG_DB_PATH', 'data/olist.db')).resolve()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path).resolve() if path else database_path()
    if not p.exists():
        raise FileNotFoundError(f"Database not found: {p}. Run scripts/load_olist.py or scripts/make_fixture.py")
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

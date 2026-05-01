"""
Lightweight SQLite cache for cv-optimizer.

What lives here today:
    parsed_cv   — cached PDF/DOCX → JSON parses, keyed by (file_hash,
                  parser_provider, parser_model). Idempotent: re-parsing
                  the same file with the same model returns instantly.

What can live here tomorrow (just add tables — `init_db` is idempotent
and safe to call any time):
    runs        — log of full optimization runs (cv, offer, score)
    offers      — cached offer text by URL hash
    embeddings  — vector embeddings for offer / CV similarity

DB lives at `.cvo/cache.db` (gitignored). Created automatically on first
use, but `cvo setup` also calls `init_db()` to make the bootstrap
explicit so users see a "Cache DB ready at: …" line.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DB_DIR = Path(".cvo")
DB_PATH = DB_DIR / "cache.db"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS parsed_cv (
    file_hash       TEXT NOT NULL,
    parser_provider TEXT NOT NULL,
    parser_model    TEXT NOT NULL,
    file_name       TEXT,
    file_kind       TEXT,
    parsed_json     TEXT NOT NULL,
    parsed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (file_hash, parser_provider, parser_model)
);

CREATE INDEX IF NOT EXISTS idx_parsed_cv_hash ON parsed_cv(file_hash);
"""


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(_SCHEMA_SQL)
    return conn


def init_db() -> Path:
    """
    Create the DB file and tables if missing. Idempotent.
    Returns the absolute path of the DB file.
    """
    with _connect() as conn:
        # _connect already runs the schema, but we reaffirm here so the
        # function is meaningful on its own.
        conn.executescript(_SCHEMA_SQL)
    return DB_PATH.resolve()


def hash_file(path: str | Path, chunk: int = 65536) -> str:
    """SHA-256 of file contents, hex-encoded."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def get_cached_parse(
    file_hash: str,
    parser_provider: str,
    parser_model: str,
) -> dict[str, Any] | None:
    """
    Return {'data': dict, 'parsed_at': str, 'file_name': str} if a cache
    hit exists, else None.
    """
    with _connect() as conn:
        row = conn.execute(
            """SELECT parsed_json, parsed_at, file_name
                 FROM parsed_cv
                WHERE file_hash = ? AND parser_provider = ? AND parser_model = ?""",
            (file_hash, parser_provider, parser_model),
        ).fetchone()
    if not row:
        return None
    parsed_json, parsed_at, file_name = row
    return {
        "data":      json.loads(parsed_json),
        "parsed_at": parsed_at,
        "file_name": file_name,
    }


def set_cached_parse(
    file_hash: str,
    parser_provider: str,
    parser_model: str,
    file_name: str,
    file_kind: str,
    parsed: dict[str, Any],
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO parsed_cv
               (file_hash, parser_provider, parser_model, file_name, file_kind, parsed_json, parsed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                file_hash,
                parser_provider,
                parser_model,
                file_name,
                file_kind,
                json.dumps(parsed, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def delete_cached_parses(file_hash: str) -> int:
    """Remove all cached parses for a file (any provider/model). Returns rows deleted."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM parsed_cv WHERE file_hash = ?", (file_hash,))
        conn.commit()
        return cur.rowcount or 0


def stats() -> dict[str, int]:
    """Quick summary, useful for `cvo cache` later."""
    with _connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM parsed_cv").fetchone()[0]
    return {"parsed_cv_rows": n}

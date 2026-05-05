"""Source activation registry for optional search datasets."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_REGISTRY_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "laws.db"
DEFAULT_KOKUJI_SOURCE = {
    "source_key": "kokuji",
    "source_label": "告示",
    "source_type": "kokuji",
    "is_active": 1,
    "is_removable": 0,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_registry_db(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_source_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
            source_key TEXT PRIMARY KEY,
            source_label TEXT NOT NULL,
            source_type TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            is_removable INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    now_iso = utc_now_iso()
    conn.execute(
        """
        INSERT INTO source_registry(
            source_key, source_label, source_type, is_active, is_removable, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_label = excluded.source_label,
            source_type = excluded.source_type,
            is_removable = excluded.is_removable,
            updated_at = CASE
                WHEN source_registry.source_label <> excluded.source_label
                  OR source_registry.source_type <> excluded.source_type
                  OR source_registry.is_removable <> excluded.is_removable
                THEN excluded.updated_at
                ELSE source_registry.updated_at
            END
        """,
        (
            DEFAULT_KOKUJI_SOURCE["source_key"],
            DEFAULT_KOKUJI_SOURCE["source_label"],
            DEFAULT_KOKUJI_SOURCE["source_type"],
            DEFAULT_KOKUJI_SOURCE["is_active"],
            DEFAULT_KOKUJI_SOURCE["is_removable"],
            now_iso,
            now_iso,
        ),
    )


def is_source_active(source_key: str = "kokuji", db_path: Path | None = None) -> bool:
    registry_path = DEFAULT_REGISTRY_DB_PATH if db_path is None else Path(db_path)
    if not registry_path.exists():
        return True

    conn = connect_registry_db(registry_path)
    try:
        ensure_source_registry(conn)
        row = conn.execute(
            "SELECT is_active FROM source_registry WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if row is None:
        return True
    return bool(int(row["is_active"]))


def set_source_active(source_key: str, is_active: bool, db_path: Path | None = None) -> None:
    registry_path = DEFAULT_REGISTRY_DB_PATH if db_path is None else Path(db_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_registry_db(registry_path)
    try:
        ensure_source_registry(conn)
        conn.execute(
            """
            UPDATE source_registry
            SET is_active = ?, updated_at = ?
            WHERE source_key = ?
            """,
            (1 if is_active else 0, utc_now_iso(), source_key),
        )
        conn.commit()
    finally:
        conn.close()

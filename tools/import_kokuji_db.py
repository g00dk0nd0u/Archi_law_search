#!/usr/bin/env python3
"""Import a prebuilt kokuji SQLite DB into this repository."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO_ROOT / "data" / "kokuji_notices.db"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.source_registry import DEFAULT_REGISTRY_DB_PATH, ensure_source_registry, set_source_active


REQUIRED_TABLES = ("notices", "notice_errors")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy a generated kokuji DB into Archi_law_search/data.")
    parser.add_argument("--source", required=True, help="Source kokuji DB path")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="Destination kokuji DB path")
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB_PATH), help="Registry DB path")
    return parser.parse_args()


def validate_source_db(source_path: Path) -> tuple[int, int, bool]:
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB not found: {source_path}")

    conn = sqlite3.connect(str(source_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = [table for table in REQUIRED_TABLES if table not in tables]
        if missing:
            raise ValueError(
                "Source DB is missing required tables: " + ", ".join(missing)
            )
        notices_count = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        error_count = conn.execute("SELECT COUNT(*) FROM notice_errors").fetchone()[0]
        has_fts = "notices_fts" in tables
        return notices_count, error_count, has_fts
    finally:
        conn.close()


def ensure_registry_default(registry_path: Path) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(registry_path))
    try:
        ensure_source_registry(conn)
        conn.commit()
    finally:
        conn.close()
    set_source_active("kokuji", True, registry_path)


def main() -> int:
    args = parse_args()
    source_path = Path(args.source).expanduser().resolve()
    dest_path = Path(args.dest).expanduser()
    registry_path = Path(args.registry_db).expanduser()

    try:
        notices_count, error_count, has_fts = validate_source_db(source_path)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest_path)
    ensure_registry_default(registry_path)

    print(f"Imported kokuji DB: {source_path} -> {dest_path}")
    print(f"notices: {notices_count}")
    print(f"notice_errors: {error_count}")
    print(f"notices_fts: {'yes' if has_fts else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

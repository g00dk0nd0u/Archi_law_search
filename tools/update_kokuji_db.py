#!/usr/bin/env python3
"""User-facing entrypoint for kokuji DB updates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.kokuji_database import DEFAULT_KOKUJI_CSV_PATH
from src.kokuji_update import DEFAULT_DB_PATH, execute_update


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely compare accepted kokuji CSV rows with laws.db and update only required records.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Check only. Do not modify the DB.")
    mode_group.add_argument("--apply", action="store_true", help="Update the DB.")
    parser.add_argument("--limit", type=int, default=None, help="Number of records to update in apply mode. Default: 20.")
    parser.add_argument("--input-csv", default=str(DEFAULT_KOKUJI_CSV_PATH), help="Input CSV path")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--verbose", action="store_true", help="Print per-record update progress in apply mode.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply_mode = args.apply
    if not (args.apply or args.dry_run):
        apply_mode = False
    return execute_update(
        input_csv=Path(args.input_csv).expanduser(),
        db_path=Path(args.db_path).expanduser(),
        apply=apply_mode,
        limit=args.limit,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())

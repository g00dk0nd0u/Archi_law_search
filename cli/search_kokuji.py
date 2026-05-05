#!/usr/bin/env python3
"""Search kokuji notices stored alongside laws.db."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "laws.db"

if __package__ in (None, ""):
    sys.path.append(str(REPO_ROOT))
    from src.kokuji_database import search_kokuji
else:
    from src.kokuji_database import search_kokuji


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search kokuji notices in laws.db and output JSON.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to laws.db")
    parser.add_argument("--query", required=True, help="Keyword query for kokuji notices")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of results")
    parser.add_argument("--json", action="store_true", help="Print compact JSON")
    parser.add_argument("--json-pretty", action="store_true", help="Print indented JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = search_kokuji(
        Path(args.db),
        query=args.query,
        limit=args.limit,
    )
    if args.json_pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

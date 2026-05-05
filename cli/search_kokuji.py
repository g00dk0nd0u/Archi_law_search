#!/usr/bin/env python3
"""Search kokuji notices stored alongside laws.db."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "kokuji_notices.db"
DEFAULT_REGISTRY_DB_PATH = REPO_ROOT / "data" / "laws.db"

if __package__ in (None, ""):
    sys.path.append(str(REPO_ROOT))
    from src.kokuji_database import search_kokuji
    from src.source_registry import is_source_active
else:
    from src.kokuji_database import search_kokuji
    from src.source_registry import is_source_active


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search bundled kokuji notices and output JSON.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to kokuji_notices.db")
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB_PATH), help="Path to source registry DB")
    parser.add_argument("--query", default="", help="Keyword query for kokuji notices")
    parser.add_argument("--notice-number", default="", help="Notice number query such as 1436 or 第1436号")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of results")
    parser.add_argument("--json", action="store_true", help="Print compact JSON")
    parser.add_argument("--json-pretty", action="store_true", help="Print indented JSON")
    return parser.parse_args()


def build_inactive_payload(db_path: Path, query: str, limit: int) -> dict[str, object]:
    return {
        "db_path": str(db_path),
        "query": query,
        "limit": limit,
        "count": 0,
        "inactive": True,
        "search_mode": "inactive",
        "warnings": [],
        "results": [],
        "message": "kokuji source is inactive",
    }


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    registry_db_path = Path(args.registry_db)
    if not args.query and not args.notice_number:
        print("Either --query or --notice-number is required.")
        return 1
    if not is_source_active("kokuji", registry_db_path):
        payload = build_inactive_payload(db_path, args.query, args.limit)
    else:
        try:
            payload = search_kokuji(
                db_path,
                query=args.query,
                notice_number=args.notice_number,
                limit=args.limit,
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(str(exc))
            return 1
    if args.json_pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

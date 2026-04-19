"""e-Gov から法令を取得し、検索用SQLite DBを作り直すCLI入口。"""

import argparse
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "laws.db"

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from src.law_database import LawSource, connect_db, init_db, replace_law
    from src.law_registry import DEFAULT_LAWS
    from src.laws_api import fetch_law_xml
else:
    from .law_database import LawSource, connect_db, init_db, replace_law
    from .law_registry import DEFAULT_LAWS
    from .laws_api import fetch_law_xml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建築法規データをSQLiteへ事前格納する")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="出力先SQLiteパス")
    parser.add_argument("--asof", default=None, help="法令取得日(YYYY-MM-DD)")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [LawSource(law.law_id, law.law_name) for law in DEFAULT_LAWS]

    conn = connect_db(db_path)
    try:
        init_db(conn)
        total = 0
        for source in sources:
            root = fetch_law_xml(source.law_id, as_of_date=args.asof)
            count = replace_law(conn, source, root)
            total += count
            print(f"[INFO] upserted {count} articles: {source.law_name} ({source.law_id})")
        conn.commit()
        print(f"[INFO] completed: {db_path} total_articles={total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

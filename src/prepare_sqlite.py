import argparse
from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from src.law_database import LawSource, connect_db, init_db, upsert_law
    from src.laws_api import LAW_MAIN_ID, LAW_ORDER_ID, safe_fetch
else:
    from .law_database import LawSource, connect_db, init_db, upsert_law
    from .laws_api import LAW_MAIN_ID, LAW_ORDER_ID, safe_fetch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建築基準法データをSQLiteへ事前格納する")
    parser.add_argument("--db", default="data/laws.db", help="出力先SQLiteパス")
    parser.add_argument("--asof", default=None, help="法令取得日(YYYY-MM-DD)")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [
        LawSource(LAW_MAIN_ID, "建築基準法"),
        LawSource(LAW_ORDER_ID, "建築基準法施行令"),
    ]

    conn = connect_db(db_path)
    try:
        init_db(conn)
        total = 0
        for source in sources:
            root = safe_fetch(source.law_id, as_of_date=args.asof)
            count = upsert_law(conn, source, root)
            total += count
            print(f"[INFO] upserted {count} articles: {source.law_name} ({source.law_id})")
        conn.commit()
        print(f"[INFO] completed: {db_path} total_articles={total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

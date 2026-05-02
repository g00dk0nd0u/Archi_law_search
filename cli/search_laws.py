#!/usr/bin/env python3
"""SQLite search helper for Codex and local CLI investigation."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_EXPORT_DIR = REPO_ROOT / "output"
DEFAULT_EXPORT_FILENAME = "law_search_results.txt"
DEFAULT_DB_CANDIDATES = (
    SCRIPT_DIR / "laws.db",
    SCRIPT_DIR.parent / "data" / "laws.db",
)
KANJI_DIGITS_REV = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def pick_existing_path(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def resolve_default_db_path() -> Path:
    path = pick_existing_path(DEFAULT_DB_CANDIDATES)
    if path is None:
        searched = "\n".join(f"- {candidate}" for candidate in DEFAULT_DB_CANDIDATES)
        raise FileNotFoundError(f"laws.db was not found. Checked:\n{searched}")
    return path


def first_matching_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise KeyError(f"Could not find any of columns {candidates!r} in {columns!r}")


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def detect_primary_key(conn: sqlite3.Connection, table_name: str) -> str:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    for row in rows:
        if int(row[5]) > 0:
            return str(row[1])
    return "rowid"


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def detect_schema(conn: sqlite3.Connection) -> dict[str, str]:
    laws_columns = table_columns(conn, "laws")
    articles_columns = table_columns(conn, "articles")
    return {
        "laws_table": "laws",
        "articles_table": "articles",
        "fts_table": "articles_fts",
        "law_id_col": first_matching_column(laws_columns, ("law_id", "id")),
        "law_title_col": first_matching_column(
            laws_columns, ("law_name", "law_title", "title", "name")
        ),
        "article_id_col": detect_primary_key(conn, "articles"),
        "article_law_id_col": first_matching_column(
            articles_columns, ("law_id", "law_ref", "law_code")
        ),
        "article_number_col": first_matching_column(
            articles_columns, ("article_no", "article_number", "article_num")
        ),
        "article_text_col": first_matching_column(
            articles_columns, ("body", "article_text", "text")
        ),
    }


def has_fts5_support(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(content)")
        conn.execute("DROP TABLE temp.fts5_probe")
        return True
    except sqlite3.DatabaseError:
        try:
            conn.execute("DROP TABLE IF EXISTS temp.fts5_probe")
        except sqlite3.DatabaseError:
            pass
        return False


def article_title_from_text(article_text: str) -> str:
    first_line = (article_text or "").strip().splitlines()[0] if (article_text or "").strip() else ""
    match = re.match(r"^（[^）]+）$", first_line)
    return match.group(0) if match else ""


def tokenize_query(query: str) -> list[str]:
    return [token for token in re.split(r"\s+", (query or "").strip()) if token]


def int_to_kanji(n: int) -> str:
    if n == 0:
        return "零"
    units = ["", "十", "百", "千"]
    value = ""
    digit_index = 0
    while n > 0:
        n, remainder = divmod(n, 10)
        if remainder:
            prefix = "" if (digit_index > 0 and remainder == 1) else KANJI_DIGITS_REV[remainder]
            value = prefix + (units[digit_index] if digit_index else "") + value
        digit_index += 1
    return value


def build_article_variants(article: str) -> list[str]:
    raw = (article or "").strip()
    if not raw:
        return []
    variants = {raw}
    normalized = raw.replace("－", "-").replace("ー", "-").replace("―", "-")
    match = re.fullmatch(r"(?:第)?(\d+)(?:条)?(?:[-の](\d+))?", normalized)
    if match:
        main_num = int(match.group(1))
        branch_num = match.group(2)
        variants.add(f"第{main_num}条")
        variants.add(f"第{int_to_kanji(main_num)}条")
        if branch_num is not None:
            branch_int = int(branch_num)
            variants.add(f"第{main_num}条の{branch_int}")
            variants.add(f"第{int_to_kanji(main_num)}条の{branch_int}")
            variants.add(f"第{int_to_kanji(main_num)}条の{int_to_kanji(branch_int)}")
    elif not raw.startswith("第"):
        variants.add(f"第{raw}")
    return [item for item in variants if item]


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def resolve_law_filter(
    conn: sqlite3.Connection,
    schema: dict[str, str],
    law: str,
) -> tuple[str, str] | None:
    law_value = (law or "").strip()
    if not law_value:
        return None

    row = conn.execute(
        f"""
        SELECT 1
        FROM {schema["laws_table"]}
        WHERE {schema["law_title_col"]} = ?
        LIMIT 1
        """,
        (law_value,),
    ).fetchone()
    if row is not None:
        return ("exact", law_value)
    return ("like", law_value)


def apply_law_filter_clause(
    clauses: list[str],
    params: list[Any],
    schema: dict[str, str],
    law_filter: tuple[str, str] | None,
) -> None:
    if law_filter is None:
        return
    mode, value = law_filter
    if mode == "exact":
        clauses.append(f'l.{schema["law_title_col"]} = ?')
        params.append(value)
        return
    clauses.append(f'l.{schema["law_title_col"]} LIKE ?')
    params.append(f"%{value}%")


def search_laws(
    db_path: Path,
    query: str = "",
    law: str = "",
    article: str = "",
    law_id: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    conn = connect_db(db_path)
    try:
        schema = detect_schema(conn)
        results, mode, warnings = execute_search(
            conn=conn,
            schema=schema,
            query=query,
            law=law,
            article=article,
            law_id=law_id,
            limit=limit,
        )
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "query": query,
        "law": law,
        "law_id": law_id,
        "article": article,
        "limit": limit,
        "count": len(results),
        "search_mode": mode,
        "warnings": warnings,
        "results": results,
    }


def build_export_search_label(
    query: str = "",
    law: str = "",
    article: str = "",
    law_id: str = "",
) -> str:
    parts = []
    if query:
        parts.append(query)
    if law:
        parts.append(f"法令名={law}")
    if article:
        parts.append(f"条番号={article}")
    if law_id:
        parts.append(f"法令ID={law_id}")
    return " / ".join(parts) if parts else "なし"


def build_txt_export_text(payload: dict[str, Any]) -> str:
    query = str(payload.get("query", "") or "")
    law = str(payload.get("law", "") or "")
    law_id = str(payload.get("law_id", "") or "")
    article = str(payload.get("article", "") or "")
    limit = payload.get("limit", "")
    lines = [
        "法令検索結果 原文一覧",
        "",
        "検索条件:",
        f"- query: {query}",
        f"- law: {law}",
        f"- law_id: {law_id}",
        f"- article: {article}",
        f"- limit: {limit}",
        "",
    ]

    results = payload.get("results", [])
    for index, row in enumerate(results, start=1):
        law_title = str(row.get("law_title", "") or "")
        article_number = str(row.get("article_number", "") or "")
        article_title = str(row.get("article_title", "") or "")
        article_text = str(row.get("article_text", "") or "")
        heading = f"【{index}】{law_title} {article_number}{article_title}".strip()

        lines.extend(
            [
                "=" * 60,
                heading.strip(),
                "=" * 60,
                "",
                article_text,
                "",
            ]
        )

    if not results:
        lines.append("検索結果はありません。")

    return "\n".join(lines).rstrip() + "\n"


def export_results_txt(export_path: Path, payload: dict[str, Any]) -> Path:
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(build_txt_export_text(payload), encoding="utf-8")
    return export_path


def resolve_export_path(export_txt: str) -> Path:
    raw = (export_txt or "").strip()
    if not raw:
        raise ValueError("export_txt path is empty")

    export_path = Path(raw).expanduser()
    if export_path.is_absolute():
        return export_path
    if export_path.parent == Path("."):
        return DEFAULT_EXPORT_DIR / export_path.name
    return REPO_ROOT / export_path


def build_export_summary(payload: dict[str, Any], export_path: Path) -> dict[str, Any]:
    results = [
        {
            "law_title": str(row.get("law_title", "") or ""),
            "article_number": str(row.get("article_number", "") or ""),
            "article_title": str(row.get("article_title", "") or ""),
        }
        for row in payload.get("results", [])
    ]
    export_label = (
        str(export_path.relative_to(REPO_ROOT))
        if export_path.is_relative_to(REPO_ROOT)
        else str(export_path)
    )
    return {
        "count": payload.get("count", 0),
        "export_txt": export_label,
        "results": results,
    }


def execute_search(
    conn: sqlite3.Connection,
    schema: dict[str, str],
    query: str,
    law: str,
    article: str,
    law_id: str,
    limit: int,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    tokens = tokenize_query(query)
    article_variants = build_article_variants(article)
    warnings: list[str] = []
    law_filter = resolve_law_filter(conn, schema, law)

    if not tokens and not law and not article and not law_id:
        return [], "empty", ["No search condition was given."]

    if tokens and table_exists(conn, schema["fts_table"]) and has_fts5_support(conn):
        try:
            return run_fts_search(
                conn=conn,
                schema=schema,
                tokens=tokens,
                law_filter=law_filter,
                article_variants=article_variants,
                law_id=law_id,
                limit=limit,
            ), "fts5", warnings
        except sqlite3.DatabaseError as exc:
            warnings.append(f"FTS5 search failed, fallback to LIKE: {exc}")

    results = run_like_search(
        conn=conn,
        schema=schema,
        tokens=tokens,
        law_filter=law_filter,
        article_variants=article_variants,
        law_id=law_id,
        limit=limit,
    )
    return results, "like", warnings


def run_fts_search(
    conn: sqlite3.Connection,
    schema: dict[str, str],
    tokens: list[str],
    law_filter: tuple[str, str] | None,
    article_variants: list[str],
    law_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if tokens:
        clauses.append(f'{schema["fts_table"]} MATCH ?')
        params.append(" AND ".join(quote_fts_term(token) for token in tokens))
    apply_law_filter_clause(clauses, params, schema, law_filter)
    if law_id:
        clauses.append(f'l.{schema["law_id_col"]} LIKE ?')
        params.append(f"%{law_id}%")
    if article_variants:
        article_parts = [f'a.{schema["article_number_col"]} = ?' for _ in article_variants]
        branchable_variants = [
            variant for variant in article_variants if "条" in variant and "の" not in variant
        ]
        if branchable_variants:
            article_parts.extend(
                [f'a.{schema["article_number_col"]} LIKE ?' for _ in branchable_variants]
            )
        clauses.append("(" + " OR ".join(article_parts) + ")")
        params.extend(article_variants)
        params.extend([f"{variant}の%" for variant in branchable_variants])

    where_sql = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT
            l.{schema["law_id_col"]} AS law_id,
            l.{schema["law_title_col"]} AS law_title,
            a.{schema["article_number_col"]} AS article_number,
            a.{schema["article_text_col"]} AS article_text,
            bm25({schema["fts_table"]}) AS match_score
        FROM {schema["fts_table"]}
        JOIN {schema["articles_table"]} a
            ON a.{schema["article_id_col"]} = {schema["fts_table"]}.rowid
        JOIN {schema["laws_table"]} l
            ON l.{schema["law_id_col"]} = a.{schema["article_law_id_col"]}
        WHERE {where_sql}
        ORDER BY match_score, a.rowid
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [row_to_result(row, source="fts5") for row in rows]


def run_like_search(
    conn: sqlite3.Connection,
    schema: dict[str, str],
    tokens: list[str],
    law_filter: tuple[str, str] | None,
    article_variants: list[str],
    law_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []

    for token in tokens:
        clauses.append(
            "("
            f"a.{schema['article_text_col']} LIKE ? "
            f"OR a.{schema['article_number_col']} LIKE ? "
            f"OR l.{schema['law_title_col']} LIKE ?"
            ")"
        )
        wildcard = f"%{token}%"
        params.extend((wildcard, wildcard, wildcard))

    apply_law_filter_clause(clauses, params, schema, law_filter)
    if law_id:
        clauses.append(f'l.{schema["law_id_col"]} LIKE ?')
        params.append(f"%{law_id}%")
    if article_variants:
        article_parts = [f'a.{schema["article_number_col"]} = ?' for _ in article_variants]
        branchable_variants = [
            variant for variant in article_variants if "条" in variant and "の" not in variant
        ]
        if branchable_variants:
            article_parts.extend(
                [f'a.{schema["article_number_col"]} LIKE ?' for _ in branchable_variants]
            )
        clauses.append("(" + " OR ".join(article_parts) + ")")
        params.extend(article_variants)
        params.extend([f"{variant}の%" for variant in branchable_variants])

    where_sql = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT
            l.{schema["law_id_col"]} AS law_id,
            l.{schema["law_title_col"]} AS law_title,
            a.{schema["article_number_col"]} AS article_number,
            a.{schema["article_text_col"]} AS article_text
        FROM {schema["articles_table"]} a
        JOIN {schema["laws_table"]} l
            ON l.{schema["law_id_col"]} = a.{schema["article_law_id_col"]}
        WHERE {where_sql}
        ORDER BY
            l.{schema["law_title_col"]},
            a.{schema["article_number_col"]}
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [row_to_result(row, source="like") for row in rows]


def row_to_result(row: sqlite3.Row, source: str) -> dict[str, Any]:
    article_text = str(row["article_text"] or "")
    result: dict[str, Any] = {
        "law_id": str(row["law_id"] or ""),
        "law_title": str(row["law_title"] or ""),
        "article_number": str(row["article_number"] or ""),
        "article_title": article_title_from_text(article_text),
        "article_text": article_text,
        "source": source,
    }
    if "match_score" in row.keys() and row["match_score"] is not None:
        result["match_score"] = float(row["match_score"])
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search laws.db and output JSON.")
    parser.add_argument("--db", help="Path to laws.db. Default: auto-detect near the repo.")
    parser.add_argument("--query", default="", help="Keyword query. Whitespace means AND search.")
    parser.add_argument("--law", default="", help="Law name. Exact match is preferred when available.")
    parser.add_argument("--law-id", default="", help="Law ID filter.")
    parser.add_argument("--article", default="", help="Article number filter, e.g. 第112条.")
    parser.add_argument("--limit", type=int, default=20, help="Result limit. Default: 20.")
    parser.add_argument(
        "--export-txt",
        nargs="?",
        const=DEFAULT_EXPORT_FILENAME,
        default="",
        help="Write matched article texts to a UTF-8 .txt file. If omitted, output/law_search_results.txt is used.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON. This is the default format and is kept for explicit CLI usage.",
    )
    parser.add_argument(
        "--json-pretty",
        action="store_true",
        help="Pretty-print JSON with indentation.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        db_path = Path(args.db).expanduser().resolve() if args.db else resolve_default_db_path()
        payload = search_laws(
            db_path=db_path,
            query=args.query,
            law=args.law,
            article=args.article,
            law_id=args.law_id,
            limit=args.limit,
        )
        output_payload = payload
        if args.export_txt:
            export_path = resolve_export_path(args.export_txt)
            export_results_txt(export_path, payload)
            output_payload = build_export_summary(payload, export_path)
    except KeyboardInterrupt:
        print(json.dumps({"error": "cancelled"}), file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    dump_kwargs = {"ensure_ascii": False}
    if args.json_pretty:
        dump_kwargs["indent"] = 2
    print(json.dumps(output_payload, **dump_kwargs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Search-only helpers for the bundled kokuji notice database."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KOKUJI_DB_PATH = REPO_ROOT / "data" / "kokuji_notices.db"
SNIPPET_LENGTH = 220
SNIPPET_CONTEXT = 90
FULLWIDTH_DIGIT_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")
KANJI_DIGITS = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}


def connect_db(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_kokuji_db_status(db_path: Path | str) -> tuple[bool, str]:
    path = Path(db_path)
    if not path.exists():
        return False, "告示DBが見つかりません"

    conn = connect_db(path)
    try:
        detect_schema(conn)
    except (FileNotFoundError, KeyError, sqlite3.DatabaseError):
        return False, "告示DBを開けません"
    finally:
        conn.close()
    return True, ""


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row["name"]) for row in rows]


def first_matching_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise KeyError(f"Could not find any of columns {candidates!r} in {columns!r}")


def supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.kokuji_fts5_probe USING fts5(content)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS temp.kokuji_fts5_probe")
        except sqlite3.OperationalError:
            pass


def detect_schema(conn: sqlite3.Connection) -> dict[str, str]:
    if table_exists(conn, "notices"):
        notices_table = "notices"
    elif table_exists(conn, "kokuji_notices"):
        notices_table = "kokuji_notices"
    else:
        raise FileNotFoundError("kokuji notice table was not found in the database.")

    columns = table_columns(conn, notices_table)
    fts_table = ""
    for candidate in ("notices_fts", "kokuji_notices_fts"):
        if table_exists(conn, candidate):
            fts_table = candidate
            break

    return {
        "notices_table": notices_table,
        "fts_table": fts_table,
        "row_id_col": first_matching_column(columns, ("id", "notice_id")),
        "notice_name_col": first_matching_column(columns, ("notice_name", "title", "name")),
        "document_number_col": first_matching_column(columns, ("document_number",)),
        "organization_col": first_matching_column(columns, ("organization",)),
        "url_col": first_matching_column(columns, ("url", "source_url", "pdf_url")),
        "full_text_col": first_matching_column(columns, ("full_text", "body", "text")),
    }


def tokenize_query(query: str) -> list[str]:
    return [token for token in re.split(r"[\s\u3000]+", (query or "").strip()) if token]


def normalize_ascii_digits(text: str) -> str:
    return (text or "").translate(FULLWIDTH_DIGIT_TRANS)


def int_to_kanji(number: int) -> str:
    if number == 0:
        return KANJI_DIGITS[0]

    parts: list[str] = []
    units = [(1000, "千"), (100, "百"), (10, "十"), (1, "")]
    remaining = number
    for value, label in units:
        digit = remaining // value
        remaining %= value
        if digit == 0:
            continue
        if value == 1:
            parts.append(KANJI_DIGITS[digit])
        elif digit == 1:
            parts.append(label)
        else:
            parts.append(f"{KANJI_DIGITS[digit]}{label}")
    return "".join(parts)


def build_query_variants(token: str) -> list[str]:
    normalized = normalize_ascii_digits(token.strip())
    variants: list[str] = []
    seen: set[str] = set()
    is_plain_number = bool(re.fullmatch(r"\d+", normalized))

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    if not is_plain_number:
        add(token)
        add(normalized)

    number_strings = re.findall(r"\d+", normalized)
    for number_string in number_strings:
        number_int = int(number_string)
        number_kanji = int_to_kanji(number_int)
        add(f"{number_string}号")
        add(f"第{number_string}号")
        add(number_kanji)
        add(f"{number_kanji}号")
        add(f"第{number_kanji}号")
        add(f"告示{number_string}号")
        add(f"告示第{number_string}号")
        add(f"告示{number_kanji}号")
        add(f"告示第{number_kanji}号")

    return variants


def build_highlight_terms(query: str) -> list[str]:
    highlight_terms: list[str] = []
    seen: set[str] = set()
    for token in tokenize_query(query):
        for variant in build_query_variants(token):
            if variant not in seen:
                seen.add(variant)
                highlight_terms.append(variant)
    return highlight_terms


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def format_snippet(text: str, terms: list[str]) -> str:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    best_index = -1
    best_term = ""
    for term in terms:
        index = lowered.find(term.lower())
        if index != -1 and (best_index == -1 or index < best_index):
            best_index = index
            best_term = term

    if best_index == -1:
        return cleaned[:SNIPPET_LENGTH]

    start = max(best_index - SNIPPET_CONTEXT, 0)
    end = min(best_index + len(best_term) + SNIPPET_CONTEXT, len(cleaned))
    snippet = cleaned[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(cleaned):
        snippet = snippet + "..."
    return snippet[: SNIPPET_LENGTH + 6]


def build_like_where_clause(target_columns: list[str], term_groups: list[list[str]]) -> tuple[str, list[str]]:
    term_clauses: list[str] = []
    params: list[str] = []
    for variants in term_groups:
        variant_clauses: list[str] = []
        for term in variants:
            column_clauses = [f"COALESCE({column}, '') LIKE ?" for column in target_columns]
            variant_clauses.append("(" + " OR ".join(column_clauses) + ")")
            params.extend([f"%{term}%"] * len(target_columns))
        term_clauses.append("(" + " OR ".join(variant_clauses) + ")")
    return " AND ".join(term_clauses), params


def build_rank_clause(schema: dict[str, str], highlight_terms: list[str]) -> tuple[str, list[str]]:
    document_number_col = schema["document_number_col"]
    notice_name_col = schema["notice_name_col"]
    full_text_col = schema["full_text_col"]
    organization_col = schema["organization_col"]

    def column_clause(column: str) -> str:
        return " OR ".join([f"COALESCE({column}, '') LIKE ?" for _ in highlight_terms]) or "0"

    rank_sql = f"""
        CASE
            WHEN ({column_clause(document_number_col)}) THEN 0
            WHEN ({column_clause(notice_name_col)}) THEN 1
            WHEN ({column_clause(full_text_col)}) THEN 2
            WHEN ({column_clause(organization_col)}) THEN 3
            ELSE 4
        END
    """
    like_params = [f"%{term}%" for term in highlight_terms]
    return rank_sql, [*like_params, *like_params, *like_params, *like_params]


def run_like_search(conn: sqlite3.Connection, schema: dict[str, str], term_groups: list[list[str]], limit: int) -> list[sqlite3.Row]:
    target_columns = [
        schema["notice_name_col"],
        schema["document_number_col"],
        schema["organization_col"],
        schema["full_text_col"],
    ]
    where_sql, params = build_like_where_clause(target_columns, term_groups)
    highlight_terms = [variant for variants in term_groups for variant in variants]
    rank_sql, rank_params = build_rank_clause(schema, highlight_terms)
    return conn.execute(
        f"""
        SELECT
            {schema["row_id_col"]} AS row_id,
            COALESCE({schema["notice_name_col"]}, '') AS notice_name,
            COALESCE({schema["document_number_col"]}, '') AS document_number,
            COALESCE({schema["organization_col"]}, '') AS organization,
            COALESCE({schema["url_col"]}, '') AS url,
            COALESCE({schema["full_text_col"]}, '') AS full_text,
            {rank_sql} AS match_rank
        FROM {schema["notices_table"]}
        WHERE {where_sql}
        ORDER BY match_rank, row_id
        LIMIT ?
        """,
        [*rank_params, *params, limit],
    ).fetchall()


def make_fts_query(terms: list[str]) -> str:
    escaped_terms = [term.replace('"', '""') for term in terms]
    return " AND ".join(f'"{term}"' for term in escaped_terms)


def run_fts_search(conn: sqlite3.Connection, schema: dict[str, str], terms: list[str], limit: int) -> list[sqlite3.Row]:
    if not schema["fts_table"]:
        return []
    return conn.execute(
        f"""
        SELECT
            n.{schema["row_id_col"]} AS row_id,
            COALESCE(n.{schema["notice_name_col"]}, '') AS notice_name,
            COALESCE(n.{schema["document_number_col"]}, '') AS document_number,
            COALESCE(n.{schema["organization_col"]}, '') AS organization,
            COALESCE(n.{schema["url_col"]}, '') AS url,
            COALESCE(n.{schema["full_text_col"]}, '') AS full_text
        FROM {schema["fts_table"]} f
        JOIN {schema["notices_table"]} n ON n.{schema["row_id_col"]} = f.rowid
        WHERE {schema["fts_table"]} MATCH ?
        ORDER BY row_id
        LIMIT ?
        """,
        (make_fts_query(terms), limit),
    ).fetchall()


def search_kokuji(db_path: Path, *, query: str, limit: int = 20) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    terms = tokenize_query(query)
    if not terms:
        raise ValueError("query must not be empty")
    term_groups = [build_query_variants(term) for term in terms]
    highlight_terms = build_highlight_terms(query)

    conn = connect_db(db_path)
    try:
        schema = detect_schema(conn)
        rows = run_like_search(conn, schema, term_groups, limit)
        mode = "like"
        warnings: list[str] = []
        if not rows and schema["fts_table"] and supports_fts5(conn):
            try:
                rows = run_fts_search(conn, schema, terms, limit)
                if rows:
                    mode = "fts_fallback"
            except sqlite3.OperationalError:
                warnings.append("FTS search was unavailable. Returning LIKE-only results.")
        results = [
            {
                "notice_name": row["notice_name"],
                "document_number": row["document_number"],
                "organization": row["organization"],
                "url": row["url"],
                "snippet": format_snippet(
                    row["full_text"]
                    or f'{row["notice_name"]} {row["document_number"]} {row["organization"]}',
                    highlight_terms,
                ),
            }
            for row in rows
        ]
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "query": query,
        "limit": limit,
        "count": len(results),
        "search_mode": mode,
        "highlight_terms": highlight_terms,
        "warnings": warnings,
        "results": results,
    }

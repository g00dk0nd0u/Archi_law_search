"""Search-only helpers for the bundled kokuji notice database."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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


def optional_matching_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def coalesce_expr(column: str, alias: str) -> str:
    if not column:
        return f"'' AS {alias}"
    return f"COALESCE({column}, '') AS {alias}"


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
        "document_number_norm_col": optional_matching_column(columns, ("document_number_norm",)),
        "document_number_digits_col": optional_matching_column(columns, ("document_number_digits",)),
        "organization_col": first_matching_column(columns, ("organization",)),
        "url_col": first_matching_column(columns, ("url", "source_url", "pdf_url")),
        "content_type_col": optional_matching_column(columns, ("content_type", "mime_type", "media_type")),
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


def extract_digits(text: str) -> str:
    return "".join(re.findall(r"\d+", normalize_ascii_digits(text or "")))


def build_notice_number_variants(notice_number: str) -> list[str]:
    raw = (notice_number or "").strip()
    if not raw:
        return []
    variants = build_query_variants(raw)
    digits = extract_digits(raw)
    if digits:
        for candidate in (digits, f"{digits}号", f"第{digits}号"):
            if candidate not in variants:
                variants.insert(0, candidate)
    return variants


def looks_like_notice_number_query(query: str) -> bool:
    normalized = normalize_ascii_digits((query or "").strip())
    if not normalized or len(tokenize_query(normalized)) != 1:
        return False
    return bool(extract_digits(normalized))


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


def build_notice_number_clause(schema: dict[str, str], notice_number: str) -> tuple[str, list[str], list[str], str]:
    variants = build_notice_number_variants(notice_number)
    digits = extract_digits(notice_number)
    clauses: list[str] = []
    params: list[str] = []
    search_columns = [
        schema.get("document_number_norm_col", ""),
        schema.get("document_number_col", ""),
        schema["notice_name_col"],
        schema["full_text_col"],
    ]
    for column in search_columns:
        if not column:
            continue
        variant_clauses = [f"COALESCE({column}, '') LIKE ?" for _ in variants]
        if variant_clauses:
            clauses.append("(" + " OR ".join(variant_clauses) + ")")
            params.extend([f"%{variant}%" for variant in variants])
    digits_column = schema.get("document_number_digits_col", "")
    if digits and digits_column:
        clauses.insert(0, f"COALESCE({digits_column}, '') = ?")
        params.insert(0, digits)
    return "(" + " OR ".join(clauses) + ")", params, variants, digits


def build_rank_clause(
    schema: dict[str, str],
    highlight_terms: list[str],
    notice_number: str = "",
) -> tuple[str, list[str]]:
    document_number_col = schema["document_number_col"]
    document_number_norm_col = schema.get("document_number_norm_col", "")
    document_number_digits_col = schema.get("document_number_digits_col", "")
    notice_name_col = schema["notice_name_col"]
    full_text_col = schema["full_text_col"]
    organization_col = schema["organization_col"]

    def column_clause(column: str) -> str:
        return " OR ".join([f"COALESCE({column}, '') LIKE ?" for _ in highlight_terms]) or "0"

    if notice_number:
        notice_digits = extract_digits(notice_number)
        digit_clause = f"COALESCE({document_number_digits_col}, '') = ?" if notice_digits and document_number_digits_col else "0"
        norm_clause = column_clause(document_number_norm_col) if document_number_norm_col else "0"
        number_clause = column_clause(document_number_col)
        name_clause = column_clause(notice_name_col)
        text_clause = column_clause(full_text_col)
        rank_sql = f"""
            CASE
                WHEN ({digit_clause}) THEN 0
                WHEN ({norm_clause}) THEN 1
                WHEN ({number_clause}) THEN 2
                WHEN ({name_clause}) THEN 3
                WHEN ({text_clause}) THEN 4
                ELSE 5
            END
        """
        highlight_like_params = [f"%{term}%" for term in highlight_terms]
        params: list[str] = []
        if notice_digits and document_number_digits_col:
            params.append(notice_digits)
        if document_number_norm_col:
            params.extend(highlight_like_params)
        params.extend(highlight_like_params)
        params.extend(highlight_like_params)
        params.extend(highlight_like_params)
        return rank_sql, params

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


def run_like_search(
    conn: sqlite3.Connection,
    schema: dict[str, str],
    query: str,
    notice_number: str,
    limit: int,
) -> list[sqlite3.Row]:
    where_parts: list[str] = []
    params: list[str] = []
    term_groups: list[list[str]] = []

    if query:
        term_groups = [build_query_variants(term) for term in tokenize_query(query)]
        target_columns = [
            column
            for column in (
                schema.get("document_number_norm_col", ""),
                schema["notice_name_col"],
                schema["document_number_col"],
                schema["organization_col"],
                schema["full_text_col"],
            )
            if column
        ]
        where_sql, where_params = build_like_where_clause(target_columns, term_groups)
        where_parts.append(f"({where_sql})")
        params.extend(where_params)

    if notice_number:
        notice_sql, notice_params, _variants, _digits = build_notice_number_clause(schema, notice_number)
        where_parts.append(notice_sql)
        params.extend(notice_params)

    highlight_terms: list[str] = []
    if query:
        highlight_terms.extend(build_highlight_terms(query))
    if notice_number:
        for variant in build_notice_number_variants(notice_number):
            if variant not in highlight_terms:
                highlight_terms.append(variant)
        digits = extract_digits(notice_number)
        if digits and digits not in highlight_terms:
            highlight_terms.append(digits)

    rank_sql, rank_params = build_rank_clause(schema, highlight_terms, notice_number=notice_number)
    return conn.execute(
        f"""
        SELECT
            {schema["row_id_col"]} AS row_id,
            COALESCE({schema["notice_name_col"]}, '') AS notice_name,
            COALESCE({schema["document_number_col"]}, '') AS document_number,
            {coalesce_expr(schema.get("document_number_norm_col", ""), "document_number_norm")},
            {coalesce_expr(schema.get("document_number_digits_col", ""), "document_number_digits")},
            COALESCE({schema["organization_col"]}, '') AS organization,
            COALESCE({schema["url_col"]}, '') AS url,
            {coalesce_expr(schema.get("content_type_col", ""), "content_type")},
            COALESCE({schema["full_text_col"]}, '') AS full_text,
            {rank_sql} AS match_rank
        FROM {schema["notices_table"]}
        WHERE {" AND ".join(where_parts)}
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
            {coalesce_expr('n.' + schema.get("document_number_norm_col", "") if schema.get("document_number_norm_col", "") else '', "document_number_norm")},
            {coalesce_expr('n.' + schema.get("document_number_digits_col", "") if schema.get("document_number_digits_col", "") else '', "document_number_digits")},
            COALESCE(n.{schema["organization_col"]}, '') AS organization,
            COALESCE(n.{schema["url_col"]}, '') AS url,
            {coalesce_expr('n.' + schema.get("content_type_col", "") if schema.get("content_type_col", "") else '', "content_type")},
            COALESCE(n.{schema["full_text_col"]}, '') AS full_text
        FROM {schema["fts_table"]} f
        JOIN {schema["notices_table"]} n ON n.{schema["row_id_col"]} = f.rowid
        WHERE {schema["fts_table"]} MATCH ?
        ORDER BY row_id
        LIMIT ?
        """,
        (make_fts_query(terms), limit),
    ).fetchall()


def display_document_number(result: dict[str, Any]) -> str:
    for value in (
        result.get("document_number_norm", ""),
        result.get("document_number", ""),
        f'{result.get("document_number_digits", "")}号' if result.get("document_number_digits", "") else "",
    ):
        text = (value or "").strip()
        if text:
            return text
    return ""


def detect_link_label(url: str, content_type: str = "") -> str:
    content_type_value = (content_type or "").strip().lower()
    if "pdf" in content_type_value:
        return "PDF"
    if "html" in content_type_value:
        return "HTML"
    if "word" in content_type_value or "docx" in content_type_value:
        return "DOCX"
    if "excel" in content_type_value or "xlsx" in content_type_value:
        return "XLSX"

    path = urlparse((url or "").strip()).path.lower()
    extension = path.rsplit(".", 1)[-1] if "." in path else ""
    return {
        "pdf": "PDF",
        "html": "HTML",
        "htm": "HTML",
        "docx": "DOCX",
        "doc": "DOC",
        "xlsx": "XLSX",
        "xls": "XLS",
    }.get(extension, "LINK")


def search_kokuji(
    db_path: Path,
    *,
    query: str = "",
    notice_number: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    query = (query or "").strip()
    notice_number = (notice_number or "").strip()
    derived_from_query = not notice_number and looks_like_notice_number_query(query)
    derived_notice_number = notice_number or (query if derived_from_query else "")
    effective_query = "" if derived_from_query else query
    terms = tokenize_query(effective_query)
    if not terms and not derived_notice_number:
        raise ValueError("query or notice_number must not be empty")
    highlight_terms = build_highlight_terms(query)
    for term in build_notice_number_variants(derived_notice_number):
        if term not in highlight_terms:
            highlight_terms.append(term)
    digits = extract_digits(derived_notice_number)
    if digits and digits not in highlight_terms:
        highlight_terms.append(digits)

    conn = connect_db(db_path)
    try:
        schema = detect_schema(conn)
        rows = run_like_search(conn, schema, effective_query, derived_notice_number, limit)
        mode = "like"
        warnings: list[str] = []
        if not rows and terms and not derived_notice_number and schema["fts_table"] and supports_fts5(conn):
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
                "document_number_norm": row["document_number_norm"],
                "document_number_digits": row["document_number_digits"],
                "display_document_number": display_document_number(dict(row)),
                "organization": row["organization"],
                "url": row["url"],
                "content_type": row["content_type"],
                "link_label": detect_link_label(row["url"], row["content_type"]),
                "snippet": format_snippet(
                    row["full_text"]
                    or " ".join(
                        filter(
                            None,
                            [
                                row["notice_name"],
                                row["document_number_norm"],
                                row["document_number"],
                                row["document_number_digits"],
                                row["organization"],
                            ],
                        )
                    ),
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
        "notice_number": derived_notice_number,
        "limit": limit,
        "count": len(results),
        "search_mode": mode,
        "highlight_terms": highlight_terms,
        "warnings": warnings,
        "results": results,
    }

"""Kokuji notice storage, update, and search helpers.

This module keeps kokuji-specific schema and optional PDF extraction isolated
from the existing law/article database flow.
"""

from __future__ import annotations

import csv
import html
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REQUEST_TIMEOUT = 30
PDF_HEADER = b"%PDF-"
USER_AGENT = "ArchiLawSearchKokuji/0.1"
CHARSET_PATTERN = re.compile(rb"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", re.IGNORECASE)
DEFAULT_KOKUJI_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "accepted_kokuji_notices.csv"
SNIPPET_LENGTH = 220
SNIPPET_CONTEXT = 90


class NoticeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lc = tag.lower()
        if tag_lc in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag_lc in {"br", "p", "div", "li", "tr", "section", "article", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lc = tag.lower()
        if tag_lc in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag_lc in {"p", "div", "li", "tr", "section", "article", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)
            self._chunks.append("\n")

    def get_text(self) -> str:
        lines = [line.strip() for line in "".join(self._chunks).splitlines()]
        return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class NoticeRow:
    notice_name: str
    document_number: str
    document_date: str
    organization: str
    url: str
    match_reason: str


@dataclass(frozen=True)
class FetchedDocument:
    format_name: str
    data: bytes
    content_type: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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


def has_kokuji_fts_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'kokuji_notices_fts'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def ensure_kokuji_schema(conn: sqlite3.Connection, *, rebuild_fts: bool = True) -> bool:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kokuji_notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_name TEXT NOT NULL,
            document_number TEXT,
            document_date TEXT,
            organization TEXT,
            url TEXT UNIQUE,
            match_reason TEXT,
            fetch_status TEXT,
            text_status TEXT,
            full_text TEXT,
            text_char_count INTEGER NOT NULL DEFAULT 0,
            page_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS kokuji_notice_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id INTEGER,
            url TEXT,
            phase TEXT NOT NULL,
            error_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(notice_id) REFERENCES kokuji_notices(id)
        );

        CREATE INDEX IF NOT EXISTS idx_kokuji_notices_url
        ON kokuji_notices(url);

        CREATE INDEX IF NOT EXISTS idx_kokuji_notices_notice_name
        ON kokuji_notices(notice_name);

        CREATE INDEX IF NOT EXISTS idx_kokuji_notices_document_number
        ON kokuji_notices(document_number);

        CREATE INDEX IF NOT EXISTS idx_kokuji_notices_organization
        ON kokuji_notices(organization);

        CREATE INDEX IF NOT EXISTS idx_kokuji_notice_errors_notice_id
        ON kokuji_notice_errors(notice_id);
        """
    )
    ensure_kokuji_columns(conn)

    if not supports_fts5(conn):
        drop_kokuji_fts(conn)
        return False

    try:
        if rebuild_fts:
            rebuild_kokuji_fts(conn)
        else:
            create_kokuji_fts_if_needed(conn)
        return True
    except sqlite3.OperationalError:
        return False


def ensure_kokuji_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(kokuji_notices)").fetchall()
    columns = {str(row["name"]) for row in rows}
    if not rows:
        return

    now_iso = utc_now_iso()
    if "created_at" not in columns:
        conn.execute("ALTER TABLE kokuji_notices ADD COLUMN created_at TEXT")
        conn.execute(
            "UPDATE kokuji_notices SET created_at = COALESCE(updated_at, ?) WHERE created_at IS NULL",
            (now_iso,),
        )
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE kokuji_notices ADD COLUMN updated_at TEXT")
        conn.execute(
            "UPDATE kokuji_notices SET updated_at = ? WHERE updated_at IS NULL",
            (now_iso,),
        )


def drop_kokuji_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS kokuji_notices_fts")


def create_kokuji_fts_if_needed(conn: sqlite3.Connection) -> None:
    if has_kokuji_fts_table(conn):
        return
    conn.execute(
        """
        CREATE VIRTUAL TABLE kokuji_notices_fts
        USING fts5(
            notice_name,
            document_number,
            organization,
            full_text
        )
        """
    )


def rebuild_kokuji_fts(conn: sqlite3.Connection) -> None:
    drop_kokuji_fts(conn)
    create_kokuji_fts_if_needed(conn)
    refresh_kokuji_fts(conn)


def refresh_kokuji_fts(conn: sqlite3.Connection) -> None:
    if not has_kokuji_fts_table(conn):
        return
    conn.execute("DELETE FROM kokuji_notices_fts")
    conn.execute(
        """
        INSERT INTO kokuji_notices_fts(
            rowid,
            notice_name,
            document_number,
            organization,
            full_text
        )
        SELECT
            id,
            notice_name,
            COALESCE(document_number, ''),
            COALESCE(organization, ''),
            COALESCE(full_text, '')
        FROM kokuji_notices
        ORDER BY id
        """
    )


def read_notice_rows(csv_path: Path) -> list[NoticeRow]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            NoticeRow(
                notice_name=(row.get("notice_name") or "").strip(),
                document_number=(row.get("document_number") or "").strip(),
                document_date=(row.get("document_date") or "").strip(),
                organization=(row.get("organization") or "").strip(),
                url=(row.get("url") or "").strip(),
                match_reason=(row.get("match_reason") or "").strip(),
            )
            for row in reader
        ]


def get_notice_metadata(conn: sqlite3.Connection, notice_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT full_text, text_char_count, page_count
        FROM kokuji_notices
        WHERE id = ?
        """,
        (notice_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Notice not found: id={notice_id}")
    return row


def upsert_notice(conn: sqlite3.Connection, row: NoticeRow, now_iso: str) -> int:
    if row.url:
        conn.execute(
            """
            INSERT INTO kokuji_notices(
                notice_name,
                document_number,
                document_date,
                organization,
                url,
                match_reason,
                fetch_status,
                text_status,
                text_char_count,
                page_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, 0, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                notice_name = excluded.notice_name,
                document_number = excluded.document_number,
                document_date = excluded.document_date,
                organization = excluded.organization,
                match_reason = excluded.match_reason,
                updated_at = excluded.updated_at
            """,
            (
                row.notice_name,
                row.document_number,
                row.document_date,
                row.organization,
                row.url,
                row.match_reason,
                now_iso,
                now_iso,
            ),
        )
        found = conn.execute("SELECT id FROM kokuji_notices WHERE url = ?", (row.url,)).fetchone()
        return int(found["id"])

    existing = conn.execute(
        """
        SELECT id
        FROM kokuji_notices
        WHERE url IS NULL
          AND notice_name = ?
          AND document_number = ?
          AND document_date = ?
          AND organization = ?
        """,
        (
            row.notice_name,
            row.document_number,
            row.document_date,
            row.organization,
        ),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE kokuji_notices
            SET match_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (row.match_reason, now_iso, int(existing["id"])),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO kokuji_notices(
            notice_name,
            document_number,
            document_date,
            organization,
            url,
            match_reason,
            fetch_status,
            text_status,
            text_char_count,
            page_count,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, 0, 0, ?, ?)
        """,
        (
            row.notice_name,
            row.document_number,
            row.document_date,
            row.organization,
            row.match_reason,
            now_iso,
            now_iso,
        ),
    )
    return int(cursor.lastrowid)


def reset_notice_errors(conn: sqlite3.Connection, notice_id: int) -> None:
    conn.execute("DELETE FROM kokuji_notice_errors WHERE notice_id = ?", (notice_id,))


def log_notice_error(
    conn: sqlite3.Connection,
    notice_id: int | None,
    url: str,
    phase: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO kokuji_notice_errors(notice_id, url, phase, error_message, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (notice_id, url or None, phase, error_message[:4000], utc_now_iso()),
    )


def update_notice_status(
    conn: sqlite3.Connection,
    notice_id: int,
    *,
    fetch_status: str,
    text_status: str,
    full_text: str | None,
    text_char_count: int,
    page_count: int,
    now_iso: str,
) -> None:
    conn.execute(
        """
        UPDATE kokuji_notices
        SET fetch_status = ?,
            text_status = ?,
            full_text = ?,
            text_char_count = ?,
            page_count = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (fetch_status, text_status, full_text, text_char_count, page_count, now_iso, notice_id),
    )


def _import_requests() -> Any:
    try:
        import requests  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "requests is required for kokuji updates. Install it with: pip install -r requirements-kokuji.txt"
        ) from exc
    return requests


def _import_pypdf_reader() -> Any:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "pypdf is required for PDF extraction. Install it with: pip install -r requirements-kokuji.txt"
        ) from exc
    return PdfReader


def looks_like_pdf(url: str, content_type: str, data: bytes) -> bool:
    content_type_lc = (content_type or "").lower()
    url_lc = (url or "").lower()
    return (
        "application/pdf" in content_type_lc
        or url_lc.endswith(".pdf")
        or data[:1024].lstrip().startswith(PDF_HEADER)
    )


def looks_like_html(url: str, content_type: str, data: bytes) -> bool:
    content_type_lc = (content_type or "").lower()
    url_lc = (url or "").lower()
    sniff = data[:2048].lstrip().lower()
    return (
        "text/html" in content_type_lc
        or "application/xhtml+xml" in content_type_lc
        or url_lc.endswith(".html")
        or url_lc.endswith(".htm")
        or sniff.startswith(b"<!doctype html")
        or sniff.startswith(b"<html")
    )


def detect_document_format(url: str, content_type: str, data: bytes) -> str:
    if looks_like_pdf(url, content_type, data):
        return "pdf"
    if looks_like_html(url, content_type, data):
        return "html"
    raise ValueError(
        f"Unsupported notice format. content_type={content_type or '(none)'} url={url or '(none)'}"
    )


def fetch_notice_document(url: str) -> FetchedDocument:
    requests = _import_requests()
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    data = response.content
    content_type = response.headers.get("Content-Type", "")
    format_name = detect_document_format(url, content_type, data)
    return FetchedDocument(format_name=format_name, data=data, content_type=content_type)


def extract_pdf_pages(pdf_bytes: bytes) -> tuple[int, list[str]]:
    PdfReader = _import_pypdf_reader()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = len(reader.pages)
    page_texts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        page_texts.append(text.strip())
    return page_count, page_texts


def decode_html_bytes(html_bytes: bytes) -> str:
    sniff = html_bytes[:4096]
    match = CHARSET_PATTERN.search(sniff)
    encodings = [match.group(1).decode("ascii", errors="ignore")] if match else []
    encodings.extend(["utf-8", "cp932", "shift_jis"])
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return html_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return html_bytes.decode("utf-8", errors="ignore")


def extract_html_text(html_bytes: bytes) -> tuple[int, list[str]]:
    parser = NoticeHTMLParser()
    parser.feed(decode_html_bytes(html_bytes))
    parser.close()
    text = html.unescape(parser.get_text())
    return 1, [text] if text else []


def extract_document_text(document: FetchedDocument) -> tuple[int, list[str]]:
    if document.format_name == "pdf":
        return extract_pdf_pages(document.data)
    if document.format_name == "html":
        return extract_html_text(document.data)
    raise ValueError(f"Unsupported document format: {document.format_name}")


def build_full_text(page_texts: list[str]) -> str:
    return "\n\n".join(text for text in page_texts if text)


def process_notice(
    conn: sqlite3.Connection,
    row: NoticeRow,
    *,
    fts_enabled: bool,
) -> tuple[str, str, int, int]:
    del fts_enabled  # FTS refresh is handled in batch after updates.
    now_iso = utc_now_iso()
    notice_id = upsert_notice(conn, row, now_iso)
    reset_notice_errors(conn, notice_id)
    previous = get_notice_metadata(conn, notice_id)
    previous_full_text = previous["full_text"]
    previous_char_count = int(previous["text_char_count"] or 0)
    previous_page_count = int(previous["page_count"] or 0)

    if not row.url:
        update_notice_status(
            conn,
            notice_id,
            fetch_status="skipped_no_url",
            text_status="skipped",
            full_text=previous_full_text,
            text_char_count=previous_char_count,
            page_count=previous_page_count,
            now_iso=now_iso,
        )
        return ("skipped_no_url", "skipped", previous_char_count, previous_page_count)

    try:
        fetched = fetch_notice_document(row.url)
    except Exception as exc:
        log_notice_error(conn, notice_id, row.url, "fetch", str(exc))
        update_notice_status(
            conn,
            notice_id,
            fetch_status="fetch_error",
            text_status="skipped",
            full_text=previous_full_text,
            text_char_count=previous_char_count,
            page_count=previous_page_count,
            now_iso=now_iso,
        )
        return ("fetch_error", "skipped", previous_char_count, previous_page_count)

    try:
        page_count, page_texts = extract_document_text(fetched)
        full_text = build_full_text(page_texts)
    except Exception as exc:
        log_notice_error(conn, notice_id, row.url, "parse", str(exc))
        update_notice_status(
            conn,
            notice_id,
            fetch_status="fetch_ok",
            text_status="parse_error",
            full_text=previous_full_text,
            text_char_count=previous_char_count,
            page_count=previous_page_count,
            now_iso=now_iso,
        )
        return ("fetch_ok", "parse_error", previous_char_count, previous_page_count)

    if not full_text.strip():
        log_notice_error(conn, notice_id, row.url, "text", "Extracted text was empty.")
        update_notice_status(
            conn,
            notice_id,
            fetch_status="fetch_ok",
            text_status="empty_text",
            full_text=previous_full_text,
            text_char_count=previous_char_count,
            page_count=previous_page_count,
            now_iso=now_iso,
        )
        return ("fetch_ok", "empty_text", previous_char_count, previous_page_count)

    text_char_count = len(full_text)
    update_notice_status(
        conn,
        notice_id,
        fetch_status="fetch_ok",
        text_status="text_ok",
        full_text=full_text,
        text_char_count=text_char_count,
        page_count=page_count,
        now_iso=now_iso,
    )
    return ("fetch_ok", "text_ok", text_char_count, page_count)


def collect_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {
        "kokuji_notices": conn.execute("SELECT COUNT(*) FROM kokuji_notices").fetchone()[0],
        "kokuji_notices_with_full_text": conn.execute(
            "SELECT COUNT(*) FROM kokuji_notices WHERE COALESCE(full_text, '') <> ''"
        ).fetchone()[0],
        "kokuji_notice_errors": conn.execute("SELECT COUNT(*) FROM kokuji_notice_errors").fetchone()[0],
    }
    if has_kokuji_fts_table(conn):
        counts["kokuji_notices_fts"] = conn.execute("SELECT COUNT(*) FROM kokuji_notices_fts").fetchone()[0]
    return counts


def tokenize_query(query: str) -> list[str]:
    return [token for token in re.split(r"[\s\u3000]+", (query or "").strip()) if token]


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


def build_like_where_clause(target_columns: list[str], terms: list[str]) -> tuple[str, list[str]]:
    term_clauses: list[str] = []
    params: list[str] = []
    for term in terms:
        column_clauses = [f"COALESCE({column}, '') LIKE ?" for column in target_columns]
        term_clauses.append("(" + " OR ".join(column_clauses) + ")")
        params.extend([f"%{term}%"] * len(target_columns))
    return " AND ".join(term_clauses), params


def run_like_search(conn: sqlite3.Connection, terms: list[str], limit: int) -> list[sqlite3.Row]:
    target_columns = ["notice_name", "document_number", "organization", "full_text"]
    where_sql, params = build_like_where_clause(target_columns, terms)
    return conn.execute(
        f"""
        SELECT
            id,
            notice_name,
            COALESCE(document_number, '') AS document_number,
            COALESCE(organization, '') AS organization,
            COALESCE(url, '') AS url,
            COALESCE(full_text, '') AS full_text
        FROM kokuji_notices
        WHERE {where_sql}
        ORDER BY id
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()


def make_fts_query(terms: list[str]) -> str:
    escaped_terms = [term.replace('"', '""') for term in terms]
    return " AND ".join(f'"{term}"' for term in escaped_terms)


def run_fts_search(conn: sqlite3.Connection, terms: list[str], limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            n.id,
            n.notice_name,
            COALESCE(n.document_number, '') AS document_number,
            COALESCE(n.organization, '') AS organization,
            COALESCE(n.url, '') AS url,
            COALESCE(n.full_text, '') AS full_text
        FROM kokuji_notices_fts f
        JOIN kokuji_notices n ON n.id = f.rowid
        WHERE kokuji_notices_fts MATCH ?
        ORDER BY n.id
        LIMIT ?
        """,
        (make_fts_query(terms), limit),
    ).fetchall()


def search_kokuji(
    db_path: Path,
    *,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    terms = tokenize_query(query)
    if not terms:
        raise ValueError("query must not be empty")

    conn = connect_db(db_path)
    try:
        ensure_kokuji_schema(conn, rebuild_fts=False)
        like_rows = run_like_search(conn, terms, limit)
        rows = like_rows
        mode = "like"
        warnings: list[str] = []
        if not rows and has_kokuji_fts_table(conn):
            try:
                rows = run_fts_search(conn, terms, limit)
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
                    row["full_text"] or f'{row["notice_name"]} {row["document_number"]} {row["organization"]}',
                    terms,
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
        "warnings": warnings,
        "results": results,
    }

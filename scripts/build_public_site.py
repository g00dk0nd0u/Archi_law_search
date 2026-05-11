#!/usr/bin/env python3
"""Build static JSON data for the GitHub Pages search app."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
LAW_DB_PATH = REPO_ROOT / "data" / "laws.db"
KOKUJI_DB_PATH = REPO_ROOT / "data" / "kokuji_notices.db"
PUBLIC_DATA_DIR = REPO_ROOT / "docs" / "data"
BODIES_DIR = PUBLIC_DATA_DIR / "bodies"
BODY_SHARD_SIZE = 200
PREVIEW_CHARS = 180

sys.path.insert(0, str(REPO_ROOT))

from cli.search_laws import article_title_from_text  # noqa: E402
from src.kokuji_database import detect_link_label, detect_schema as detect_kokuji_schema  # noqa: E402


def normalize_preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def write_body_shards(source: str, rows: Iterable[tuple[str, str]]) -> dict[str, str]:
    body_paths: dict[str, str] = {}
    shard: dict[str, str] = {}
    shard_index = 1

    def flush() -> None:
        nonlocal shard, shard_index
        if not shard:
            return
        path = BODIES_DIR / f"{source}_{shard_index:04d}.json"
        write_json(path, {"source": source, "bodies": shard})
        relative_path = f"data/bodies/{path.name}"
        for body_id in shard:
            body_paths[body_id] = relative_path
        shard = {}
        shard_index += 1

    for body_id, body in rows:
        shard[body_id] = body or ""
        if len(shard) >= BODY_SHARD_SIZE:
            flush()
    flush()
    return body_paths


def build_law_data(generated_at: str) -> None:
    conn = sqlite3.connect(str(LAW_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                a.id,
                l.law_id,
                l.law_name,
                a.article_no,
                a.provision_kind,
                a.provision_context,
                a.body,
                a.article_sort_base,
                a.article_sort_branch
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            ORDER BY l.law_name, a.article_sort_base, a.article_sort_branch, a.id
            """
        ).fetchall()
    finally:
        conn.close()

    body_rows = [(f"law:{row['id']}", str(row["body"] or "")) for row in rows]
    body_paths = write_body_shards("law", body_rows)
    records = []
    for row in rows:
        body_id = f"law:{row['id']}"
        body = str(row["body"] or "")
        records.append(
            {
                "id": body_id,
                "law_id": str(row["law_id"] or ""),
                "law_title": str(row["law_name"] or ""),
                "article_number": str(row["article_no"] or ""),
                "article_title": article_title_from_text(body),
                "provision_kind": str(row["provision_kind"] or ""),
                "provision_context": str(row["provision_context"] or ""),
                "preview": normalize_preview(body),
                "body_path": body_paths[body_id],
                "body_chars": len(body),
            }
        )

    write_json(
        PUBLIC_DATA_DIR / "law_index.json",
        {
            "source": "law",
            "generated_at": generated_at,
            "count": len(records),
            "records": records,
        },
    )


def build_kokuji_data(generated_at: str) -> None:
    conn = sqlite3.connect(str(KOKUJI_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        schema = detect_kokuji_schema(conn)
        content_type_expr = (
            f"COALESCE({schema['content_type_col']}, '')"
            if schema.get("content_type_col")
            else "''"
        )
        document_number_norm_expr = (
            f"COALESCE({schema['document_number_norm_col']}, '')"
            if schema.get("document_number_norm_col")
            else "''"
        )
        document_number_digits_expr = (
            f"COALESCE({schema['document_number_digits_col']}, '')"
            if schema.get("document_number_digits_col")
            else "''"
        )
        document_date_expr = (
            f"COALESCE({schema['document_date_col']}, '')"
            if schema.get("document_date_col")
            else "''"
        )
        rows = conn.execute(
            f"""
            SELECT
                {schema['row_id_col']} AS row_id,
                COALESCE({schema['notice_name_col']}, '') AS notice_name,
                COALESCE({schema['document_number_col']}, '') AS document_number,
                {document_number_norm_expr} AS document_number_norm,
                {document_number_digits_expr} AS document_number_digits,
                {document_date_expr} AS document_date,
                COALESCE({schema['organization_col']}, '') AS organization,
                COALESCE({schema['url_col']}, '') AS url,
                {content_type_expr} AS content_type,
                COALESCE({schema['full_text_col']}, '') AS full_text
            FROM {schema['notices_table']}
            ORDER BY row_id
            """
        ).fetchall()
    finally:
        conn.close()

    body_rows = [(f"kokuji:{row['row_id']}", str(row["full_text"] or "")) for row in rows]
    body_paths = write_body_shards("kokuji", body_rows)
    records = []
    for row in rows:
        body_id = f"kokuji:{row['row_id']}"
        full_text = str(row["full_text"] or "")
        url = str(row["url"] or "")
        content_type = str(row["content_type"] or "")
        records.append(
            {
                "id": body_id,
                "notice_name": str(row["notice_name"] or ""),
                "document_number": str(row["document_number"] or ""),
                "document_number_norm": str(row["document_number_norm"] or ""),
                "document_number_digits": str(row["document_number_digits"] or ""),
                "document_date": str(row["document_date"] or ""),
                "organization": str(row["organization"] or ""),
                "url": url,
                "link_label": detect_link_label(url, content_type),
                "preview": normalize_preview(full_text),
                "body_path": body_paths[body_id],
                "body_chars": len(full_text),
            }
        )

    write_json(
        PUBLIC_DATA_DIR / "kokuji_index.json",
        {
            "source": "kokuji",
            "generated_at": generated_at,
            "count": len(records),
            "records": records,
        },
    )


def clear_old_body_shards() -> None:
    BODIES_DIR.mkdir(parents=True, exist_ok=True)
    for path in BODIES_DIR.glob("*.json"):
        path.unlink()


def main() -> int:
    if not LAW_DB_PATH.exists():
        print(f"laws.db not found: {LAW_DB_PATH}", file=sys.stderr)
        return 1
    if not KOKUJI_DB_PATH.exists():
        print(f"kokuji_notices.db not found: {KOKUJI_DB_PATH}", file=sys.stderr)
        return 1

    generated_at = datetime.now(timezone.utc).isoformat()
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    clear_old_body_shards()
    build_law_data(generated_at)
    build_kokuji_data(generated_at)

    print(
        json.dumps(
            {
                "law_index": "docs/data/law_index.json",
                "kokuji_index": "docs/data/kokuji_index.json",
                "bodies": "docs/data/bodies",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

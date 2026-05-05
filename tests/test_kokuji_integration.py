"""Regression tests for the staged kokuji integration."""

from __future__ import annotations

import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from kokuji_database import (  # type: ignore
    NoticeRow,
    connect_db,
    ensure_kokuji_schema,
    has_kokuji_fts_table,
    process_notice,
    search_kokuji,
    update_notice_status,
    upsert_notice,
)
from law_database import init_db  # type: ignore


class KokujiIntegrationTests(unittest.TestCase):
    def test_ensure_kokuji_schema_keeps_existing_law_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            init_db(conn)
            fts_enabled = ensure_kokuji_schema(conn, rebuild_fts=True)

            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'laws'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'articles'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'kokuji_notices'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'kokuji_notice_errors'").fetchone()
            )
            self.assertEqual(fts_enabled, has_kokuji_fts_table(conn))
        finally:
            conn.close()

    def test_ensure_kokuji_schema_skips_fts_when_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with mock.patch("kokuji_database.supports_fts5", return_value=False):
                enabled = ensure_kokuji_schema(conn, rebuild_fts=True)
            self.assertFalse(enabled)
            self.assertFalse(has_kokuji_fts_table(conn))
        finally:
            conn.close()

    def test_process_notice_preserves_existing_full_text_on_fetch_error(self):
        row = NoticeRow(
            notice_name="準不燃材料を定める件",
            document_number="国土交通省告示第1号",
            document_date="2026-01-01",
            organization="国土交通省住宅局建築指導課",
            url="https://example.com/test.pdf",
            match_reason="seed",
        )
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = connect_db(tf.name)
            try:
                ensure_kokuji_schema(conn, rebuild_fts=False)
                notice_id = upsert_notice(conn, row, "2026-01-01T00:00:00+00:00")
                update_notice_status(
                    conn,
                    notice_id,
                    fetch_status="fetch_ok",
                    text_status="text_ok",
                    full_text="old text",
                    text_char_count=8,
                    page_count=3,
                    now_iso="2026-01-01T00:00:00+00:00",
                )
                conn.commit()

                with mock.patch("kokuji_database.fetch_notice_document", side_effect=RuntimeError("boom")):
                    fetch_status, text_status, char_count, page_count = process_notice(
                        conn,
                        row,
                        fts_enabled=False,
                    )

                stored = conn.execute(
                    """
                    SELECT full_text, text_char_count, page_count, fetch_status, text_status
                    FROM kokuji_notices
                    WHERE id = ?
                    """,
                    (notice_id,),
                ).fetchone()
                error_count = conn.execute(
                    "SELECT COUNT(*) FROM kokuji_notice_errors WHERE notice_id = ?",
                    (notice_id,),
                ).fetchone()[0]
            finally:
                conn.close()

        self.assertEqual((fetch_status, text_status), ("fetch_error", "skipped"))
        self.assertEqual((char_count, page_count), (8, 3))
        self.assertEqual(stored["full_text"], "old text")
        self.assertEqual(stored["text_char_count"], 8)
        self.assertEqual(stored["page_count"], 3)
        self.assertEqual(stored["fetch_status"], "fetch_error")
        self.assertEqual(stored["text_status"], "skipped")
        self.assertEqual(error_count, 1)

    def test_search_kokuji_uses_like_search(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = connect_db(tf.name)
            try:
                ensure_kokuji_schema(conn, rebuild_fts=False)
                conn.execute(
                    """
                    INSERT INTO kokuji_notices(
                        notice_name, document_number, document_date, organization, url,
                        match_reason, fetch_status, text_status, full_text,
                        text_char_count, page_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "準不燃材料を定める件",
                        "国土交通省告示第1号",
                        "2026-01-01",
                        "国土交通省住宅局建築指導課",
                        "https://example.com/jun.pdf",
                        "seed",
                        "fetch_ok",
                        "text_ok",
                        "この告示は準不燃材料と建築物の内装制限を定める。",
                        27,
                        2,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            payload = search_kokuji(pathlib.Path(tf.name), query="準不燃", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["search_mode"], "like")
        self.assertEqual(payload["results"][0]["notice_name"], "準不燃材料を定める件")
        self.assertIn("準不燃", payload["results"][0]["snippet"])

    def test_make_kokuji_csv_reports_missing_input_clearly(self):
        missing_path = ROOT / "data" / "does_not_exist_001992597.xlsx"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "make_kokuji_csv.py"),
                "--input-xlsx",
                str(missing_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Input workbook not found.", result.stdout)
        self.assertIn(str(missing_path), result.stdout)
        self.assertIn("data/001992597.xlsx", result.stdout)


if __name__ == "__main__":
    unittest.main()

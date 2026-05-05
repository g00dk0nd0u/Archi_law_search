"""Regression tests for search-only kokuji integration."""

from __future__ import annotations

import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from kokuji_database import connect_db, search_kokuji  # type: ignore
from source_registry import ensure_source_registry, is_source_active, set_source_active  # type: ignore


def create_sample_kokuji_db(db_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE notices (
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
                text_char_count INTEGER DEFAULT 0,
                page_count INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE notice_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id INTEGER,
                url TEXT,
                phase TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notices(
                notice_name, document_number, document_date, organization, url,
                match_reason, fetch_status, text_status, full_text,
                text_char_count, page_count, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()
    finally:
        conn.close()


class KokujiIntegrationTests(unittest.TestCase):
    def test_search_kokuji_uses_like_search(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name))
            payload = search_kokuji(pathlib.Path(tf.name), query="準不燃", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["search_mode"], "like")
        self.assertEqual(payload["results"][0]["notice_name"], "準不燃材料を定める件")
        self.assertIn("準不燃", payload["results"][0]["snippet"])

    def test_import_kokuji_db_copies_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            source_db = tmp_path / "source_kokuji.db"
            dest_db = tmp_path / "dest_kokuji.db"
            registry_db = tmp_path / "laws.db"
            create_sample_kokuji_db(source_db)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "import_kokuji_db.py"),
                    "--source",
                    str(source_db),
                    "--dest",
                    str(dest_db),
                    "--registry-db",
                    str(registry_db),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertTrue(dest_db.exists())
            conn = connect_db(dest_db)
            try:
                count = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)
            self.assertIn("Imported kokuji DB:", result.stdout)
            self.assertIn("notices: 1", result.stdout)

    def test_import_kokuji_db_fails_when_required_tables_are_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            source_db = tmp_path / "broken.db"
            sqlite3.connect(str(source_db)).close()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "import_kokuji_db.py"),
                    "--source",
                    str(source_db),
                    "--dest",
                    str(tmp_path / "dest.db"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required tables", result.stdout)

    def test_source_registry_can_toggle_active_state(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            db_path = pathlib.Path(tf.name)
            conn = sqlite3.connect(str(db_path))
            try:
                conn.row_factory = sqlite3.Row
                ensure_source_registry(conn)
                conn.commit()
            finally:
                conn.close()

            self.assertTrue(is_source_active("kokuji", db_path))
            set_source_active("kokuji", False, db_path)
            self.assertFalse(is_source_active("kokuji", db_path))
            set_source_active("kokuji", True, db_path)
            self.assertTrue(is_source_active("kokuji", db_path))

    def test_cli_search_kokuji_returns_inactive_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            kokuji_db = tmp_path / "kokuji.db"
            registry_db = tmp_path / "laws.db"
            create_sample_kokuji_db(kokuji_db)
            conn = sqlite3.connect(str(registry_db))
            try:
                conn.row_factory = sqlite3.Row
                ensure_source_registry(conn)
                conn.commit()
            finally:
                conn.close()
            set_source_active("kokuji", False, registry_db)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli.search_kokuji",
                    "--db",
                    str(kokuji_db),
                    "--registry-db",
                    str(registry_db),
                    "--query",
                    "建築物",
                    "--limit",
                    "10",
                    "--json-pretty",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn('"inactive": true', result.stdout.lower())
            self.assertIn("kokuji source is inactive", result.stdout)


if __name__ == "__main__":
    unittest.main()

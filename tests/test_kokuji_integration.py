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
from source_registry import ensure_source_registry, get_source_status, is_source_active, set_source_active  # type: ignore
from web_app import LawSearchHandler  # type: ignore


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
                "防火設備の構造方法を定める件",
                "国土交通省告示第二百九十四号",
                "2026-02-01",
                "国土交通省住宅局建築指導課",
                "https://example.com/294.pdf",
                "seed",
                "fetch_ok",
                "text_ok",
                "この告示は防火設備の構造方法を定め、第二百九十四号として公布された。",
                40,
                1,
                "2026-02-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


class KokujiIntegrationTests(unittest.TestCase):
    def _make_handler(self, laws_db: pathlib.Path, kokuji_db: pathlib.Path):
        handler = object.__new__(LawSearchHandler)
        handler.db_path = str(laws_db)
        handler.kokuji_db_path = str(kokuji_db)
        handler.render_table = LawSearchHandler.render_table.__get__(handler, LawSearchHandler)
        handler.render_results = LawSearchHandler.render_results.__get__(handler, LawSearchHandler)
        captured: dict[str, str] = {}

        def fake_send_html(body: bytes):
            captured["html"] = body.decode("utf-8")

        handler._send_html = fake_send_html
        return handler, captured

    def test_search_kokuji_uses_like_search(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name))
            payload = search_kokuji(pathlib.Path(tf.name), query="準不燃", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["search_mode"], "like")
        self.assertEqual(payload["results"][0]["notice_name"], "準不燃材料を定める件")
        self.assertIn("準不燃", payload["results"][0]["snippet"])

    def test_search_kokuji_matches_notice_number_variants(self):
        queries = ["294", "294号", "告示第294号", "防火設備"]
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name))
            for query in queries:
                payload = search_kokuji(pathlib.Path(tf.name), query=query, limit=10)
                self.assertGreaterEqual(payload["count"], 1, query)
                self.assertTrue(
                    any(result["document_number"] == "国土交通省告示第二百九十四号" for result in payload["results"]),
                    query,
                )
                self.assertTrue(payload["highlight_terms"])

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
            self.assertEqual(count, 2)
            self.assertIn("Imported kokuji DB:", result.stdout)
            self.assertIn("notices: 2", result.stdout)

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
            self.assertTrue(get_source_status("kokuji", db_path)["is_active"])

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

    def test_web_ui_defaults_to_law_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": ""})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn('name="source" value="law" checked', captured["html"])
            self.assertNotIn('name="source" value="kokuji" checked', captured["html"])

    def test_web_ui_keeps_law_search_results_for_source_law(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            rows, warning = LawSearchHandler.search_law_inputs(handler, "", "容積率")

            self.assertEqual(warning, "")
            self.assertGreater(len(rows), 0)
            self.assertIn("容積率", rows[0][2] + rows[0][3])

    def test_web_ui_returns_kokuji_results_for_source_kokuji(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": "q=%E6%BA%96%E4%B8%8D%E7%87%83&source=kokuji"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn("材料を定める件", captured["html"])
            self.assertIn(">告示<", captured["html"])
            self.assertIn("国土交通省告示第1号", captured["html"])
            self.assertIn("name=\"source\" value=\"kokuji\" checked", captured["html"])
            self.assertNotIn("<th>条</th>", captured["html"])
            self.assertNotIn("<th>機関</th>", captured["html"])
            self.assertIn("<mark>準不燃</mark>", captured["html"])
            self.assertIn("告示番号・キーワード", captured["html"])

    def test_web_ui_kokuji_number_search_highlights_notice_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": "q=294%E5%8F%B7&source=kokuji"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn("国土交通省<mark>告示第二百九十四号</mark>", captured["html"])
            self.assertIn("防火設備", captured["html"])
            self.assertIn("<mark>第二百九十四号</mark>", captured["html"])
            self.assertNotIn("<th>機関</th>", captured["html"])

    def test_missing_source_param_and_invalid_source_fall_back_to_law(self):
        self.assertEqual(LawSearchHandler._parse_source("q=%E6%BA%96%E4%B8%8D%E7%87%83"), "law")
        self.assertEqual(LawSearchHandler._parse_source("q=%E6%BA%96%E4%B8%8D%E7%87%83&source=invalid"), "law")

    def test_missing_kokuji_db_disables_switch_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            sqlite3.connect(str(laws_db)).close()
            missing_kokuji_db = tmp_path / "missing.db"

            handler, captured = self._make_handler(laws_db, missing_kokuji_db)
            parsed = type("Parsed", (), {"query": "q=%E6%BA%96%E4%B8%8D%E7%87%83&source=kokuji"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn("告示DBが見つかりません", captured["html"])
            self.assertIn('value="kokuji" disabled', captured["html"])
            self.assertIn('value="law" checked', captured["html"])

    def test_inactive_kokuji_source_blocks_kokuji_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)
            conn = sqlite3.connect(str(laws_db))
            try:
                conn.row_factory = sqlite3.Row
                ensure_source_registry(conn)
                conn.commit()
            finally:
                conn.close()
            set_source_active("kokuji", False, laws_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": "q=%E6%BA%96%E4%B8%8D%E7%87%83&source=kokuji"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn("告示検索は現在無効です", captured["html"])
            self.assertIn('value="kokuji" disabled', captured["html"])
            self.assertIn('value="law" checked', captured["html"])


if __name__ == "__main__":
    unittest.main()

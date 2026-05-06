"""Regression tests for search-only kokuji integration."""

from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from kokuji_database import connect_db, search_kokuji  # type: ignore
from source_registry import ensure_source_registry, get_source_status, is_source_active, set_source_active  # type: ignore
from web_app import LawSearchHandler  # type: ignore


def create_sample_kokuji_db(db_path: pathlib.Path, *, with_native_number_columns: bool = False) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        extra_columns = ""
        insert_columns = ""
        first_extra_values: tuple[object, ...] = ()
        second_extra_values: tuple[object, ...] = ()
        if with_native_number_columns:
            extra_columns = """
                document_number_norm TEXT,
                document_number_digits TEXT,
                content_type TEXT,
            """
            insert_columns = "document_number_norm, document_number_digits, content_type,"
            first_extra_values = ("第1号", "1", "application/pdf")
            second_extra_values = ("第1436号", "1436", "application/pdf")
        conn.execute(
            """
            CREATE TABLE notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_name TEXT NOT NULL,
                document_number TEXT,
                """
            + extra_columns
            + """
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
                notice_name, document_number, """
            + insert_columns
            + """ document_date, organization, url,
                match_reason, fetch_status, text_status, full_text,
                text_char_count, page_count, updated_at
            )
            VALUES (?, ?, """
            + ("?, ?, ?, " if with_native_number_columns else "")
            + """?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "準不燃材料を定める件",
                "国土交通省告示第1号",
                *first_extra_values,
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
                notice_name, document_number, """
            + insert_columns
            + """ document_date, organization, url,
                match_reason, fetch_status, text_status, full_text,
                text_char_count, page_count, updated_at
            )
            VALUES (?, ?, """
            + ("?, ?, ?, " if with_native_number_columns else "")
            + """?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "防火設備の構造方法を定める件",
                "国土交通省告示第千四百三十六号",
                *second_extra_values,
                "2026-02-01",
                "国土交通省住宅局建築指導課",
                "https://example.com/1436.pdf",
                "seed",
                "fetch_ok",
                "text_ok",
                "この告示は防火設備および排煙に関する構造方法を定め、第千四百三十六号として公布された。",
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
        queries = ["1436", "1436号", "告示第1436号", "建設省告示第1436号", "国土交通省告示第1436号"]
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name), with_native_number_columns=True)
            for query in queries:
                payload = search_kokuji(pathlib.Path(tf.name), notice_number=query, limit=10)
                self.assertGreaterEqual(payload["count"], 1, query)
                self.assertTrue(
                    any(result["document_number"] == "国土交通省告示第千四百三十六号" for result in payload["results"]),
                    query,
                )
                self.assertTrue(payload["highlight_terms"])
                self.assertEqual(payload["results"][0]["display_document_number"], "第1436号")

    def test_search_kokuji_combines_notice_number_and_keyword(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name), with_native_number_columns=True)
            payload = search_kokuji(pathlib.Path(tf.name), query="排煙", notice_number="1436", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["display_document_number"], "第1436号")
        self.assertIn("排煙", payload["results"][0]["snippet"])

    def test_search_kokuji_old_db_fallback_still_works(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            create_sample_kokuji_db(pathlib.Path(tf.name), with_native_number_columns=False)
            payload = search_kokuji(pathlib.Path(tf.name), notice_number="1436", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["document_number"], "国土交通省告示第千四百三十六号")
        self.assertEqual(payload["results"][0]["document_date"], "2026-02-01")

    def test_search_kokuji_old_db_without_document_date_column_does_not_crash(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            db_path = pathlib.Path(tf.name)
            create_sample_kokuji_db(db_path, with_native_number_columns=False)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executescript(
                    """
                    ALTER TABLE notices RENAME TO notices_old;
                    CREATE TABLE notices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        notice_name TEXT NOT NULL,
                        document_number TEXT,
                        organization TEXT,
                        url TEXT UNIQUE,
                        match_reason TEXT,
                        fetch_status TEXT,
                        text_status TEXT,
                        full_text TEXT,
                        text_char_count INTEGER DEFAULT 0,
                        page_count INTEGER DEFAULT 0,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO notices (
                        id, notice_name, document_number, organization, url,
                        match_reason, fetch_status, text_status, full_text,
                        text_char_count, page_count, updated_at
                    )
                    SELECT
                        id, notice_name, document_number, organization, url,
                        match_reason, fetch_status, text_status, full_text,
                        text_char_count, page_count, updated_at
                    FROM notices_old;
                    DROP TABLE notices_old;
                    """
                )
            payload = search_kokuji(db_path, notice_number="1436", limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["document_date"], "")

    def test_search_kokuji_cli_supports_notice_number_option(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            kokuji_db = tmp_path / "kokuji.db"
            registry_db = tmp_path / "laws.db"
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)
            conn = sqlite3.connect(str(registry_db))
            try:
                conn.row_factory = sqlite3.Row
                ensure_source_registry(conn)
                conn.commit()
            finally:
                conn.close()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli.search_kokuji",
                    "--db",
                    str(kokuji_db),
                    "--registry-db",
                    str(registry_db),
                    "--notice-number",
                    "1436",
                    "--limit",
                    "10",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn('"notice_number": "1436"', result.stdout)

    def test_handle_search_page_accepts_article_as_notice_number_in_kokuji_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            laws_db.touch()
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)
            handler, captured = self._make_handler(laws_db, kokuji_db)

            parsed = type("Parsed", (), {"query": "source=kokuji&article=1436&q=%E6%8E%92%E7%85%99"})()
            LawSearchHandler._handle_search_page(handler, parsed)

        self.assertIn("第<mark>1436</mark>号", captured["html"])
        self.assertIn("class='kokuji-link-button'", captured["html"])
        self.assertIn(">PDF<", captured["html"])
        self.assertNotIn("種別", captured["html"])

    def test_handle_search_page_accepts_notice_number_when_switching_back_to_law_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)
            handler, captured = self._make_handler(laws_db, kokuji_db)

            parsed = type("Parsed", (), {"query": "source=law&notice_number=112&q=%E9%98%B2%E7%81%AB"})()
            LawSearchHandler._handle_search_page(handler, parsed)

        self.assertIn('name="article" value="112"', captured["html"])
        self.assertIn('name="source" value="law" checked', captured["html"])

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
                    str(ROOT / "internal_tools" / "import_kokuji_db.py"),
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
                    str(ROOT / "internal_tools" / "import_kokuji_db.py"),
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
            self.assertIn("国土交通省告示<br>第1号", captured["html"])
            self.assertIn("name=\"source\" value=\"kokuji\" checked", captured["html"])
            self.assertNotIn("<th>条</th>", captured["html"])
            self.assertNotIn("<th>機関</th>", captured["html"])
            self.assertIn("<th>本文</th>", captured["html"])
            self.assertIn("<mark>準不燃</mark>", captured["html"])
            self.assertIn("告示番号", captured["html"])
            self.assertIn("検索キーワード", captured["html"])
            self.assertIn("<div class='kokuji-meta'>国土交通省住宅局建築指導課</div>", captured["html"])
            self.assertIn("<div class='kokuji-meta kokuji-year'>2026年</div>", captured["html"])
            self.assertIn("class='kokuji-link-button'", captured["html"])
            self.assertIn(">PDF<", captured["html"])
            self.assertIn("class='copy-button kokuji-copy-button'", captured["html"])
            self.assertIn("class='body-preview'", captured["html"])
            self.assertLess(captured["html"].index(">PDF<"), captured["html"].index("class='copy-button kokuji-copy-button'"))
            self.assertIn(">TXT保存<", captured["html"])

    def test_web_ui_law_results_show_txt_download_button(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": "article=112&q=%E9%98%B2%E7%81%AB&source=law"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn(">TXT保存<", captured["html"])
            self.assertIn("/export_results?source=law", captured["html"])

    def test_web_ui_kokuji_number_search_highlights_notice_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)

            handler, captured = self._make_handler(laws_db, kokuji_db)
            parsed = type("Parsed", (), {"query": "notice_number=1436%E5%8F%B7&source=kokuji"})()
            LawSearchHandler._handle_search_page(handler, parsed)

            self.assertIn("国土交通省告示<br>第千四百三十六号", captured["html"])
            self.assertIn("<mark>第千四百三十六号</mark>", captured["html"])
            self.assertNotIn("<mark>第</mark>", captured["html"])
            self.assertIn("防火設備", captured["html"])
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
            self.assertIn('name="source" value="kokuji" checked disabled', captured["html"])
            self.assertIn("告示DBが未作成です。", captured["html"])

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
            self.assertIn('name="source" value="kokuji" checked disabled', captured["html"])
            self.assertIn("告示検索は現在無効です。", captured["html"])

    def test_kokuji_text_api_returns_full_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            payload_holder: dict[str, object] = {}

            def fake_send_json(payload, status=200):
                payload_holder["payload"] = payload
                payload_holder["status"] = status

            handler._send_json = fake_send_json
            parsed = type("Parsed", (), {"query": "id=1"})()
            LawSearchHandler._handle_kokuji_text_api(handler, parsed)

            self.assertEqual(payload_holder["status"], 200)
            payload = payload_holder["payload"]
            self.assertEqual(payload["row_id"], "1")
            self.assertIn("準不燃材料", payload["notice_name"])
            self.assertIn("準不燃材料", payload["full_text"])

    def test_save_results_txt_uses_output_exports_latest_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            exports_dir = tmp_path / "output" / "exports"
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            handler.DEFAULT_EXPORTS_DIR = exports_dir

            law_path, law_count = LawSearchHandler._save_results_txt(
                handler,
                source="law",
                article_query="",
                notice_number_query="",
                body_query="容積率",
            )
            kokuji_path, kokuji_count = LawSearchHandler._save_results_txt(
                handler,
                source="kokuji",
                article_query="",
                notice_number_query="1436",
                body_query="排煙",
            )
            law_path_2, _law_count_2 = LawSearchHandler._save_results_txt(
                handler,
                source="law",
                article_query="",
                notice_number_query="",
                body_query="容積率",
            )

            self.assertEqual(law_path.parent, exports_dir)
            self.assertEqual(kokuji_path.parent, exports_dir)
            self.assertEqual(law_path.name, "latest_law_search.txt")
            self.assertEqual(kokuji_path.name, "latest_kokuji_search.txt")
            self.assertEqual(law_path_2, law_path)
            self.assertTrue(law_path.exists())
            self.assertTrue(kokuji_path.exists())
            self.assertGreater(law_count, 0)
            self.assertGreater(kokuji_count, 0)
            self.assertIn("法令検索結果", law_path.read_text(encoding="utf-8"))
            self.assertIn("告示検索結果", kokuji_path.read_text(encoding="utf-8"))
            self.assertIn("organization:", kokuji_path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(path.name for path in exports_dir.iterdir()), ["latest_kokuji_search.txt", "latest_law_search.txt"])

    def test_save_results_txt_law_matches_screen_search_count_for_fullwidth_space_and(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            exports_dir = tmp_path / "output" / "exports"
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            handler.DEFAULT_EXPORTS_DIR = exports_dir

            screen_rows, warning = LawSearchHandler.search_law_inputs(handler, "", "耐火　不燃")
            law_path, law_count = LawSearchHandler._save_results_txt(
                handler,
                source="law",
                article_query="",
                notice_number_query="",
                body_query="耐火　不燃",
            )

            self.assertEqual(warning, "")
            self.assertGreater(len(screen_rows), 0)
            self.assertEqual(law_count, len(screen_rows))
            text = law_path.read_text(encoding="utf-8")
            self.assertIn(f"件数: {len(screen_rows)}", text)
            self.assertNotIn("<mark>", text)

    def test_fetch_law_download_rows_supports_article_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            shutil.copyfile(ROOT / "data" / "laws.db", laws_db)
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            rows = LawSearchHandler._fetch_law_download_rows(handler, "6", "")

            self.assertGreater(len(rows), 0)
            self.assertEqual(rows[0]["source"], "laws.db")
            self.assertTrue(rows[0]["article_number"].endswith("条"))

    def test_handle_export_results_opens_exports_and_redirects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            laws_db = tmp_path / "laws.db"
            kokuji_db = tmp_path / "kokuji.db"
            sqlite3.connect(str(laws_db)).close()
            create_sample_kokuji_db(kokuji_db, with_native_number_columns=True)

            handler, _captured = self._make_handler(laws_db, kokuji_db)
            sent: dict[str, object] = {}

            def fake_send_response(code):
                sent["code"] = code

            def fake_send_header(name, value):
                sent.setdefault("headers", {})[name] = value

            handler.send_response = fake_send_response
            handler.send_header = fake_send_header
            handler.end_headers = lambda: sent.setdefault("ended", True)

            export_path = tmp_path / "output" / "exports" / "latest_kokuji_search.txt"
            with mock.patch.object(handler, "_save_results_txt", return_value=(export_path, 1)) as save_mock:
                with mock.patch.object(handler, "_open_exports_folder") as open_mock:
                    parsed = type("Parsed", (), {"query": "notice_number=1436&q=%E6%8E%92%E7%85%99&source=kokuji"})()
                    LawSearchHandler._handle_export_results(handler, parsed)

            save_mock.assert_called_once()
            open_mock.assert_called_once_with(export_path.parent)
            self.assertEqual(sent["code"], 303)
            self.assertIn("Location", sent["headers"])
            self.assertIn("message=TXT%E3%82%92%E4%BF%9D%E5%AD%98%E3%81%97%E3%81%BE%E3%81%97%E3%81%9F", sent["headers"]["Location"])
            self.assertIn("output%2Fexports%2Flatest_kokuji_search.txt", sent["headers"]["Location"])


if __name__ == "__main__":
    unittest.main()

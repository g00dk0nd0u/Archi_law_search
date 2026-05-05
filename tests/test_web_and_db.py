"""SQLite取り込み・検索UI・通信補助の回帰を確認するテスト群。"""

from __future__ import annotations

import pathlib
import json
import sqlite3
import subprocess
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.append(str(ROOT / "src"))

from law_database import (  # type: ignore
    LawSource,
    _article_sort_key,
    delete_law,
    ensure_db,
    fts5_enabled,
    has_fts5_table,
    init_db,
    iter_articles,
    list_installed_law_ids,
    replace_law,
    supports_fts5,
    upsert_law,
)
from law_registry import DEFAULT_LAWS, LAW_REGISTRY  # type: ignore
import laws_api  # type: ignore
from web_app import SEARCH_PAGE_TEMPLATE, SETTINGS_PAGE_TEMPLATE, LawSearchHandler, build_server_url, open_browser  # type: ignore
from cli.search_laws import search_laws as cli_search_laws  # type: ignore
from cli.search_laws import build_txt_export_text, export_results_txt  # type: ignore


def _maybe_fts_count(conn):
    if not has_fts5_table(conn):
        return None
    return conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]


SAMPLE_MAIN_XML = """
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第1条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>耐火構造について定める。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第2条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>一般構造に関する規定。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第2条の2</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>防火設備と排煙に関する規定。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第6条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>建築物の建築等に関する申請及び確認。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
    <SupplProvision AmendLawNum="令和六年法律第十号">
      <SupplProvisionLabel>附則</SupplProvisionLabel>
      <Article>
        <ArticleTitle>第6条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>罰則に関する経過措置。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </SupplProvision>
  </LawBody>
</Root>
"""


SAMPLE_ORDER_XML = """
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第6条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>建築基準法施行令の第六条本文。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""


SAMPLE_UPDATED_XML = """
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第1条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>更新後の本文。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""


SAMPLE_HEADING_XML = """
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第27条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>（耐火建築物等としなければならない特殊建築物）劇場、映画館その他の特殊建築物は耐火構造としなければならない。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""


SAMPLE_KANJI_ORDER_XML = """
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第七十七条の二十</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の二十。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の二十一</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の二十一。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の二十四</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の二十四。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十一</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十一。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十二</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十二。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十四</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十四。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十五の四</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十五の四。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
      <Article>
        <ArticleTitle>第七十七条の三十六</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>確認の三十六。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""


class DatabaseAndWebTests(unittest.TestCase):
    def test_ca_bundle_path_exists(self):
        ca_bundle_path = laws_api.get_ca_bundle_path()
        self.assertTrue(ca_bundle_path.exists())
        self.assertEqual(ca_bundle_path.name, "cacert.pem")

    def test_create_ssl_context_uses_repo_ca_bundle(self):
        with mock.patch("laws_api.ssl.create_default_context", return_value="ctx") as create_default_context:
            context = laws_api.create_ssl_context()
        self.assertEqual(context, "ctx")
        create_default_context.assert_called_once_with(cafile=str(laws_api.get_ca_bundle_path()))

    def test_create_ssl_context_raises_when_ca_bundle_missing(self):
        missing_path = pathlib.Path("/tmp/does-not-exist-cacert.pem")
        with mock.patch("laws_api.get_ca_bundle_path", return_value=missing_path):
            with self.assertRaises(FileNotFoundError):
                laws_api.create_ssl_context()

    def test_build_server_url(self):
        self.assertEqual(build_server_url("127.0.0.1", 8765), "http://127.0.0.1:8765")

    def test_open_browser_calls_webbrowser_open(self):
        called = []

        def fake_open(url):
            called.append(url)
            return True

        with mock.patch("web_app.webbrowser.open", side_effect=fake_open):
            open_browser("http://127.0.0.1:8765", delay_seconds=0)
            for _ in range(20):
                if called:
                    break
                time.sleep(0.01)

        self.assertEqual(called, ["http://127.0.0.1:8765"])

    def test_open_browser_swallows_webbrowser_errors(self):
        with mock.patch("web_app.webbrowser.open", side_effect=RuntimeError("boom")):
            open_browser("http://127.0.0.1:8765", delay_seconds=0)
            time.sleep(0.05)

    def test_upsert_creates_and_updates_articles(self):
        root = ET.fromstring(SAMPLE_MAIN_XML)
        source = LawSource("X001", "建築基準法")
        conn = sqlite3.connect(":memory:")
        try:
            init_db(conn)

            inserted = upsert_law(conn, source, root)
            self.assertEqual(inserted, 5)

            count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            self.assertEqual(count, 5)
            if supports_fts5(conn):
                self.assertEqual(_maybe_fts_count(conn), 5)
            else:
                self.assertIsNone(_maybe_fts_count(conn))

            # 同一データの再投入でも件数は増えない（upsert）
            inserted2 = upsert_law(conn, source, root)
            self.assertEqual(inserted2, 5)
            count2 = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            self.assertEqual(count2, 5)

            rows = conn.execute(
                """
                SELECT article_no, provision_kind, amend_law_num
                FROM articles
                WHERE article_no = '第6条'
                ORDER BY provision_kind
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("第6条", "main", ""),
                    ("第6条", "suppl", "令和六年法律第十号"),
                ],
            )
        finally:
            conn.close()

    def test_ensure_db_skips_fts_objects_when_fts5_is_unavailable(self):
        conn = sqlite3.connect(":memory:")
        try:
            with mock.patch("law_database.supports_fts5", return_value=False):
                ensure_db(conn)

            self.assertFalse(has_fts5_table(conn))
            trigger_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'articles_a%'"
                ).fetchall()
            }
            self.assertEqual(trigger_names, set())
        finally:
            conn.close()

    def test_search_body_falls_back_to_like_only_when_fts5_is_unavailable(self):
        root = ET.fromstring(SAMPLE_MAIN_XML)
        source = LawSource("X900", "建築基準法")

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            with mock.patch("law_database.supports_fts5", return_value=False):
                ensure_db(conn)
                upsert_law(conn, source, root)
                conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            with mock.patch("web_app.fts5_enabled", return_value=False):
                rows, warning = LawSearchHandler.search_body(handler, "耐火")
                rows_missing, warning_missing = LawSearchHandler.search_body(handler, "(")

        self.assertEqual(warning, "")
        self.assertEqual(len(rows), 1)
        self.assertIn("<mark>耐火</mark>", rows[0][2])
        self.assertEqual(rows_missing, [])
        self.assertEqual(warning_missing, "")

    def test_iter_articles_separates_main_and_suppl(self):
        root = ET.fromstring(SAMPLE_MAIN_XML)
        articles = list(iter_articles(root))
        article_sixes = [(article.article_no, article.provision_kind, article.amend_law_num) for article in articles if article.article_no == "第6条"]
        self.assertEqual(
            article_sixes,
            [
                ("第6条", "main", ""),
                ("第6条", "suppl", "令和六年法律第十号"),
            ],
        )

    def test_web_search_and_html_safety(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)
        order_root = ET.fromstring(SAMPLE_ORDER_XML)
        main_source = LawSource("X001", "建築基準法")
        order_source = LawSource("X002", "建築基準法施行令")

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, main_source, main_root)
            upsert_law(conn, order_source, order_root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_article(handler, "第1条")
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(warning, "")
            self.assertEqual(rows[0][1], "第1条")
            self.assertEqual(rows[0][0], "建築基準法")

            rows_number, warning_number = LawSearchHandler.search_article(handler, "1")
            self.assertGreaterEqual(len(rows_number), 1)
            self.assertEqual(rows_number[0][1], "第1条")
            self.assertEqual(warning_number, "")

            rows_base, warning_base = LawSearchHandler.search_article(handler, "2")
            self.assertEqual([row[1] for row in rows_base], ["第2条", "第2条の2"])
            self.assertEqual(warning_base, "")

            rows_branch, warning_branch = LawSearchHandler.search_article(handler, "２-２")
            self.assertGreaterEqual(len(rows_branch), 1)
            self.assertEqual(rows_branch[0][1], "第2条の2")
            self.assertEqual(len(rows_branch), 1)
            self.assertEqual(warning_branch, "")

            rows_kanji, warning_kanji = LawSearchHandler.search_article(handler, "二の二")
            self.assertGreaterEqual(len(rows_kanji), 1)
            self.assertEqual(rows_kanji[0][1], "第2条の2")
            self.assertEqual(len(rows_kanji), 1)
            self.assertEqual(warning_kanji, "")

            rows_filtered, warning_filtered = LawSearchHandler.search_article_with_body_keyword(handler, "2", "煙")
            self.assertEqual([row[1] for row in rows_filtered], ["第2条の2"])
            self.assertEqual(warning_filtered, "")
            self.assertIn("<mark>煙</mark>", rows_filtered[0][2])
            self.assertEqual(rows_filtered[0][0], "建築基準法")

            rows_six, warning_six = LawSearchHandler.search_article(handler, "6")
            self.assertEqual(warning_six, "")
            self.assertEqual(
                [(row[0], row[1]) for row in rows_six[:2]],
                [("建築基準法", "第6条"), ("建築基準法施行令", "第6条")],
            )
            self.assertIn("建築物の建築等に関する申請及び確認。", rows_six[0][2])
            self.assertIn("建築基準法施行令の第六条本文。", rows_six[1][2])
            self.assertNotIn("建築基準法・附則", [row[0] for row in rows_six])

            # 日本語の部分一致でもヒットする
            rows_partial, warning_partial = LawSearchHandler.search_body(handler, "耐火")
            self.assertGreaterEqual(len(rows_partial), 1)
            self.assertEqual(warning_partial, "")
            self.assertIn("<mark>耐火</mark>", rows_partial[0][2])
            self.assertEqual(rows_partial[0][0], "建築基準法")

            rows_suppl_only, warning_suppl_only = LawSearchHandler.search_body(handler, "罰則")
            self.assertEqual(rows_suppl_only, [])
            self.assertEqual(warning_suppl_only, "")

            rows_legacy, warning_legacy = LawSearchHandler.search(handler, "耐火")
            self.assertGreaterEqual(len(rows_legacy), 1)
            self.assertEqual(warning_legacy, "")

            # 記号クエリで構文エラーが出てもフレーズ検索にフォールバック
            rows2, warning2 = LawSearchHandler.search_body(handler, "(")
            self.assertIsInstance(rows2, list)
            probe_conn = sqlite3.connect(":memory:")
            try:
                fts_supported = supports_fts5(probe_conn)
            finally:
                probe_conn.close()
            if fts_supported:
                self.assertEqual(warning2, "クエリをフレーズ検索に変換")
            else:
                self.assertEqual(warning2, "")

            # snippet中のHTMLはエスケープされる（markタグのみ許可）
            unsafe = "<script>alert(1)</script><mark>耐火</mark>"
            safe = LawSearchHandler._safe_snippet(unsafe)
            self.assertIn("&lt;script&gt;", safe)
            self.assertIn("<mark>耐火</mark>", safe)

    def test_article_sort_key_supports_kanji_article_numbers(self):
        self.assertEqual(_article_sort_key("第1条"), (1, 0))
        self.assertEqual(_article_sort_key("第2条の2"), (2, 2))
        self.assertEqual(_article_sort_key("第七十七条の二十"), (77, 20))
        self.assertEqual(_article_sort_key("第七十七条の三十"), (77, 30))
        self.assertLess(_article_sort_key("第七十七条の三十"), _article_sort_key("第七十七条の三十一"))
        self.assertLess(_article_sort_key("第七十七条の三十四"), _article_sort_key("第七十七条の三十五の四"))
        self.assertLess(_article_sort_key("第七十七条の三十五の四"), _article_sort_key("第七十七条の三十六"))

    def test_search_body_orders_kanji_article_numbers_numerically(self):
        kanji_root = ET.fromstring(SAMPLE_KANJI_ORDER_XML)
        source = LawSource("X003", "建築基準法")

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, source, kanji_root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_body(handler, "確認")

        self.assertEqual(warning, "")
        self.assertEqual(
            [row[1] for row in rows[:9]],
            [
                "第七十七条の二十",
                "第七十七条の二十一",
                "第七十七条の二十四",
                "第七十七条の三十",
                "第七十七条の三十一",
                "第七十七条の三十二",
                "第七十七条の三十四",
                "第七十七条の三十五の四",
                "第七十七条の三十六",
            ],
        )

    def test_cli_search_laws_prefers_exact_law_name_match(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)
        order_root = ET.fromstring(SAMPLE_ORDER_XML)

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, LawSource("X001", "建築基準法"), main_root)
            upsert_law(conn, LawSource("X002", "建築基準法施行令"), order_root)
            conn.commit()
            conn.close()

            payload = cli_search_laws(
                db_path=pathlib.Path(tf.name),
                law="建築基準法",
                article="第6条",
                limit=10,
            )

        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            {row["law_title"] for row in payload["results"]},
            {"建築基準法"},
        )

    def test_cli_search_laws_article_prefix_includes_branch_articles(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, LawSource("X001", "建築基準法"), main_root)
            conn.commit()
            conn.close()

            payload = cli_search_laws(
                db_path=pathlib.Path(tf.name),
                law="建築基準法",
                article="第2条",
                limit=10,
            )

        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [row["article_number"] for row in payload["results"]],
            ["第2条", "第2条の2"],
        )

    def test_cli_module_runs_with_python_m(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)
        order_root = ET.fromstring(SAMPLE_ORDER_XML)

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, LawSource("X001", "建築基準法"), main_root)
            upsert_law(conn, LawSource("X002", "建築基準法施行令"), order_root)
            conn.commit()
            conn.close()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli.search_laws",
                    "--db",
                    tf.name,
                    "--law",
                    "建築基準法",
                    "--article",
                    "第6条",
                    "--json",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            {row["law_title"] for row in payload["results"]},
            {"建築基準法"},
        )

    def test_cli_search_laws_can_export_txt_with_db_text_unchanged(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)

        with tempfile.NamedTemporaryFile(suffix=".db") as tf, tempfile.TemporaryDirectory() as td:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, LawSource("X001", "建築基準法"), main_root)
            conn.commit()
            conn.close()

            payload = cli_search_laws(
                db_path=pathlib.Path(tf.name),
                law="建築基準法",
                article="第1条",
                limit=10,
            )
            export_path = pathlib.Path(td) / "output" / "law_refs.txt"
            export_results_txt(export_path, payload)

            text = export_path.read_text(encoding="utf-8")

        self.assertIn("法令検索結果 原文一覧", text)
        self.assertIn("検索条件:", text)
        self.assertIn("- law: 建築基準法", text)
        self.assertIn("- article: 第1条", text)
        self.assertIn("【1】建築基準法 第1条", text)
        self.assertIn("耐火構造について定める。", text)

    def test_build_txt_export_text_handles_empty_results(self):
        text = build_txt_export_text(
            {
                "query": "存在しない語",
                "law": "",
                "law_id": "",
                "article": "",
                "limit": 20,
                "results": [],
            }
        )

        self.assertIn("- query: 存在しない語", text)
        self.assertIn("検索結果はありません。", text)

    def test_cli_module_export_txt_creates_output_and_hides_article_text_from_stdout(self):
        main_root = ET.fromstring(SAMPLE_MAIN_XML)

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, LawSource("X001", "建築基準法"), main_root)
            conn.commit()
            conn.close()

            export_path = ROOT / "output" / "law_refs.txt"
            if export_path.exists():
                export_path.unlink()
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli.search_laws",
                    "--db",
                    tf.name,
                    "--law",
                    "建築基準法",
                    "--article",
                    "第1条",
                    "--limit",
                    "10",
                    "--export-txt",
                    "law_refs.txt",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertTrue(export_path.exists())
                export_text = export_path.read_text(encoding="utf-8")
                self.assertIn("耐火構造について定める。", export_text)

                payload = json.loads(result.stdout)
                self.assertEqual(payload["count"], 1)
                self.assertEqual(payload["export_txt"], "output/law_refs.txt")
                self.assertEqual(
                    payload["results"],
                    [
                        {
                            "law_title": "建築基準法",
                            "article_number": "第1条",
                            "article_title": "",
                        }
                    ],
                )
                self.assertNotIn("article_text", result.stdout)
                self.assertNotIn("耐火構造について定める。", result.stdout)
            finally:
                if export_path.exists():
                    export_path.unlink()

    def test_default_registry_contains_only_three_initial_import_targets(self):
        self.assertEqual([law.law_name for law in DEFAULT_LAWS], ["建築基準法", "建築基準法施行令", "建築士法"])
        self.assertEqual(len(DEFAULT_LAWS), 3)

    def test_replace_and_delete_law_keep_registry_state_and_search_target_consistent(self):
        root = ET.fromstring(SAMPLE_MAIN_XML)
        source = LawSource("X100", "追加法令")

        conn = sqlite3.connect(":memory:")
        try:
            ensure_db(conn)

            count = replace_law(conn, source, root)
            self.assertEqual(count, 5)
            self.assertEqual(list_installed_law_ids(conn), {"X100"})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 5)
            if supports_fts5(conn):
                self.assertEqual(_maybe_fts_count(conn), 5)
            else:
                self.assertIsNone(_maybe_fts_count(conn))

            delete_law(conn, "X100")
            self.assertEqual(list_installed_law_ids(conn), set())
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 0)
            if supports_fts5(conn):
                self.assertEqual(_maybe_fts_count(conn), 0)
            else:
                self.assertIsNone(_maybe_fts_count(conn))
        finally:
            conn.close()

    def test_replace_law_refresh_removes_stale_articles(self):
        source = LawSource("X200", "更新法令")
        conn = sqlite3.connect(":memory:")
        try:
            ensure_db(conn)

            replace_law(conn, source, ET.fromstring(SAMPLE_MAIN_XML))
            replace_law(conn, source, ET.fromstring(SAMPLE_UPDATED_XML))

            rows = conn.execute(
                "SELECT article_no, body FROM articles WHERE law_id = ? ORDER BY article_no",
                ("X200",),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "第1条")
            self.assertIn("更新後の本文。", rows[0][1])
            if supports_fts5(conn):
                self.assertEqual(_maybe_fts_count(conn), 1)
            else:
                self.assertIsNone(_maybe_fts_count(conn))
        finally:
            conn.close()

    def test_parse_search_inputs_prioritizes_article_and_legacy_q_as_body(self):
        article_q, body_q = LawSearchHandler._parse_search_inputs("q=%E8%80%90%E7%81%AB")
        self.assertEqual(article_q, "")
        self.assertEqual(body_q, "耐火")

        article_q2, body_q2 = LawSearchHandler._parse_search_inputs(
            "article_q=%E7%AC%AC1%E6%9D%A1&body_q=%E8%80%90%E7%81%AB&q=%E9%98%B2%E7%81%AB"
        )
        self.assertEqual(article_q2, "第1条")
        self.assertEqual(body_q2, "耐火")

        mode, active_query = LawSearchHandler._select_search_query(article_q2, body_q2)
        self.assertEqual(mode, "article")
        self.assertEqual(active_query, "第1条")
        self.assertEqual(LawSearchHandler._parse_source("q=%E8%80%90%E7%81%AB"), "law")
        self.assertEqual(LawSearchHandler._parse_source("q=%E6%BA%96%E4%B8%8D%E7%87%83&source=kokuji"), "kokuji")
        self.assertEqual(LawSearchHandler._parse_source("source=invalid"), "law")

    def test_build_meta_handles_article_and_warning_cases(self):
        self.assertEqual(LawSearchHandler._build_meta([], ""), "0件ヒット")
        self.assertEqual(LawSearchHandler._build_meta([("建築基準法", "第1条", "本文", "本文")], ""), "1件ヒット")
        self.assertEqual(
            LawSearchHandler._build_meta([], "クエリをフレーズ検索に変換"),
            "0件ヒット（クエリをフレーズ検索に変換）",
        )

    def test_page_template_supports_realtime_search_script(self):
        html_doc = SEARCH_PAGE_TEMPLATE.format(
            query="耐火",
            law_checked=" checked",
            kokuji_checked="",
            kokuji_disabled="",
            source_note="",
            meta="1件ヒット",
            meta_actions="<button class='bulk-copy-button'>全結果をコピー</button>",
            table="<div>ok</div>",
        )
        self.assertIn('document.documentElement.dataset.theme = theme;', html_doc)
        self.assertIn('localStorage.getItem(THEME_STORAGE_KEY)', html_doc)
        self.assertIn('localStorage.setItem(THEME_STORAGE_KEY, theme);', html_doc)
        self.assertIn('prefers-color-scheme: dark', html_doc)
        self.assertIn('document.addEventListener("DOMContentLoaded"', html_doc)
        self.assertIn("compositionstart", html_doc)
        self.assertIn("compositionend", html_doc)
        self.assertIn("if (!queryValue) {", html_doc)
        self.assertIn("return true;", html_doc)
        self.assertIn("queryValue.length < 2", html_doc)
        self.assertIn("AUTO_SUBMIT_DELAY_MS = 700", html_doc)
        self.assertIn('querySelectorAll("td.body.is-expandable")', html_doc)
        self.assertIn('document.querySelectorAll("input[name=\'source\']")', html_doc)
        self.assertIn('navigator.clipboard.writeText', html_doc)
        self.assertIn('document.querySelectorAll(".copy-button")', html_doc)
        self.assertIn('document.querySelector(".bulk-copy-button")', html_doc)
        self.assertIn('feedback.textContent = "コピー済み"', html_doc)
        self.assertIn('feedback.hidden = false', html_doc)
        self.assertIn("meta-actions", html_doc)
        self.assertIn('class="theme-toggle"', html_doc)
        self.assertIn(">全結果をコピー<", html_doc)
        self.assertIn("--table-head-bg: #1a2e4a;", html_doc)
        self.assertIn("--table-head-text: #ffffff;", html_doc)
        self.assertIn("--mark-text: inherit;", html_doc)
        self.assertIn("--bg-color: #0d1117;", html_doc)
        self.assertIn("--surface-color: #161b22;", html_doc)
        self.assertIn("--table-head-bg: #21262d;", html_doc)
        self.assertIn("--table-head-text: #f0f6fc;", html_doc)
        self.assertIn("background: var(--table-head-bg);", html_doc)
        self.assertIn("color: var(--table-head-text);", html_doc)
        self.assertIn("color: var(--mark-text);", html_doc)
        self.assertIn("--mark-bg: #ffdca8;", html_doc)
        self.assertIn("html[data-theme=\"dark\"]", html_doc)
        self.assertIn("--mark-bg: #f2cc60;", html_doc)
        self.assertIn("--mark-text: #24292f;", html_doc)
        self.assertIn(">Settings<", html_doc)
        self.assertIn('value="law" checked', html_doc)
        self.assertIn(">告示<", html_doc)

    def test_settings_template_supports_notice_and_table_markup(self):
        html_doc = SETTINGS_PAGE_TEMPLATE.format(notice="<div>ok</div>", rows="<table><tbody></tbody></table>")
        self.assertIn("法令 Settings", html_doc)
        self.assertIn("検索へ戻る", html_doc)
        self.assertIn('class="theme-toggle"', html_doc)
        self.assertIn('localStorage.getItem(THEME_STORAGE_KEY)', html_doc)
        self.assertIn('localStorage.setItem(THEME_STORAGE_KEY, theme);', html_doc)
        self.assertIn('prefers-color-scheme: dark', html_doc)
        self.assertIn("html[data-theme=\"dark\"]", html_doc)
        self.assertIn("--table-head-bg: #1a2e4a;", html_doc)
        self.assertIn("--table-head-text: #ffffff;", html_doc)
        self.assertIn("--mark-text: inherit;", html_doc)
        self.assertIn("--bg-color: #0d1117;", html_doc)
        self.assertIn("--table-head-bg: #21262d;", html_doc)
        self.assertIn("--table-head-text: #f0f6fc;", html_doc)
        self.assertIn("background: var(--table-head-bg);", html_doc)
        self.assertIn("color: var(--table-head-text);", html_doc)
        self.assertIn("--mark-text: #24292f;", html_doc)
        self.assertIn("<div>ok</div>", html_doc)
        self.assertIn("<table><tbody></tbody></table>", html_doc)

    def test_display_law_name_maps_main_and_suppl(self):
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法", "main"), "建築基準法")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法", "suppl"), "建築基準法")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法施行令", "main"), "建築基準法施行令")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法施行令", "suppl"), "建築基準法施行令")
        self.assertEqual(LawSearchHandler._display_law_name("その他", "main"), "その他")
        self.assertEqual(
            LawSearchHandler._display_law_name("建築物の耐震改修の促進に関する法律", "main"),
            "建築物の耐震改修の促進に関する法律",
        )

    def test_build_like_snippet_keeps_single_heading_when_match_is_in_heading(self):
        body = "（耐火建築物等としなければならない特殊建築物）劇場、映画館その他の特殊建築物は耐火構造としなければならない。"
        snippet = LawSearchHandler._build_like_snippet(body, "耐火")
        self.assertEqual(snippet.count("（"), 1)
        self.assertTrue(snippet.startswith("（<mark>耐火</mark>建築物等としなければならない特殊建築物）"))
        self.assertIn("<mark>耐火</mark>", snippet)

    def test_build_like_snippet_does_not_duplicate_heading_when_snippet_already_contains_it(self):
        body = "前文です。" * 20 + "（特殊建築物等の内装）特殊建築物等の内装は制限を受ける。"
        snippet = LawSearchHandler._build_like_snippet(body, "内装", radius=20)
        self.assertEqual(snippet.count("（特殊建築物等の"), 1)
        self.assertIn("<mark>内装</mark>", snippet)

    def test_build_like_snippet_keeps_plain_snippet_when_heading_missing(self):
        body = "劇場、映画館その他の特殊建築物は耐火構造としなければならない。"
        snippet = LawSearchHandler._build_like_snippet(body, "耐火")
        self.assertFalse(snippet.startswith("（"))
        self.assertIn("<mark>耐火</mark>", snippet)

    def test_extract_leading_heading_ignores_parentheses_that_are_not_at_start(self):
        body = "第三条\n消防長（消防本部を置かない市町村においては、市町村長。）は、危険物又は放置された物件の処理を行う。"
        heading = LawSearchHandler._extract_leading_heading(body)
        self.assertEqual(heading, "")

    def test_display_article_no_omits_leading_dai(self):
        self.assertEqual(LawSearchHandler._display_article_no("第六条"), "六条")
        self.assertEqual(LawSearchHandler._display_article_no("第2条の2"), "2条の2")
        self.assertEqual(LawSearchHandler._display_article_no("六条"), "六条")

    def test_filter_article_rows_by_body_keyword_highlights_matches(self):
        rows = [
            ("建築基準法", "第2条", "一般構造に関する規定。", "一般構造に関する規定。"),
            ("建築基準法", "第2条の2", "防火設備と排煙に関する規定。", "防火設備と排煙に関する規定。"),
        ]
        filtered = LawSearchHandler._filter_article_rows_by_body_keyword(rows, "煙")
        self.assertEqual(
            filtered,
            [("建築基準法", "第2条の2", "防火設備と排<mark>煙</mark>に関する規定。", "防火設備と排<mark>煙</mark>に関する規定。")],
        )

    def test_render_table_embeds_safe_preview_and_full_body(self):
        handler = object.__new__(LawSearchHandler)
        table_html = LawSearchHandler.render_table(
            handler,
            [("建築基準法", "第1条", "…<mark>耐火</mark>…", "<script>alert(1)</script><mark>耐火</mark>構造の全文")],
        )

        self.assertIn("class='body is-expandable'", table_html)
        self.assertIn("class='copy-button'", table_html)
        self.assertIn("class='copy-feedback body-copy-feedback'", table_html)
        self.assertIn("data-copy-text='建築基準法\n第1条\n&lt;script&gt;alert(1)&lt;/script&gt;耐火構造の全文'", table_html)
        self.assertIn("hidden", table_html)
        self.assertIn("class='body-preview'", table_html)
        self.assertIn("class='body-full' hidden", table_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", table_html)
        self.assertIn("<mark>耐火</mark>", table_html)

    def test_render_table_shows_copy_button_for_full_rows_without_hidden_state(self):
        handler = object.__new__(LawSearchHandler)
        table_html = LawSearchHandler.render_table(
            handler,
            [("消防法", "第三条", "第三条\n放置物件を除去する。", "第三条\n放置物件を除去する。")],
        )

        self.assertIn("class='copy-button'", table_html)
        self.assertNotIn("class='copy-button' title='コピー' data-copy-text='消防法&#xA;第三条&#xA;第三条&#xA;放置物件を除去する。' hidden", table_html)
        self.assertIn("消防法\n第三条\n第三条\n放置物件を除去する。", table_html)

    def test_build_bulk_copy_text_joins_all_rows_without_mark_tags(self):
        text = LawSearchHandler._build_bulk_copy_text(
            [
                ("建築基準法", "第1条", "…<mark>耐火</mark>…", "<mark>耐火</mark>構造の全文"),
                ("消防法", "第三条", "…<mark>放置</mark>…", "放置物件を除去する。"),
            ],
            article_query="第1条",
            body_query="耐火",
        )

        self.assertEqual(
            text,
            "検索条件\n条番号: 第1条\n本文キーワード: 耐火\n\n建築基準法\n第1条\n耐火構造の全文\n\n消防法\n第三条\n放置物件を除去する。",
        )
        self.assertNotIn("<mark>", text)

    def test_render_meta_actions_shows_bulk_copy_button_only_when_rows_exist(self):
        handler = object.__new__(LawSearchHandler)
        html_with_rows = LawSearchHandler._render_meta_actions(
            handler,
            [("建築基準法", "第1条", "本文", "本文")],
            article_query="第1条",
            body_query="耐火",
        )
        html_without_rows = LawSearchHandler._render_meta_actions(handler, [])

        self.assertIn("class='bulk-copy-button'", html_with_rows)
        self.assertIn("class='copy-feedback'", html_with_rows)
        self.assertIn("全結果をコピー", html_with_rows)
        self.assertIn("検索条件", html_with_rows)
        self.assertEqual(html_without_rows, "")
        self.assertEqual(
            LawSearchHandler._render_meta_actions(handler, [{"notice_name": "告示"}], source="kokuji"),
            "",
        )

    def test_build_bulk_copy_text_uses_none_for_missing_conditions(self):
        text = LawSearchHandler._build_bulk_copy_text([], article_query="", body_query="")
        self.assertEqual(text, "検索条件\n条番号: なし\n本文キーワード: なし")

    def test_handle_search_page_empty_query_returns_initial_empty_state(self):
        handler = object.__new__(LawSearchHandler)
        captured = {}

        def fake_send_html(body: bytes):
            captured["html"] = body.decode("utf-8")

        handler._send_html = fake_send_html
        handler.render_table = LawSearchHandler.render_table.__get__(handler, LawSearchHandler)
        handler.render_results = LawSearchHandler.render_results.__get__(handler, LawSearchHandler)
        handler.kokuji_db_path = str(ROOT / "data" / "kokuji_notices.db")
        handler.db_path = str(ROOT / "data" / "laws.db")

        parsed = type("Parsed", (), {"query": ""})()
        LawSearchHandler._handle_search_page(handler, parsed)

        self.assertIn("キーワードを入力してください", captured["html"])
        self.assertIn("該当する条文が見つかりませんでした。検索語を変えて再度お試しください。", captured["html"])
        self.assertIn('value="law" checked', captured["html"])

    def test_search_body_prepends_heading_to_like_snippet(self):
        heading_root = ET.fromstring(SAMPLE_HEADING_XML)
        source = LawSource("X300", "建築基準法")

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, source, heading_root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_body(handler, "耐火")

        self.assertEqual(warning, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2].count("（耐火建築物等としなければならない特殊建築物）"), 0)
        self.assertEqual(rows[0][2].count("（<mark>耐火</mark>建築物等としなければならない特殊建築物）"), 1)
        self.assertIn("<mark>耐火</mark>", rows[0][2])

    def test_search_body_does_not_duplicate_heading_in_like_snippet(self):
        body = "前文です。" * 20 + "（特殊建築物等の内装）特殊建築物等の内装は制限を受ける。"
        source = LawSource("X301", "建築基準法")
        root = ET.fromstring(
            f"""
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第三十五条の二</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>{body}</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""
        )

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, source, root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_body(handler, "内装")

        self.assertEqual(warning, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2].count("（特殊建築物等の"), 1)
        self.assertIn("<mark>内装</mark>", rows[0][2])

    def test_search_body_does_not_treat_inline_parentheses_as_heading(self):
        body = "第三条\n消防長（消防本部を置かない市町村においては、市町村長。）は、危険物又は放置された物件の処理を行い、当該物件が放置されたときは措置を命ずることができる。"
        source = LawSource("X302", "消防法")
        root = ET.fromstring(
            f"""
<Root>
  <LawBody>
    <MainProvision>
      <Article>
        <ArticleTitle>第三条</ArticleTitle>
        <Paragraph>
          <ParagraphNum>1</ParagraphNum>
          <ParagraphSentence>
            <Sentence>{body}</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""
        )

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, source, root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_body(handler, "放置")

        self.assertEqual(warning, "")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0][2].startswith("（消防本部を置かない市町村においては、市町村長。）\n"))
        self.assertIn("<mark>放置</mark>", rows[0][2])

    def test_render_settings_table_shows_import_status_and_actions(self):
        handler = object.__new__(LawSearchHandler)
        table_html = LawSearchHandler.render_settings_table(handler, {LAW_REGISTRY[0].law_id})

        self.assertIn("取込済", table_html)
        self.assertIn("未取込", table_html)
        self.assertIn(">更新<", table_html)
        self.assertIn(">削除<", table_html)
        self.assertIn(">追加<", table_html)
        self.assertIn(LAW_REGISTRY[0].law_name, table_html)
        self.assertIn(LAW_REGISTRY[-1].law_name, table_html)

    def test_web_search_missing_db_returns_warning_without_creating_file(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp())
        db_path = tmpdir / "missing.db"

        handler = object.__new__(LawSearchHandler)
        handler.db_path = str(db_path)

        rows, warning = LawSearchHandler.search_article(handler, "第1条")

        self.assertEqual(rows, [])
        self.assertEqual(warning, "DBファイルが見つかりません")
        self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()

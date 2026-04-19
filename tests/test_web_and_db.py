"""SQLite取り込み・検索UI・通信補助の回帰を確認するテスト群。"""

from __future__ import annotations

import pathlib
import sqlite3
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
    init_db,
    iter_articles,
    list_installed_law_ids,
    replace_law,
    upsert_law,
)
from law_registry import DEFAULT_LAWS, LAW_REGISTRY  # type: ignore
import laws_api  # type: ignore
from web_app import SEARCH_PAGE_TEMPLATE, SETTINGS_PAGE_TEMPLATE, LawSearchHandler, build_server_url, open_browser  # type: ignore


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
        init_db(conn)

        inserted = upsert_law(conn, source, root)
        self.assertEqual(inserted, 5)

        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
        self.assertEqual(count, 5)
        self.assertEqual(fts_count, 5)

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
            self.assertEqual(rows[0][0], "法")

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
            self.assertEqual(rows_filtered[0][0], "法")

            rows_six, warning_six = LawSearchHandler.search_article(handler, "6")
            self.assertEqual(warning_six, "")
            self.assertEqual(
                [(row[0], row[1]) for row in rows_six[:2]],
                [("法", "第6条"), ("令", "第6条")],
            )
            self.assertIn("建築物の建築等に関する申請及び確認。", rows_six[0][2])
            self.assertIn("建築基準法施行令の第六条本文。", rows_six[1][2])
            self.assertNotIn("法・附則", [row[0] for row in rows_six])

            # 日本語の部分一致でもヒットする
            rows_partial, warning_partial = LawSearchHandler.search_body(handler, "耐火")
            self.assertGreaterEqual(len(rows_partial), 1)
            self.assertEqual(warning_partial, "")
            self.assertIn("<mark>耐火</mark>", rows_partial[0][2])
            self.assertEqual(rows_partial[0][0], "法")

            rows_suppl_only, warning_suppl_only = LawSearchHandler.search_body(handler, "罰則")
            self.assertEqual(rows_suppl_only, [])
            self.assertEqual(warning_suppl_only, "")

            rows_legacy, warning_legacy = LawSearchHandler.search(handler, "耐火")
            self.assertGreaterEqual(len(rows_legacy), 1)
            self.assertEqual(warning_legacy, "")

            # 記号クエリで構文エラーが出てもフレーズ検索にフォールバック
            rows2, warning2 = LawSearchHandler.search_body(handler, "(")
            self.assertIsInstance(rows2, list)
            self.assertEqual(warning2, "クエリをフレーズ検索に変換")

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

    def test_default_registry_contains_only_three_initial_import_targets(self):
        self.assertEqual([law.law_name for law in DEFAULT_LAWS], ["建築基準法", "建築基準法施行令", "建築士法"])
        self.assertEqual(len(DEFAULT_LAWS), 3)

    def test_replace_and_delete_law_keep_registry_state_and_search_target_consistent(self):
        root = ET.fromstring(SAMPLE_MAIN_XML)
        source = LawSource("X100", "追加法令")

        conn = sqlite3.connect(":memory:")
        ensure_db(conn)

        count = replace_law(conn, source, root)
        self.assertEqual(count, 5)
        self.assertEqual(list_installed_law_ids(conn), {"X100"})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 5)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0], 5)

        delete_law(conn, "X100")
        self.assertEqual(list_installed_law_ids(conn), set())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0], 0)

    def test_replace_law_refresh_removes_stale_articles(self):
        source = LawSource("X200", "更新法令")
        conn = sqlite3.connect(":memory:")
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
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0], 1)

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

    def test_build_meta_handles_article_and_warning_cases(self):
        self.assertEqual(LawSearchHandler._build_meta([], ""), "0件ヒット")
        self.assertEqual(LawSearchHandler._build_meta([("法", "第1条", "本文", "本文")], ""), "1件ヒット")
        self.assertEqual(
            LawSearchHandler._build_meta([], "クエリをフレーズ検索に変換"),
            "0件ヒット（クエリをフレーズ検索に変換）",
        )

    def test_page_template_supports_realtime_search_script(self):
        html_doc = SEARCH_PAGE_TEMPLATE.format(
            article_query="第1条",
            body_query="耐火",
            meta="1件ヒット",
            table="<div>ok</div>",
        )
        self.assertIn('document.addEventListener("DOMContentLoaded"', html_doc)
        self.assertIn("compositionstart", html_doc)
        self.assertIn("compositionend", html_doc)
        self.assertIn("bodyValue.length < 2", html_doc)
        self.assertIn("AUTO_SUBMIT_DELAY_MS = 700", html_doc)
        self.assertIn('querySelectorAll("td.body.is-expandable")', html_doc)
        self.assertIn(">Settings<", html_doc)

    def test_settings_template_supports_notice_and_table_markup(self):
        html_doc = SETTINGS_PAGE_TEMPLATE.format(notice="<div>ok</div>", rows="<table><tbody></tbody></table>")
        self.assertIn("法令 Settings", html_doc)
        self.assertIn("検索へ戻る", html_doc)
        self.assertIn("<div>ok</div>", html_doc)
        self.assertIn("<table><tbody></tbody></table>", html_doc)

    def test_display_law_name_maps_main_and_suppl(self):
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法", "main"), "法")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法", "suppl"), "法・附則")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法施行令", "main"), "令")
        self.assertEqual(LawSearchHandler._display_law_name("建築基準法施行令", "suppl"), "令・附則")
        self.assertEqual(LawSearchHandler._display_law_name("その他", "main"), "その他")
        self.assertEqual(
            LawSearchHandler._display_law_name("建築物の耐震改修の促進に関する法律", "main"),
            "建築物の耐震改修の促進に関する法律",
        )

    def test_build_like_snippet_prepends_leading_heading_when_present(self):
        body = "（耐火建築物等としなければならない特殊建築物）劇場、映画館その他の特殊建築物は耐火構造としなければならない。"
        snippet = LawSearchHandler._build_like_snippet(body, "耐火")
        self.assertTrue(snippet.startswith("（耐火建築物等としなければならない特殊建築物）\n"))
        self.assertIn("<mark>耐火</mark>", snippet)

    def test_build_like_snippet_keeps_plain_snippet_when_heading_missing(self):
        body = "劇場、映画館その他の特殊建築物は耐火構造としなければならない。"
        snippet = LawSearchHandler._build_like_snippet(body, "耐火")
        self.assertFalse(snippet.startswith("（"))
        self.assertIn("<mark>耐火</mark>", snippet)

    def test_display_article_no_omits_leading_dai(self):
        self.assertEqual(LawSearchHandler._display_article_no("第六条"), "六条")
        self.assertEqual(LawSearchHandler._display_article_no("第2条の2"), "2条の2")
        self.assertEqual(LawSearchHandler._display_article_no("六条"), "六条")

    def test_filter_article_rows_by_body_keyword_highlights_matches(self):
        rows = [
            ("法", "第2条", "一般構造に関する規定。", "一般構造に関する規定。"),
            ("法", "第2条の2", "防火設備と排煙に関する規定。", "防火設備と排煙に関する規定。"),
        ]
        filtered = LawSearchHandler._filter_article_rows_by_body_keyword(rows, "煙")
        self.assertEqual(
            filtered,
            [("法", "第2条の2", "防火設備と排<mark>煙</mark>に関する規定。", "防火設備と排<mark>煙</mark>に関する規定。")],
        )

    def test_render_table_embeds_safe_preview_and_full_body(self):
        handler = object.__new__(LawSearchHandler)
        table_html = LawSearchHandler.render_table(
            handler,
            [("法", "第1条", "…<mark>耐火</mark>…", "<script>alert(1)</script><mark>耐火</mark>構造の全文")],
        )

        self.assertIn("class='body is-expandable'", table_html)
        self.assertIn("class='body-preview'", table_html)
        self.assertIn("class='body-full' hidden", table_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", table_html)
        self.assertIn("<mark>耐火</mark>", table_html)

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
        self.assertTrue(rows[0][2].startswith("（耐火建築物等としなければならない特殊建築物）\n"))
        self.assertIn("<mark>耐火</mark>", rows[0][2])

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

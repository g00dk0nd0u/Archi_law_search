from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.append(str(ROOT / "src"))

from law_database import LawSource, init_db, upsert_law  # type: ignore
from web_app import LawSearchHandler  # type: ignore


SAMPLE_XML = """
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
            <Sentence>防火設備に関する規定。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Root>
"""


class DatabaseAndWebTests(unittest.TestCase):
    def test_upsert_creates_and_updates_articles(self):
        root = ET.fromstring(SAMPLE_XML)
        source = LawSource("X001", "テスト法")
        conn = sqlite3.connect(":memory:")
        init_db(conn)

        inserted = upsert_law(conn, source, root)
        self.assertEqual(inserted, 3)

        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
        self.assertEqual(count, 3)
        self.assertEqual(fts_count, 3)

        # 同一データの再投入でも件数は増えない（upsert）
        inserted2 = upsert_law(conn, source, root)
        self.assertEqual(inserted2, 3)
        count2 = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        self.assertEqual(count2, 3)

    def test_web_search_and_html_safety(self):
        root = ET.fromstring(SAMPLE_XML)
        source = LawSource("X001", "テスト法")

        with tempfile.NamedTemporaryFile(suffix=".db") as tf:
            conn = sqlite3.connect(tf.name)
            init_db(conn)
            upsert_law(conn, source, root)
            conn.commit()
            conn.close()

            handler = object.__new__(LawSearchHandler)
            handler.db_path = tf.name

            rows, warning = LawSearchHandler.search_article(handler, "第1条")
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(warning, "")
            self.assertEqual(rows[0][1], "第1条")

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

            # 日本語の部分一致でもヒットする
            rows_partial, warning_partial = LawSearchHandler.search_body(handler, "耐火")
            self.assertGreaterEqual(len(rows_partial), 1)
            self.assertEqual(warning_partial, "")
            self.assertIn("<mark>耐火</mark>", rows_partial[0][2])

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
        self.assertEqual(LawSearchHandler._build_meta([("法", "第1条", "本文")], ""), "1件ヒット")
        self.assertEqual(
            LawSearchHandler._build_meta([], "クエリをフレーズ検索に変換"),
            "0件ヒット（クエリをフレーズ検索に変換）",
        )

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

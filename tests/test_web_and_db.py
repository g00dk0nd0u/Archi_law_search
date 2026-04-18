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
        self.assertEqual(inserted, 2)

        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
        self.assertEqual(count, 2)
        self.assertEqual(fts_count, 2)

        # 同一データの再投入でも件数は増えない（upsert）
        inserted2 = upsert_law(conn, source, root)
        self.assertEqual(inserted2, 2)
        count2 = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        self.assertEqual(count2, 2)

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

            rows, warning = LawSearchHandler.search(handler, "第1条")
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(warning, "")

            rows_number, warning_number = LawSearchHandler.search(handler, "1")
            self.assertGreaterEqual(len(rows_number), 1)
            self.assertEqual(rows_number[0][1], "第1条")
            self.assertEqual(warning_number, "")

            rows_branch, warning_branch = LawSearchHandler.search(handler, "2-2")
            self.assertGreaterEqual(len(rows_branch), 1)
            self.assertEqual(rows_branch[0][1], "第2条の2")
            self.assertEqual(warning_branch, "")

            # 日本語の部分一致でもヒットする
            rows_partial, warning_partial = LawSearchHandler.search(handler, "耐火")
            self.assertGreaterEqual(len(rows_partial), 1)
            self.assertEqual(warning_partial, "")
            self.assertIn("<mark>耐火</mark>", rows_partial[0][2])

            # 記号クエリで構文エラーが出てもフレーズ検索にフォールバック
            rows2, warning2 = LawSearchHandler.search(handler, "(")
            self.assertIsInstance(rows2, list)
            self.assertEqual(warning2, "クエリをフレーズ検索に変換")

            # snippet中のHTMLはエスケープされる（markタグのみ許可）
            unsafe = "<script>alert(1)</script><mark>耐火</mark>"
            safe = LawSearchHandler._safe_snippet(unsafe)
            self.assertIn("&lt;script&gt;", safe)
            self.assertIn("<mark>耐火</mark>", safe)

    def test_web_search_missing_db_returns_warning_without_creating_file(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp())
        db_path = tmpdir / "missing.db"

        handler = object.__new__(LawSearchHandler)
        handler.db_path = str(db_path)

        rows, warning = LawSearchHandler.search(handler, "第1条")

        self.assertEqual(rows, [])
        self.assertEqual(warning, "DBファイルが見つかりません")
        self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()

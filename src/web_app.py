import argparse
import html
from pathlib import Path
import re
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    from number_text_utils import int_to_kanji, normalize_separators
else:
    from .number_text_utils import int_to_kanji, normalize_separators

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "laws.db"

PAGE_TEMPLATE = """<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>建築法規検索</title>
  <style>
    body {{ font-family: sans-serif; margin: 1.5rem auto; max-width: 1080px; padding: 0 1rem; }}
    input[type=text] {{ width: 26rem; max-width: 80vw; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem; vertical-align: top; }}
    th {{ background: #f5f5f5; text-align: left; }}
    .law {{ white-space: nowrap; }}
    .article {{ white-space: nowrap; }}
    .body {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>建築基準法・施行令 検索</h1>
  <form method=\"get\" action=\"/\">
    <input type=\"text\" name=\"q\" value=\"{query}\" placeholder=\"例: 第111条 / 耐火構造\" />
    <button type=\"submit\">検索</button>
  </form>
  <p>{meta}</p>
  {table}
</body>
</html>
"""


class LawSearchHandler(BaseHTTPRequestHandler):
    db_path = str(DEFAULT_DB_PATH)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        query = parse_qs(parsed.query).get("q", [""])[0].strip()
        rows = []
        warning = ""
        if query:
            rows, warning = self.search(query)
            meta = f"{len(rows)}件ヒット"
            if warning:
                meta = f"{meta}（{warning}）"
        else:
            meta = "キーワードを入力してください"

        body = PAGE_TEMPLATE.format(
            query=html.escape(query),
            meta=html.escape(meta),
            table=self.render_table(rows),
        ).encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

    def search(self, query: str):
        db_path = Path(self.db_path)
        if not db_path.exists():
            return [], "DBファイルが見つかりません"

        db_uri = f"{db_path.resolve().as_uri()}?mode=rw"
        try:
            conn = sqlite3.connect(db_uri, uri=True)
        except sqlite3.OperationalError:
            return [], "DBファイルを開けません"

        like_sql = """
            SELECT l.law_name, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE {where_clause}
            ORDER BY a.article_sort_base, a.article_sort_branch
            LIMIT 100
        """
        fts_sql = """
            SELECT l.law_name, a.article_no, snippet(articles_fts, 1, '<mark>', '</mark>', ' … ', 16)
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            JOIN laws l ON l.law_id = a.law_id
            WHERE articles_fts MATCH ?
            ORDER BY a.article_sort_base, a.article_sort_branch
            LIMIT 100
        """

        with conn:
            article_variants, is_article_number_query = self._article_query_variants(query)
            article_operator = "=" if is_article_number_query else "LIKE"
            where_parts = [f"a.article_no {article_operator} ?" for _ in article_variants]
            params = [variant if is_article_number_query else f"%{variant}%" for variant in article_variants]
            where_parts.extend(["a.body LIKE ?", "l.law_name LIKE ?"])
            params.extend([f"%{query}%", f"%{query}%"])
            like_rows = conn.execute(
                like_sql.format(where_clause="\n               OR ".join(where_parts)),
                params,
            ).fetchall()
            if like_rows:
                return [
                    (law_name, article_no, self._build_like_snippet(body, query))
                    for law_name, article_no, body in like_rows
                ], ""

            try:
                return conn.execute(fts_sql, (query,)).fetchall(), ""
            except sqlite3.OperationalError:
                # FTS5の構文エラー回避（例: 記号が多いクエリ）
                quoted = f'"{query}"'
                return conn.execute(fts_sql, (quoted,)).fetchall(), "クエリをフレーズ検索に変換"

    @staticmethod
    def _safe_snippet(snippet_text: str) -> str:
        placeholder_open = "__MARK_OPEN__"
        placeholder_close = "__MARK_CLOSE__"
        safe = (snippet_text or "").replace("<mark>", placeholder_open).replace("</mark>", placeholder_close)
        safe = html.escape(safe)
        return safe.replace(placeholder_open, "<mark>").replace(placeholder_close, "</mark>")

    @staticmethod
    def _build_like_snippet(body_text: str, query: str, radius: int = 80) -> str:
        body_text = body_text or ""
        idx = body_text.find(query)
        if idx < 0:
            return body_text[: radius * 2]

        start = max(0, idx - radius)
        end = min(len(body_text), idx + len(query) + radius)
        snippet = body_text[start:end]
        if start > 0:
            snippet = f"… {snippet}"
        if end < len(body_text):
            snippet = f"{snippet} …"
        return snippet.replace(query, f"<mark>{query}</mark>", 1)

    @staticmethod
    def _article_query_variants(query: str) -> tuple[list[str], bool]:
        variants: list[str] = []
        seen: set[str] = set()

        def add(value: str):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                variants.append(value)

        add(query)
        normalized = normalize_separators(query.strip())
        add(normalized)

        match = re.fullmatch(r"(?:第)?(\d+)(?:条)?(?:[-の](\d+))?", normalized)
        if not match:
            return variants, False

        main_num = int(match.group(1))
        branch_num = match.group(2)
        if branch_num is None:
            add(f"第{main_num}条")
            add(f"第{int_to_kanji(main_num)}条")
        else:
            branch_int = int(branch_num)
            add(f"第{main_num}条の{branch_int}")
            add(f"第{int_to_kanji(main_num)}条の{branch_int}")
            add(f"第{int_to_kanji(main_num)}条の{int_to_kanji(branch_int)}")

        return variants, True

    def render_table(self, rows):
        if not rows:
            return ""
        lines = ["<table>", "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>", "<tbody>"]
        for law_name, article_no, body in rows:
            safe_body = self._safe_snippet(body)
            lines.append(
                "<tr>"
                f"<td class='law'>{html.escape(law_name)}</td>"
                f"<td class='article'>{html.escape(article_no)}</td>"
                f"<td class='body'>{safe_body}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(description="SQLite法規データを検索するWeb UI")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB パス")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    LawSearchHandler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), LawSearchHandler)
    print(f"[INFO] serving http://{args.host}:{args.port} (db={args.db})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

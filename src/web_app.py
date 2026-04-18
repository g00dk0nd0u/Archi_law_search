import argparse
import html
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGE_TEMPLATE = """<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>建築法規検索</title>
  <style>
    body { font-family: sans-serif; margin: 1.5rem auto; max-width: 1080px; padding: 0 1rem; }
    input[type=text] { width: 26rem; max-width: 80vw; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ddd; padding: 0.5rem; vertical-align: top; }
    th { background: #f5f5f5; text-align: left; }
    .law { white-space: nowrap; }
    .article { white-space: nowrap; }
    .body { white-space: pre-wrap; }
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
    db_path = "data/laws.db"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        query = parse_qs(parsed.query).get("q", [""])[0].strip()
        rows = []
        if query:
            rows = self.search(query)
            meta = f"{len(rows)}件ヒット"
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
        sql = """
            SELECT l.law_name, a.article_no, snippet(articles_fts, 1, '<mark>', '</mark>', ' … ', 16)
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            JOIN laws l ON l.law_id = a.law_id
            WHERE articles_fts MATCH ?
            ORDER BY a.article_sort_base, a.article_sort_branch
            LIMIT 100
        """
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(sql, (query,)).fetchall()

    def render_table(self, rows):
        if not rows:
            return ""
        lines = ["<table>", "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>", "<tbody>"]
        for law_name, article_no, body in rows:
            lines.append(
                "<tr>"
                f"<td class='law'>{html.escape(law_name)}</td>"
                f"<td class='article'>{html.escape(article_no)}</td>"
                f"<td class='body'>{body}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(description="SQLite法規データを検索するWeb UI")
    parser.add_argument("--db", default="data/laws.db", help="SQLite DB パス")
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

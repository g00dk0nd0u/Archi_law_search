"""SQLiteに保存した法令データをブラウザから検索するローカルWeb UI。"""

import argparse
from contextlib import closing
import html
from pathlib import Path
import re
import sqlite3
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    from number_text_utils import int_to_kanji, normalize_num, normalize_separators
else:
    from .number_text_utils import int_to_kanji, normalize_num, normalize_separators

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "laws.db"

PAGE_TEMPLATE = """<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>建築法規検索</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: "Hiragino Sans", "Yu Gothic UI", sans-serif;
      margin: 0;
      padding: 1.5rem 1rem;
      max-width: 1100px;
      margin-inline: auto;
      background: #f4f5f7;
      color: #222;
      font-size: 0.9375rem;
    }}
    h1 {{
      font-size: 1.25rem;
      font-weight: 700;
      color: #1a2e4a;
      border-left: 4px solid #3b6ea5;
      padding-left: 0.75rem;
      margin: 0 0 1.25rem;
    }}
    .search-form {{
      background: #fff;
      border: 1px solid #dde1e7;
      border-radius: 8px;
      padding: 0.95rem 1.1rem;
      margin-bottom: 0.6rem;
    }}
    .search-row {{ display: flex; flex-wrap: wrap; gap: 0.85rem; align-items: flex-end; }}
    .field {{ display: grid; gap: 0.3rem; }}
    label {{ font-weight: 600; font-size: 0.8125rem; color: #444; }}
    input[type=text] {{
      width: 18rem;
      max-width: 78vw;
      padding: 0.45rem 0.65rem;
      border: 1px solid #bfc5ce;
      border-radius: 5px;
      font-size: 0.9375rem;
      color: #222;
      background: #fafafa;
      transition: border-color 0.15s;
    }}
    input[type=text]:focus {{
      outline: none;
      border-color: #3b6ea5;
      background: #fff;
      box-shadow: 0 0 0 3px rgba(59, 110, 165, 0.15);
    }}
    #article_q {{ width: 14rem; }}
    #body_q {{ width: 30rem; max-width: 80vw; }}
    button[type=submit] {{
      padding: 0.45rem 1.25rem;
      background: #3b6ea5;
      color: #fff;
      border: none;
      border-radius: 5px;
      font-size: 0.9375rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
      align-self: flex-end;
    }}
    button[type=submit]:hover {{ background: #2d5585; }}
    .meta {{
      font-size: 0.8125rem;
      color: #4e5968;
      margin: 0 0 0.7rem;
      background: #f7f9fc;
      border: 1px solid #e2e7ef;
      border-radius: 6px;
      padding: 0.45rem 0.7rem;
    }}
    .meta strong {{
      font-weight: 600;
      color: #1f3656;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 0.35rem;
      background: #fff;
      border: 1px solid #dde1e7;
      border-radius: 8px;
      overflow: hidden;
      font-size: 0.875rem;
    }}
    thead th {{
      background: #1a2e4a;
      color: #fff;
      border-top: none;
      padding: 0.6rem 0.75rem;
      text-align: left;
      font-size: 0.8125rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    td {{
      border-top: 1px solid #eaecef;
      padding: 0.72rem 0.85rem;
      vertical-align: top;
    }}
    tbody tr:nth-child(even) {{ background: #f8f9fb; }}
    tbody tr:hover {{ background: #eef3fb; }}
    .law {{ white-space: nowrap; color: #3b6ea5; font-weight: 600; width: 3.5rem; }}
    .article {{ white-space: nowrap; width: 6rem; font-variant-numeric: tabular-nums; }}
    .body {{ white-space: pre-wrap; line-height: 1.72; font-size: 0.9rem; }}
    .empty {{
      margin-top: 0.35rem;
      background: #f9fbfd;
      border: 1px solid #e2e7ef;
      border-radius: 8px;
      padding: 0.75rem 0.9rem;
      color: #505c6d;
      font-size: 0.875rem;
    }}
    mark {{
      background: #fff0b3;
      color: inherit;
      border-radius: 2px;
      padding: 0 2px;
    }}
  </style>
</head>
<body>
  <h1>建築基準法・施行令 検索</h1>
  <form method=\"get\" action=\"/\" class=\"search-form\">
    <div class=\"search-row\">
      <div class=\"field\">
        <label for=\"article_q\">条番号</label>
        <input id=\"article_q\" type=\"text\" name=\"article_q\" value=\"{article_query}\" placeholder=\"例: 第111条 / １１１ / 百十一\" />
      </div>
      <div class=\"field\">
        <label for=\"body_q\">本文キーワード</label>
        <input id=\"body_q\" type=\"text\" name=\"body_q\" value=\"{body_query}\" placeholder=\"例: 耐火構造\" />
      </div>
      <button type=\"submit\">検索</button>
    </div>
  </form>
  <p class=\"meta\"><strong>{meta}</strong></p>
  {table}
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      const form = document.querySelector(".search-form");
      const articleInput = document.getElementById("article_q");
      const bodyInput = document.getElementById("body_q");
      if (!form || !articleInput || !bodyInput) {{
        return;
      }}

      const AUTO_SUBMIT_DELAY_MS = 700;
      let timerId = null;
      let isComposing = false;
      let isSubmitting = false;

      const clearScheduledSubmit = function () {{
        if (timerId !== null) {{
          clearTimeout(timerId);
          timerId = null;
        }}
      }};

      const shouldAutoSubmit = function () {{
        const articleValue = articleInput.value.trim();
        const bodyValue = bodyInput.value.trim();
        if (isComposing) {{
          return false;
        }}
        if (!articleValue && !bodyValue) {{
          return false;
        }}
        if (!articleValue && bodyValue.length < 2) {{
          return false;
        }}
        return true;
      }};

      const submitForm = function () {{
        if (isSubmitting) {{
          return;
        }}
        isSubmitting = true;
        clearScheduledSubmit();
        if (typeof form.requestSubmit === "function") {{
          form.requestSubmit();
          return;
        }}
        form.submit();
      }};

      const scheduleSubmit = function () {{
        clearScheduledSubmit();
        if (!shouldAutoSubmit()) {{
          return;
        }}
        timerId = window.setTimeout(function () {{
          if (!shouldAutoSubmit()) {{
            return;
          }}
          submitForm();
        }}, AUTO_SUBMIT_DELAY_MS);
      }};

      const handleCompositionStart = function () {{
        isComposing = true;
        clearScheduledSubmit();
      }};

      const handleCompositionEnd = function () {{
        isComposing = false;
        scheduleSubmit();
      }};

      articleInput.addEventListener("input", scheduleSubmit);
      bodyInput.addEventListener("input", scheduleSubmit);
      articleInput.addEventListener("compositionstart", handleCompositionStart);
      bodyInput.addEventListener("compositionstart", handleCompositionStart);
      articleInput.addEventListener("compositionend", handleCompositionEnd);
      bodyInput.addEventListener("compositionend", handleCompositionEnd);
      form.addEventListener("submit", function () {{
        isSubmitting = true;
        clearScheduledSubmit();
      }});
    }});
  </script>
</body>
</html>
"""


class LawSearchHandler(BaseHTTPRequestHandler):
    db_path = str(DEFAULT_DB_PATH)
    LAW_DISPLAY_LABELS = {
        ("建築基準法", "main"): "法",
        ("建築基準法", "suppl"): "法・附則",
        ("建築基準法施行令", "main"): "令",
        ("建築基準法施行令", "suppl"): "令・附則",
    }

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        article_query, body_query = self._parse_search_inputs(parsed.query)
        rows = []
        warning = ""
        if article_query and body_query:
            rows, warning = self.search_article_with_body_keyword(article_query, body_query)
        else:
            search_mode, active_query = self._select_search_query(article_query, body_query)
            if search_mode == "article":
                rows, warning = self.search_article(active_query)
            elif search_mode == "body":
                rows, warning = self.search_body(active_query)
        if article_query or body_query:
            meta = self._build_meta(rows, warning)
        else:
            meta = "キーワードを入力してください"

        body = PAGE_TEMPLATE.format(
            article_query=html.escape(article_query),
            body_query=html.escape(body_query),
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

    @staticmethod
    def _parse_search_inputs(query_string: str) -> tuple[str, str]:
        params = parse_qs(query_string)
        article_query = params.get("article_q", [""])[0].strip()
        body_query = params.get("body_q", [""])[0].strip()
        legacy_query = params.get("q", [""])[0].strip()
        if not body_query and legacy_query:
            body_query = legacy_query
        return article_query, body_query

    @staticmethod
    def _select_search_query(article_query: str, body_query: str) -> tuple[str, str]:
        if article_query:
            return "article", article_query
        if body_query:
            return "body", body_query
        return "", ""

    @staticmethod
    def _build_meta(rows, warning: str) -> str:
        meta = f"{len(rows)}件ヒット"
        if warning:
            meta = f"{meta}（{warning}）"
        return meta

    def _connect_db(self):
        db_path = Path(self.db_path)
        if not db_path.exists():
            return None, "DBファイルが見つかりません"

        db_uri = f"{db_path.resolve().as_uri()}?mode=rw"
        try:
            return sqlite3.connect(db_uri, uri=True), ""
        except sqlite3.OperationalError:
            return None, "DBファイルを開けません"

    def search(self, query: str):
        return self.search_body(query)

    def search_article_with_body_keyword(self, article_query: str, body_query: str):
        rows, warning = self.search_article(article_query)
        if not body_query or warning:
            return rows, warning
        return self._filter_article_rows_by_body_keyword(rows, body_query), warning

    def search_article(self, query: str):
        conn, warning = self._connect_db()
        if conn is None:
            return [], warning

        sql = """
            SELECT l.law_name, a.provision_kind, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND ({where_clause})
            ORDER BY
                CASE l.law_name
                    WHEN '建築基準法' THEN 0
                    WHEN '建築基準法施行令' THEN 1
                    ELSE 2
                END,
                a.article_sort_base,
                a.article_sort_branch,
                CASE a.provision_kind WHEN 'main' THEN 0 ELSE 1 END,
                a.article_no
            LIMIT 100
        """

        with closing(conn):
            article_variants, parsed_article = self._article_query_variants(query)
            main_num, branch_num = parsed_article
            where_parts = ["a.article_no = ?" for _ in article_variants]
            params = list(article_variants)
            if main_num is not None and branch_num is None:
                branchable_variants = [variant for variant in article_variants if "条" in variant]
                where_parts.extend(["a.article_no LIKE ?" for _ in branchable_variants])
                params.extend([f"{variant}の%" for variant in branchable_variants])
            rows = conn.execute(sql.format(where_clause="\n               OR ".join(where_parts)), params).fetchall()
            return self._format_result_rows(rows), ""

    def search_body(self, query: str):
        conn, warning = self._connect_db()
        if conn is None:
            return [], warning

        like_sql = """
            SELECT l.law_name, a.provision_kind, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND (a.body LIKE ? OR l.law_name LIKE ?)
            ORDER BY
                CASE l.law_name
                    WHEN '建築基準法' THEN 0
                    WHEN '建築基準法施行令' THEN 1
                    ELSE 2
                END,
                a.article_sort_base,
                a.article_sort_branch,
                CASE a.provision_kind WHEN 'main' THEN 0 ELSE 1 END,
                a.article_no
            LIMIT 100
        """
        fts_sql = """
            SELECT l.law_name, a.provision_kind, a.article_no, snippet(articles_fts, 1, '<mark>', '</mark>', ' … ', 16)
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND articles_fts MATCH ?
            ORDER BY
                CASE l.law_name
                    WHEN '建築基準法' THEN 0
                    WHEN '建築基準法施行令' THEN 1
                    ELSE 2
                END,
                a.article_sort_base,
                a.article_sort_branch,
                CASE a.provision_kind WHEN 'main' THEN 0 ELSE 1 END,
                a.article_no
            LIMIT 100
        """

        with closing(conn):
            like_rows = conn.execute(like_sql, (f"%{query}%", f"%{query}%")).fetchall()
            if like_rows:
                return [
                    (self._display_law_name(law_name, provision_kind), article_no, self._build_like_snippet(body, query))
                    for law_name, provision_kind, article_no, body in like_rows
                ], ""

            try:
                return self._format_result_rows(conn.execute(fts_sql, (query,)).fetchall()), ""
            except sqlite3.OperationalError:
                # FTS5の構文エラー回避（例: 記号が多いクエリ）
                quoted = f'"{query}"'
                return self._format_result_rows(conn.execute(fts_sql, (quoted,)).fetchall()), "クエリをフレーズ検索に変換"

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
    def _highlight_text(text: str, query: str) -> str:
        if not text or not query or query not in text:
            return text
        return text.replace(query, f"<mark>{query}</mark>")

    @classmethod
    def _display_law_name(cls, law_name: str, provision_kind: str) -> str:
        return cls.LAW_DISPLAY_LABELS.get((law_name, provision_kind), law_name)

    @classmethod
    def _format_result_rows(cls, rows):
        return [
            (cls._display_law_name(law_name, provision_kind), article_no, body)
            for law_name, provision_kind, article_no, body in rows
        ]

    @classmethod
    def _filter_article_rows_by_body_keyword(cls, rows, body_query: str):
        filtered_rows = []
        for law_name, article_no, body in rows:
            if body_query not in body:
                continue
            filtered_rows.append((law_name, article_no, cls._highlight_text(body, body_query)))
        return filtered_rows

    @staticmethod
    def _display_article_no(article_no: str) -> str:
        return article_no[1:] if article_no.startswith("第") else article_no

    @staticmethod
    def _article_query_variants(query: str) -> tuple[list[str], tuple[int | None, int | None]]:
        variants: list[str] = []
        seen: set[str] = set()

        def add(value: str):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                variants.append(value)

        add(query)
        normalized = normalize_num(normalize_separators(query.strip()))
        add(normalized)

        match = re.fullmatch(r"(?:第)?(\d+)(?:条)?(?:[-の](\d+))?", normalized)
        if not match:
            return variants, (None, None)

        main_num = int(match.group(1))
        branch_num = match.group(2)
        if branch_num is None:
            add(f"第{main_num}条")
            add(f"第{int_to_kanji(main_num)}条")
            return variants, (main_num, None)
        else:
            branch_int = int(branch_num)
            add(f"第{main_num}条の{branch_int}")
            add(f"第{int_to_kanji(main_num)}条の{branch_int}")
            add(f"第{int_to_kanji(main_num)}条の{int_to_kanji(branch_int)}")
            return variants, (main_num, branch_int)

    def render_table(self, rows):
        if not rows:
            return "<div class='empty'>該当する条文が見つかりませんでした。検索語を変えて再度お試しください。</div>"
        lines = ["<table>", "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>", "<tbody>"]
        for law_name, article_no, body in rows:
            safe_body = self._safe_snippet(body)
            display_article_no = self._display_article_no(article_no)
            lines.append(
                "<tr>"
                f"<td class='law'>{html.escape(law_name)}</td>"
                f"<td class='article'>{html.escape(display_article_no)}</td>"
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


def build_server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def open_browser(url: str, delay_seconds: float = 0.3) -> None:
    def _open():
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"[WARN] failed to open browser: {exc}")

    threading.Thread(target=_open, daemon=True).start()


def main():
    args = parse_args()
    LawSearchHandler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), LawSearchHandler)
    url = build_server_url(args.host, args.port)
    print(f"[INFO] serving {url} (db={args.db})")
    open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

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
from urllib.parse import parse_qs, urlencode, urlparse

if __package__ in (None, ""):
    from law_database import LawSource, connect_db, delete_law, ensure_db, law_exists, list_installed_law_ids, replace_law
    from law_registry import LAW_BY_ID, LAW_REGISTRY
    from laws_api import fetch_law_xml
    from number_text_utils import int_to_kanji, normalize_num, normalize_separators
else:
    from .law_database import LawSource, connect_db, delete_law, ensure_db, law_exists, list_installed_law_ids, replace_law
    from .law_registry import LAW_BY_ID, LAW_REGISTRY
    from .laws_api import fetch_law_xml
    from .number_text_utils import int_to_kanji, normalize_num, normalize_separators

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "laws.db"

SEARCH_PAGE_TEMPLATE = """<!doctype html>
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
    .page-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      margin: 0 0 1.1rem;
    }}
    h1 {{
      font-size: 1.25rem;
      font-weight: 700;
      color: #1a2e4a;
      border-left: 4px solid #3b6ea5;
      padding-left: 0.75rem;
      margin: 0;
    }}
    .header-actions {{
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 2rem;
      padding: 0.35rem 0.9rem;
      border: 1px solid #c9d3e0;
      border-radius: 6px;
      background: #fff;
      color: #1f3656;
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
    }}
    .nav-link:hover {{ background: #f7f9fc; }}
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
    button, .action-button {{
      padding: 0.45rem 1.05rem;
      background: #3b6ea5;
      color: #fff;
      border: none;
      border-radius: 5px;
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
      text-decoration: none;
    }}
    button:hover, .action-button:hover {{ background: #2d5585; }}
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
    .law {{ white-space: nowrap; color: #3b6ea5; font-weight: 600; width: 6rem; }}
    .article {{ white-space: nowrap; width: 6rem; font-variant-numeric: tabular-nums; }}
    .body {{ white-space: pre-wrap; line-height: 1.72; font-size: 0.9rem; }}
    .body.is-expandable {{
      cursor: pointer;
      transition: background 0.15s;
    }}
    .body.is-expandable:hover {{ background: #f7fafd; }}
    .body-preview, .body-full {{ white-space: pre-wrap; }}
    .body-full[hidden], .body-preview[hidden] {{ display: none; }}
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
  <div class=\"page-header\">
    <h1>建築法規検索</h1>
    <div class=\"header-actions\">
      <a class=\"nav-link\" href=\"/settings\">Settings</a>
    </div>
  </div>
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

      document.querySelectorAll("td.body.is-expandable").forEach(function (cell) {{
        cell.addEventListener("click", function () {{
          const preview = cell.querySelector(".body-preview");
          const full = cell.querySelector(".body-full");
          if (!preview || !full) {{
            return;
          }}
          const expanded = cell.classList.toggle("is-expanded");
          preview.hidden = expanded;
          full.hidden = !expanded;
        }});
      }});
    }});
  </script>
</body>
</html>
"""

SETTINGS_PAGE_TEMPLATE = """<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>法令 Settings</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: "Hiragino Sans", "Yu Gothic UI", sans-serif;
      margin: 0;
      padding: 1.5rem 1rem 2rem;
      max-width: 1100px;
      margin-inline: auto;
      background: #f4f5f7;
      color: #222;
      font-size: 0.9375rem;
    }}
    .page-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      margin: 0 0 1rem;
    }}
    h1 {{
      font-size: 1.2rem;
      font-weight: 700;
      color: #1a2e4a;
      border-left: 4px solid #3b6ea5;
      padding-left: 0.75rem;
      margin: 0;
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 2rem;
      padding: 0.35rem 0.9rem;
      border: 1px solid #c9d3e0;
      border-radius: 6px;
      background: #fff;
      color: #1f3656;
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
    }}
    .nav-link:hover {{ background: #f7f9fc; }}
    .panel {{
      background: #fff;
      border: 1px solid #dde1e7;
      border-radius: 8px;
      padding: 1rem 1.1rem 1.1rem;
    }}
    .panel p {{
      margin: 0 0 0.9rem;
      color: #4e5968;
      line-height: 1.6;
    }}
    .notice {{
      margin: 0 0 0.9rem;
      border-radius: 6px;
      padding: 0.65rem 0.8rem;
      font-size: 0.875rem;
      border: 1px solid #d9e2ef;
      background: #f7f9fc;
      color: #1f3656;
    }}
    .notice.is-error {{
      border-color: #edc7c7;
      background: #fff3f3;
      color: #8b2e2e;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 0.875rem;
    }}
    thead th {{
      background: #1a2e4a;
      color: #fff;
      padding: 0.65rem 0.75rem;
      text-align: left;
      white-space: nowrap;
      font-size: 0.8125rem;
    }}
    tbody td {{
      border-top: 1px solid #eaecef;
      padding: 0.78rem 0.75rem;
      vertical-align: middle;
    }}
    tbody tr:nth-child(even) {{ background: #f8f9fb; }}
    .law-name {{
      font-weight: 600;
      color: #1f3656;
      line-height: 1.5;
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 1.9rem;
      padding: 0.2rem 0.65rem;
      border-radius: 999px;
      border: 1px solid #c9d3e0;
      background: #eef3fb;
      color: #1f3656;
      font-size: 0.8125rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .status-badge.is-off {{
      background: #f5f5f6;
      color: #5b6572;
      border-color: #d8dce1;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
    }}
    .actions form {{ margin: 0; }}
    button {{
      padding: 0.42rem 0.95rem;
      border: none;
      border-radius: 5px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      background: #3b6ea5;
      color: #fff;
    }}
    button:hover {{ background: #2d5585; }}
    .button-secondary {{
      background: #5f748e;
    }}
    .button-secondary:hover {{
      background: #4d627b;
    }}
    .button-danger {{
      background: #a44949;
    }}
    .button-danger:hover {{
      background: #883939;
    }}
    .empty {{
      margin-top: 0.6rem;
      color: #5b6572;
      font-size: 0.875rem;
    }}
  </style>
</head>
<body>
  <div class=\"page-header\">
    <h1>法令 Settings</h1>
    <a class=\"nav-link\" href=\"/\">検索へ戻る</a>
  </div>
  <div class=\"panel\">
    <p>検索対象に含める法令を管理します。取込済の法令は検索対象になり、未取込の法令はここから追加できます。</p>
    {notice}
    {rows}
  </div>
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
        if parsed.path == "/":
            self._handle_search_page(parsed)
            return
        if parsed.path == "/settings":
            self._handle_settings_page(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/settings/action":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        self._handle_settings_action()

    def log_message(self, format, *args):
        return

    def _handle_search_page(self, parsed):
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

        body = SEARCH_PAGE_TEMPLATE.format(
            article_query=html.escape(article_query),
            body_query=html.escape(body_query),
            meta=html.escape(meta),
            table=self.render_table(rows),
        ).encode("utf-8")
        self._send_html(body)

    def _handle_settings_page(self, parsed):
        params = parse_qs(parsed.query)
        message = params.get("message", [""])[0].strip()
        kind = params.get("kind", ["info"])[0].strip()
        notice = self._render_notice(message, kind) if message else ""

        installed_ids = set()
        conn = self._connect_existing_db()
        if conn is not None:
            with closing(conn):
                installed_ids = list_installed_law_ids(conn)

        body = SETTINGS_PAGE_TEMPLATE.format(
            notice=notice,
            rows=self.render_settings_table(installed_ids),
        ).encode("utf-8")
        self._send_html(body)

    def _handle_settings_action(self):
        params = self._read_post_params()
        action = params.get("action", [""])[0].strip()
        law_id = params.get("law_id", [""])[0].strip()
        law = LAW_BY_ID.get(law_id)
        if law is None:
            self._redirect_with_message("error", "対象の法令が見つかりません。")
            return

        try:
            db_path = Path(self.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = connect_db(db_path)
            try:
                ensure_db(conn)
                if action == "add":
                    root = fetch_law_xml(law.law_id)
                    count = replace_law(conn, LawSource(law.law_id, law.law_name), root)
                elif action == "refresh":
                    root = fetch_law_xml(law.law_id)
                    count = replace_law(conn, LawSource(law.law_id, law.law_name), root)
                elif action == "delete":
                    if law_exists(conn, law.law_id):
                        delete_law(conn, law.law_id)
                    count = 0
                else:
                    raise ValueError("未対応の操作です。")
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._redirect_with_message("error", f"{law.law_name}: {exc}")
            return

        if action == "add":
            self._redirect_with_message("info", f"{law.law_name} を追加しました。{count}件の条文を取込済です。")
        elif action == "refresh":
            self._redirect_with_message("info", f"{law.law_name} を更新しました。{count}件の条文を再取込しました。")
        else:
            self._redirect_with_message("info", f"{law.law_name} を削除しました。")

    def _send_html(self, body: bytes):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect_with_message(self, kind: str, message: str):
        query = urlencode({"kind": kind, "message": message})
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/settings?{query}")
        self.end_headers()

    def _connect_existing_db(self):
        db_path = Path(self.db_path)
        if not db_path.exists():
            return None
        db_uri = f"{db_path.resolve().as_uri()}?mode=rw"
        try:
            conn = sqlite3.connect(db_uri, uri=True)
        except sqlite3.OperationalError:
            return None
        ensure_db(conn)
        return conn

    def _read_post_params(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        payload = self.rfile.read(length).decode("utf-8")
        return parse_qs(payload)

    @staticmethod
    def _render_notice(message: str, kind: str) -> str:
        css_class = "notice is-error" if kind == "error" else "notice"
        return f"<div class='{css_class}'>{html.escape(message)}</div>"

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

    def _connect_search_db(self):
        db_path = Path(self.db_path)
        if not db_path.exists():
            return None, "DBファイルが見つかりません"

        db_uri = f"{db_path.resolve().as_uri()}?mode=rw"
        try:
            return sqlite3.connect(db_uri, uri=True), ""
        except sqlite3.OperationalError:
            return None, "DBファイルを開けません"

    @staticmethod
    def _law_order_sql() -> str:
        return """
            CASE l.law_name
                WHEN '建築基準法' THEN 0
                WHEN '建築基準法施行令' THEN 1
                ELSE 2
            END,
            l.law_name,
        """

    def search(self, query: str):
        return self.search_body(query)

    def search_article_with_body_keyword(self, article_query: str, body_query: str):
        rows, warning = self.search_article(article_query)
        if not body_query or warning:
            return rows, warning
        return self._filter_article_rows_by_body_keyword(rows, body_query), warning

    def search_article(self, query: str):
        conn, warning = self._connect_search_db()
        if conn is None:
            return [], warning

        sql = f"""
            SELECT l.law_name, a.provision_kind, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND ({{where_clause}})
            ORDER BY
                {self._law_order_sql()}
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
        conn, warning = self._connect_search_db()
        if conn is None:
            return [], warning

        like_sql = f"""
            SELECT l.law_name, a.provision_kind, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND (a.body LIKE ? OR l.law_name LIKE ?)
            ORDER BY
                {self._law_order_sql()}
                a.article_sort_base,
                a.article_sort_branch,
                CASE a.provision_kind WHEN 'main' THEN 0 ELSE 1 END,
                a.article_no
            LIMIT 100
        """
        fts_sql = f"""
            SELECT
                l.law_name,
                a.provision_kind,
                a.article_no,
                snippet(articles_fts, 1, '<mark>', '</mark>', ' … ', 16),
                highlight(articles_fts, 1, '<mark>', '</mark>')
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND articles_fts MATCH ?
            ORDER BY
                {self._law_order_sql()}
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
                    (
                        self._display_law_name(law_name, provision_kind),
                        article_no,
                        self._build_like_snippet(body, query),
                        self._highlight_text(body, query),
                    )
                    for law_name, provision_kind, article_no, body in like_rows
                ], ""

            try:
                return self._format_result_rows(conn.execute(fts_sql, (query,)).fetchall(), body_index=3, full_body_index=4), ""
            except sqlite3.OperationalError:
                quoted = f'"{query}"'
                return self._format_result_rows(conn.execute(fts_sql, (quoted,)).fetchall(), body_index=3, full_body_index=4), "クエリをフレーズ検索に変換"

    @staticmethod
    def _safe_snippet(snippet_text: str) -> str:
        placeholder_open = "__MARK_OPEN__"
        placeholder_close = "__MARK_CLOSE__"
        safe = (snippet_text or "").replace("<mark>", placeholder_open).replace("</mark>", placeholder_close)
        safe = html.escape(safe)
        return safe.replace(placeholder_open, "<mark>").replace(placeholder_close, "</mark>")

    @staticmethod
    def _extract_leading_heading(body_text: str, max_scan_length: int = 240, max_heading_length: int = 80) -> str:
        body_text = (body_text or "").strip()
        if not body_text:
            return ""

        match = re.search(r"（[^）]{1," + str(max_heading_length) + r"}）", body_text[:max_scan_length])
        if match is None:
            return ""
        return match.group(0)

    @classmethod
    def _prepend_heading_to_snippet(cls, body_text: str, snippet: str) -> str:
        heading = cls._extract_leading_heading(body_text)
        if not heading:
            return snippet
        if snippet.startswith(heading):
            return snippet
        return f"{heading}\n{snippet}"

    @classmethod
    def _build_like_snippet(cls, body_text: str, query: str, radius: int = 80) -> str:
        body_text = body_text or ""
        idx = body_text.find(query)
        if idx < 0:
            snippet = body_text[: radius * 2]
            return cls._prepend_heading_to_snippet(body_text, snippet)

        start = max(0, idx - radius)
        end = min(len(body_text), idx + len(query) + radius)
        snippet = body_text[start:end]
        if start > 0:
            snippet = f"… {snippet}"
        if end < len(body_text):
            snippet = f"{snippet} …"
        snippet = snippet.replace(query, f"<mark>{query}</mark>", 1)
        return cls._prepend_heading_to_snippet(body_text, snippet)

    @staticmethod
    def _highlight_text(text: str, query: str) -> str:
        if not text or not query or query not in text:
            return text
        return text.replace(query, f"<mark>{query}</mark>")

    @classmethod
    def _display_law_name(cls, law_name: str, provision_kind: str) -> str:
        return cls.LAW_DISPLAY_LABELS.get((law_name, provision_kind), law_name)

    @classmethod
    def _format_result_rows(cls, rows, body_index: int = 3, full_body_index: int | None = None):
        return [
            cls._format_result_row(row, body_index=body_index, full_body_index=full_body_index)
            for row in rows
        ]

    @classmethod
    def _filter_article_rows_by_body_keyword(cls, rows, body_query: str):
        filtered_rows = []
        for law_name, article_no, body, full_body in rows:
            if body_query not in full_body:
                continue
            highlighted_body = cls._highlight_text(full_body, body_query)
            filtered_rows.append((law_name, article_no, highlighted_body, highlighted_body))
        return filtered_rows

    @classmethod
    def _format_result_row(cls, row, body_index: int = 3, full_body_index: int | None = None):
        law_name, provision_kind, article_no = row[:3]
        body = row[body_index]
        full_body = body if full_body_index is None else row[full_body_index]
        return (cls._display_law_name(law_name, provision_kind), article_no, body, full_body)

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

        branch_int = int(branch_num)
        add(f"第{main_num}条の{branch_int}")
        add(f"第{int_to_kanji(main_num)}条の{branch_int}")
        add(f"第{int_to_kanji(main_num)}条の{int_to_kanji(branch_int)}")
        return variants, (main_num, branch_int)

    def render_table(self, rows):
        if not rows:
            return "<div class='empty'>該当する条文が見つかりませんでした。検索語を変えて再度お試しください。</div>"
        lines = ["<table>", "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>", "<tbody>"]
        for law_name, article_no, body, full_body in rows:
            safe_body = self._safe_snippet(body)
            safe_full_body = self._safe_snippet(full_body)
            is_expandable = safe_body != safe_full_body
            body_class = "body is-expandable" if is_expandable else "body"
            body_html = f"<div class='body-preview'>{safe_body}</div>"
            if is_expandable:
                body_html += f"<div class='body-full' hidden>{safe_full_body}</div>"
            display_article_no = self._display_article_no(article_no)
            lines.append(
                "<tr>"
                f"<td class='law'>{html.escape(law_name)}</td>"
                f"<td class='article'>{html.escape(display_article_no)}</td>"
                f"<td class='{body_class}'>{body_html}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    def render_settings_table(self, installed_ids: set[str]) -> str:
        if not LAW_REGISTRY:
            return "<div class='empty'>表示できる法令がありません。</div>"

        lines = [
            "<table>",
            "<thead><tr><th>法令</th><th>状態</th><th>操作</th></tr></thead>",
            "<tbody>",
        ]
        for law in LAW_REGISTRY:
            is_installed = law.law_id in installed_ids
            status_label = "取込済" if is_installed else "未取込"
            status_class = "status-badge" if is_installed else "status-badge is-off"
            actions = self._render_settings_actions(law.law_id, is_installed)
            lines.append(
                "<tr>"
                f"<td><div class='law-name'>{html.escape(law.law_name)}</div></td>"
                f"<td><span class='{status_class}'>{status_label}</span></td>"
                f"<td>{actions}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    @staticmethod
    def _render_settings_actions(law_id: str, is_installed: bool) -> str:
        def render_form(action: str, label: str, button_class: str = "") -> str:
            class_attr = f" class='{button_class}'" if button_class else ""
            return (
                "<form method='post' action='/settings/action'>"
                f"<input type='hidden' name='law_id' value='{html.escape(law_id)}' />"
                f"<input type='hidden' name='action' value='{action}' />"
                f"<button type='submit'{class_attr}>{label}</button>"
                "</form>"
            )

        forms = [render_form("add", "追加")] if not is_installed else [
            render_form("refresh", "更新", "button-secondary"),
            render_form("delete", "削除", "button-danger"),
        ]
        return f"<div class='actions'>{''.join(forms)}</div>"


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
    db_path = Path(args.db)
    if db_path.exists():
        conn = connect_db(db_path)
        try:
            ensure_db(conn)
            conn.commit()
        finally:
            conn.close()

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

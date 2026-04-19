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
  <script>
    (function () {{
      const storageKey = "archi-law-search-theme";
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      let theme = prefersDark ? "dark" : "light";
      try {{
        const savedTheme = localStorage.getItem(storageKey);
        if (savedTheme === "light" || savedTheme === "dark") {{
          theme = savedTheme;
        }}
      }} catch (_error) {{
      }}
      document.documentElement.dataset.theme = theme;
    }})();
  </script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    :root {{
      color-scheme: light;
      --bg-color: #f4f5f7;
      --surface-color: #ffffff;
      --surface-muted: #f7f9fc;
      --surface-soft: #f8f9fb;
      --surface-hover: #eef3fb;
      --surface-accent: #f7fafd;
      --text-color: #222222;
      --text-strong: #1a2e4a;
      --text-muted: #4e5968;
      --text-subtle: #505c6d;
      --link-color: #1f3656;
      --accent-color: #3b6ea5;
      --accent-hover: #2d5585;
      --accent-soft: rgba(59, 110, 165, 0.15);
      --border-color: #dde1e7;
      --border-soft: #e2e7ef;
      --border-table: #eaecef;
      --border-input: #bfc5ce;
      --border-button: #c9d3e0;
      --border-copy: #d5dbe4;
      --border-copy-hover: #aebccc;
      --nav-bg: #ffffff;
      --button-text: #ffffff;
      --meta-strong: #1f3656;
      --copy-button-bg: rgba(255, 255, 255, 0.92);
      --copy-button-back: rgba(244, 245, 247, 0.98);
      --feedback-bg: rgba(255, 255, 255, 0.92);
      --feedback-border: #d6dee8;
      --mark-bg: #ffdca8;
      --shadow-ring: 0 0 0 3px rgba(59, 110, 165, 0.15);
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg-color: #111722;
      --surface-color: #182131;
      --surface-muted: #1d2738;
      --surface-soft: #151f2e;
      --surface-hover: #223147;
      --surface-accent: #202c3e;
      --text-color: #e6ebf2;
      --text-strong: #f2f6fb;
      --text-muted: #aeb9c8;
      --text-subtle: #b6c0cf;
      --link-color: #d9e5f4;
      --accent-color: #628fca;
      --accent-hover: #7aa3db;
      --accent-soft: rgba(98, 143, 202, 0.24);
      --border-color: #2c3a4f;
      --border-soft: #33445c;
      --border-table: #2a3648;
      --border-input: #415269;
      --border-button: #415269;
      --border-copy: #46586f;
      --border-copy-hover: #6d8199;
      --nav-bg: #1b2637;
      --button-text: #f7f9fc;
      --meta-strong: #edf3fb;
      --copy-button-bg: rgba(24, 33, 49, 0.94);
      --copy-button-back: rgba(17, 23, 34, 0.98);
      --feedback-bg: rgba(24, 33, 49, 0.95);
      --feedback-border: #43556d;
      --mark-bg: #f2ad61;
      --shadow-ring: 0 0 0 3px rgba(98, 143, 202, 0.24);
    }}
    body {{
      font-family: "Hiragino Sans", "Yu Gothic UI", sans-serif;
      margin: 0;
      padding: 1.5rem 1rem;
      max-width: 1100px;
      margin-inline: auto;
      background: var(--bg-color);
      color: var(--text-color);
      font-size: 0.9375rem;
      transition: background 0.18s ease, color 0.18s ease;
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
      color: var(--text-strong);
      border-left: 4px solid var(--accent-color);
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
      border: 1px solid var(--border-button);
      border-radius: 6px;
      background: var(--nav-bg);
      color: var(--link-color);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    }}
    .nav-link:hover {{ background: var(--surface-muted); }}
    .theme-toggle {{
      width: 2rem;
      min-width: 2rem;
      height: 2rem;
      padding: 0;
      border: 1px solid var(--border-button);
      border-radius: 999px;
      background: var(--nav-bg);
      color: var(--link-color);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.12s ease;
    }}
    .theme-toggle:hover, .theme-toggle:focus {{
      background: var(--surface-muted);
      border-color: var(--border-input);
      outline: none;
    }}
    .theme-toggle:active {{ transform: translateY(1px); }}
    .theme-toggle-icon {{
      font-size: 0.96rem;
      line-height: 1;
    }}
    .search-form {{
      background: var(--surface-color);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 0.95rem 1.1rem;
      margin-bottom: 0.6rem;
    }}
    .search-row {{ display: flex; flex-wrap: wrap; gap: 0.85rem; align-items: flex-end; }}
    .field {{ display: grid; gap: 0.3rem; }}
    label {{ font-weight: 600; font-size: 0.8125rem; color: var(--text-muted); }}
    input[type=text] {{
      width: 18rem;
      max-width: 78vw;
      padding: 0.45rem 0.65rem;
      border: 1px solid var(--border-input);
      border-radius: 5px;
      font-size: 0.9375rem;
      color: var(--text-color);
      background: var(--surface-soft);
      transition: border-color 0.15s;
    }}
    input[type=text]:focus {{
      outline: none;
      border-color: var(--accent-color);
      background: var(--surface-color);
      box-shadow: var(--shadow-ring);
    }}
    #article_q {{ width: 14rem; }}
    #body_q {{ width: 30rem; max-width: 80vw; }}
    button, .action-button {{
      padding: 0.45rem 1.05rem;
      background: var(--accent-color);
      color: var(--button-text);
      border: none;
      border-radius: 5px;
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
      text-decoration: none;
    }}
    button:hover, .action-button:hover {{ background: var(--accent-hover); }}
    .meta {{
      font-size: 0.8125rem;
      color: var(--text-muted);
      margin: 0 0 0.7rem;
      background: var(--surface-muted);
      border: 1px solid var(--border-soft);
      border-radius: 6px;
      padding: 0.45rem 0.7rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.8rem;
    }}
    .meta strong {{
      font-weight: 600;
      color: var(--meta-strong);
    }}
    .meta-actions {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 0.5rem;
      flex-shrink: 0;
      position: relative;
    }}
    .bulk-copy-button {{
      padding: 0.32rem 0.72rem;
      background: var(--surface-color);
      color: var(--link-color);
      border: 1px solid var(--border-button);
      border-radius: 5px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .bulk-copy-button:hover, .bulk-copy-button:focus {{
      background: var(--surface-muted);
      border-color: var(--border-input);
      color: var(--text-strong);
      outline: none;
    }}
    .bulk-copy-button[hidden] {{ display: none; }}
    .copy-feedback {{
      position: absolute;
      top: 50%;
      right: calc(100% + 0.35rem);
      transform: translateY(-50%);
      font-size: 0.74rem;
      color: var(--text-muted);
      background: var(--feedback-bg);
      border: 1px solid var(--feedback-border);
      border-radius: 999px;
      padding: 0.14rem 0.46rem;
      line-height: 1.2;
      white-space: nowrap;
    }}
    .copy-feedback[hidden] {{ display: none; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 0.35rem;
      background: var(--surface-color);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      overflow: hidden;
      font-size: 0.875rem;
    }}
    thead th {{
      background: var(--text-strong);
      color: var(--button-text);
      border-top: none;
      padding: 0.6rem 0.75rem;
      text-align: left;
      font-size: 0.8125rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    td {{
      border-top: 1px solid var(--border-table);
      padding: 0.72rem 0.85rem;
      vertical-align: top;
    }}
    tbody tr:nth-child(even) {{ background: var(--surface-soft); }}
    tbody tr:hover {{ background: var(--surface-hover); }}
    .law {{ white-space: nowrap; color: var(--accent-color); font-weight: 600; width: 6rem; }}
    .article {{ white-space: nowrap; width: 6rem; font-variant-numeric: tabular-nums; }}
    .body {{ white-space: pre-wrap; line-height: 1.72; font-size: 0.9rem; }}
    .body-wrap {{
      position: relative;
      min-height: 1.6rem;
      padding-right: 2.1rem;
    }}
    .body-copy-feedback {{
      position: absolute;
      top: 0.18rem;
      right: 2.35rem;
    }}
    .body.is-expandable {{
      cursor: pointer;
      transition: background 0.15s;
    }}
    .body.is-expandable:hover {{ background: var(--surface-accent); }}
    .body-preview, .body-full {{ white-space: pre-wrap; }}
    .body-full[hidden], .body-preview[hidden] {{ display: none; }}
    .copy-button {{
      position: absolute;
      top: 0;
      right: 0;
      width: 1.65rem;
      height: 1.65rem;
      border: 1px solid var(--border-copy);
      border-radius: 4px;
      background: var(--copy-button-bg);
      color: var(--text-muted);
      cursor: pointer;
      padding: 0;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }}
    .copy-button::before, .copy-button::after {{
      content: "";
      position: absolute;
      border: 1.4px solid currentColor;
      border-radius: 2px;
      width: 0.5rem;
      height: 0.62rem;
    }}
    .copy-button::before {{
      top: 0.42rem;
      left: 0.48rem;
      background: var(--copy-button-bg);
    }}
    .copy-button::after {{
      top: 0.3rem;
      left: 0.62rem;
      background: var(--copy-button-back);
    }}
    .copy-button:hover, .copy-button:focus {{
      border-color: var(--border-copy-hover);
      color: var(--text-strong);
      background: var(--surface-color);
      outline: none;
    }}
    .copy-button[hidden] {{ display: none; }}
    .empty {{
      margin-top: 0.35rem;
      background: var(--surface-muted);
      border: 1px solid var(--border-soft);
      border-radius: 8px;
      padding: 0.75rem 0.9rem;
      color: var(--text-subtle);
      font-size: 0.875rem;
    }}
    mark {{
      background: var(--mark-bg);
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
      <button type=\"button\" class=\"theme-toggle\" data-theme-toggle aria-label=\"テーマ切替\" title=\"ダークモードに切替\">
        <span class=\"theme-toggle-icon\" aria-hidden=\"true\">☾</span>
      </button>
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
  <div class=\"meta\">
    <strong>{meta}</strong>
    <div class=\"meta-actions\">{meta_actions}</div>
  </div>
  {table}
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      const form = document.querySelector(".search-form");
      const articleInput = document.getElementById("article_q");
      const bodyInput = document.getElementById("body_q");
      const themeToggle = document.querySelector("[data-theme-toggle]");
      const themeIcon = themeToggle ? themeToggle.querySelector(".theme-toggle-icon") : null;

      const THEME_STORAGE_KEY = "archi-law-search-theme";
      const getPreferredTheme = function () {{
        const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
        if (savedTheme === "light" || savedTheme === "dark") {{
          return savedTheme;
        }}
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }};
      const updateThemeToggle = function (theme) {{
        if (!themeToggle || !themeIcon) {{
          return;
        }}
        if (theme === "dark") {{
          themeIcon.textContent = "☀";
          themeToggle.setAttribute("title", "ライトモードに切替");
          themeToggle.setAttribute("aria-label", "ライトモードに切替");
        }} else {{
          themeIcon.textContent = "☾";
          themeToggle.setAttribute("title", "ダークモードに切替");
          themeToggle.setAttribute("aria-label", "ダークモードに切替");
        }}
      }};
      const applyTheme = function (theme, persist) {{
        document.documentElement.dataset.theme = theme;
        updateThemeToggle(theme);
        if (persist) {{
          localStorage.setItem(THEME_STORAGE_KEY, theme);
        }}
      }};

      applyTheme(getPreferredTheme(), false);
      if (themeToggle) {{
        themeToggle.addEventListener("click", function () {{
          const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
          applyTheme(nextTheme, true);
        }});
      }}

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
          return true;
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
          const copyButton = cell.querySelector(".copy-button");
          if (!preview || !full) {{
            return;
          }}
          const expanded = cell.classList.toggle("is-expanded");
          preview.hidden = expanded;
          full.hidden = !expanded;
          if (copyButton) {{
            copyButton.hidden = !expanded;
          }}
        }});
      }});

      const copyText = async function (text) {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(text);
          return true;
        }}

        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        try {{
          document.execCommand("copy");
          return true;
        }} finally {{
          document.body.removeChild(textarea);
        }}
      }};

      const handleCopyButtonClick = async function (button, event) {{
        if (event) {{
          event.preventDefault();
          event.stopPropagation();
        }}
        const text = button.getAttribute("data-copy-text") || "";
        if (!text) {{
          return;
        }}
        const originalTitle = button.getAttribute("title") || "コピー";
        const feedback = button.parentElement ? button.parentElement.querySelector(".copy-feedback") : null;
        if (button._copyFeedbackTimerId) {{
          window.clearTimeout(button._copyFeedbackTimerId);
          button._copyFeedbackTimerId = null;
        }}
        try {{
          await copyText(text);
          button.setAttribute("title", "Copied");
          if (feedback) {{
            feedback.textContent = "コピー済み";
            feedback.hidden = false;
          }}
          window.setTimeout(function () {{
            button.setAttribute("title", originalTitle);
          }}, 1200);
        }} catch (_error) {{
          button.setAttribute("title", "コピー失敗");
          if (feedback) {{
            feedback.textContent = "失敗";
            feedback.hidden = false;
          }}
          window.setTimeout(function () {{
            button.setAttribute("title", originalTitle);
          }}, 1200);
        }}
        if (feedback) {{
          button._copyFeedbackTimerId = window.setTimeout(function () {{
            feedback.hidden = true;
            button._copyFeedbackTimerId = null;
          }}, 1200);
        }}
      }};

      document.querySelectorAll(".copy-button").forEach(function (button) {{
        button.addEventListener("click", async function (event) {{
          await handleCopyButtonClick(button, event);
        }});
      }});

      const bulkCopyButton = document.querySelector(".bulk-copy-button");
      if (bulkCopyButton) {{
        bulkCopyButton.addEventListener("click", async function (event) {{
          await handleCopyButtonClick(bulkCopyButton, event);
        }});
      }}
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
  <script>
    (function () {{
      const storageKey = "archi-law-search-theme";
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      let theme = prefersDark ? "dark" : "light";
      try {{
        const savedTheme = localStorage.getItem(storageKey);
        if (savedTheme === "light" || savedTheme === "dark") {{
          theme = savedTheme;
        }}
      }} catch (_error) {{
      }}
      document.documentElement.dataset.theme = theme;
    }})();
  </script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    :root {{
      color-scheme: light;
      --bg-color: #f4f5f7;
      --surface-color: #ffffff;
      --surface-muted: #f7f9fc;
      --surface-soft: #f8f9fb;
      --text-color: #222222;
      --text-strong: #1a2e4a;
      --text-muted: #4e5968;
      --text-subtle: #5b6572;
      --link-color: #1f3656;
      --accent-color: #3b6ea5;
      --accent-hover: #2d5585;
      --border-color: #dde1e7;
      --border-soft: #d9e2ef;
      --border-row: #eaecef;
      --border-button: #c9d3e0;
      --button-secondary: #5f748e;
      --button-secondary-hover: #4d627b;
      --button-danger: #a44949;
      --button-danger-hover: #883939;
      --nav-bg: #ffffff;
      --button-text: #ffffff;
      --notice-bg: #f7f9fc;
      --notice-text: #1f3656;
      --notice-error-bg: #fff3f3;
      --notice-error-border: #edc7c7;
      --notice-error-text: #8b2e2e;
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg-color: #111722;
      --surface-color: #182131;
      --surface-muted: #1d2738;
      --surface-soft: #151f2e;
      --text-color: #e6ebf2;
      --text-strong: #f2f6fb;
      --text-muted: #aeb9c8;
      --text-subtle: #b6c0cf;
      --link-color: #d9e5f4;
      --accent-color: #628fca;
      --accent-hover: #7aa3db;
      --border-color: #2c3a4f;
      --border-soft: #33445c;
      --border-row: #2a3648;
      --border-button: #415269;
      --button-secondary: #617791;
      --button-secondary-hover: #7590b0;
      --button-danger: #b85a5a;
      --button-danger-hover: #cf7070;
      --nav-bg: #1b2637;
      --button-text: #f7f9fc;
      --notice-bg: #1d2738;
      --notice-text: #edf3fb;
      --notice-error-bg: #3a2024;
      --notice-error-border: #75474d;
      --notice-error-text: #f2c7c7;
    }}
    body {{
      font-family: "Hiragino Sans", "Yu Gothic UI", sans-serif;
      margin: 0;
      padding: 1.5rem 1rem 2rem;
      max-width: 1100px;
      margin-inline: auto;
      background: var(--bg-color);
      color: var(--text-color);
      font-size: 0.9375rem;
      transition: background 0.18s ease, color 0.18s ease;
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
      color: var(--text-strong);
      border-left: 4px solid var(--accent-color);
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
      border: 1px solid var(--border-button);
      border-radius: 6px;
      background: var(--nav-bg);
      color: var(--link-color);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    }}
    .nav-link:hover {{ background: var(--surface-muted); }}
    .theme-toggle {{
      width: 2rem;
      min-width: 2rem;
      height: 2rem;
      padding: 0;
      border: 1px solid var(--border-button);
      border-radius: 999px;
      background: var(--nav-bg);
      color: var(--link-color);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.12s ease;
    }}
    .theme-toggle:hover, .theme-toggle:focus {{
      background: var(--surface-muted);
      border-color: var(--border-color);
      outline: none;
    }}
    .theme-toggle:active {{ transform: translateY(1px); }}
    .theme-toggle-icon {{
      font-size: 0.96rem;
      line-height: 1;
    }}
    .panel {{
      background: var(--surface-color);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 1rem 1.1rem 1.1rem;
    }}
    .panel p {{
      margin: 0 0 0.9rem;
      color: var(--text-muted);
      line-height: 1.6;
    }}
    .notice {{
      margin: 0 0 0.9rem;
      border-radius: 6px;
      padding: 0.65rem 0.8rem;
      font-size: 0.875rem;
      border: 1px solid var(--border-soft);
      background: var(--notice-bg);
      color: var(--notice-text);
    }}
    .notice.is-error {{
      border-color: var(--notice-error-border);
      background: var(--notice-error-bg);
      color: var(--notice-error-text);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 0.875rem;
    }}
    thead th {{
      background: var(--text-strong);
      color: var(--button-text);
      padding: 0.65rem 0.75rem;
      text-align: left;
      white-space: nowrap;
      font-size: 0.8125rem;
    }}
    tbody td {{
      border-top: 1px solid var(--border-row);
      padding: 0.78rem 0.75rem;
      vertical-align: middle;
    }}
    tbody tr:nth-child(even) {{ background: var(--surface-soft); }}
    .law-name {{
      font-weight: 600;
      color: var(--link-color);
      line-height: 1.5;
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 1.9rem;
      padding: 0.2rem 0.65rem;
      border-radius: 999px;
      border: 1px solid var(--border-button);
      background: var(--surface-muted);
      color: var(--link-color);
      font-size: 0.8125rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .status-badge.is-off {{
      background: var(--surface-soft);
      color: var(--text-subtle);
      border-color: var(--border-color);
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
      background: var(--accent-color);
      color: var(--button-text);
    }}
    button:hover {{ background: var(--accent-hover); }}
    .button-secondary {{
      background: var(--button-secondary);
    }}
    .button-secondary:hover {{
      background: var(--button-secondary-hover);
    }}
    .button-danger {{
      background: var(--button-danger);
    }}
    .button-danger:hover {{
      background: var(--button-danger-hover);
    }}
    .empty {{
      margin-top: 0.6rem;
      color: var(--text-subtle);
      font-size: 0.875rem;
    }}
  </style>
</head>
<body>
  <div class=\"page-header\">
    <h1>法令 Settings</h1>
    <div class=\"header-actions\">
      <button type=\"button\" class=\"theme-toggle\" data-theme-toggle aria-label=\"テーマ切替\" title=\"ダークモードに切替\">
        <span class=\"theme-toggle-icon\" aria-hidden=\"true\">☾</span>
      </button>
      <a class=\"nav-link\" href=\"/\">検索へ戻る</a>
    </div>
  </div>
  <div class=\"panel\">
    <p>検索対象に含める法令を管理します。取込済の法令は検索対象になり、未取込の法令はここから追加できます。</p>
    {notice}
    {rows}
  </div>
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      const themeToggle = document.querySelector("[data-theme-toggle]");
      const themeIcon = themeToggle ? themeToggle.querySelector(".theme-toggle-icon") : null;
      const THEME_STORAGE_KEY = "archi-law-search-theme";
      const getPreferredTheme = function () {{
        const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
        if (savedTheme === "light" || savedTheme === "dark") {{
          return savedTheme;
        }}
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }};
      const updateThemeToggle = function (theme) {{
        if (!themeToggle || !themeIcon) {{
          return;
        }}
        if (theme === "dark") {{
          themeIcon.textContent = "☀";
          themeToggle.setAttribute("title", "ライトモードに切替");
          themeToggle.setAttribute("aria-label", "ライトモードに切替");
        }} else {{
          themeIcon.textContent = "☾";
          themeToggle.setAttribute("title", "ダークモードに切替");
          themeToggle.setAttribute("aria-label", "ダークモードに切替");
        }}
      }};
      const applyTheme = function (theme, persist) {{
        document.documentElement.dataset.theme = theme;
        updateThemeToggle(theme);
        if (persist) {{
          localStorage.setItem(THEME_STORAGE_KEY, theme);
        }}
      }};

      applyTheme(getPreferredTheme(), false);
      if (themeToggle) {{
        themeToggle.addEventListener("click", function () {{
          const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
          applyTheme(nextTheme, true);
        }});
      }}
    }});
  </script>
</body>
</html>
"""


class LawSearchHandler(BaseHTTPRequestHandler):
    db_path = str(DEFAULT_DB_PATH)
    LAW_DISPLAY_LABELS = {}

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
            meta_actions=self._render_meta_actions(rows, article_query, body_query),
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
    def _plain_text_for_copy(text: str) -> str:
        return (text or "").replace("<mark>", "").replace("</mark>", "")

    @classmethod
    def _build_copy_text(cls, law_name: str, article_no: str, full_body: str) -> str:
        return "\n".join([law_name, article_no, cls._plain_text_for_copy(full_body)])

    @classmethod
    def _build_bulk_copy_text(cls, rows, article_query: str = "", body_query: str = "") -> str:
        condition_lines = [
            "検索条件",
            f"条番号: {article_query or 'なし'}",
            f"本文キーワード: {body_query or 'なし'}",
        ]
        blocks = [cls._build_copy_text(law_name, article_no, full_body) for law_name, article_no, _body, full_body in rows]
        if not blocks:
            return "\n".join(condition_lines)
        return "\n".join(condition_lines) + "\n\n" + "\n\n".join(blocks)

    @staticmethod
    def _extract_leading_heading(body_text: str, max_scan_length: int = 240, max_heading_length: int = 80) -> str:
        body_text = (body_text or "").strip()
        if not body_text:
            return ""

        match = re.match(r"（[^）]{1," + str(max_heading_length) + r"}）", body_text[:max_scan_length])
        if match is None:
            return ""
        return match.group(0)

    @classmethod
    def _normalize_heading_candidate(cls, text: str) -> str:
        text = (text or "").replace("<mark>", "").replace("</mark>", "")
        return text.lstrip("… \n\r\t")

    @classmethod
    def _snippet_already_shows_heading(cls, heading: str, snippet: str) -> bool:
        normalized_heading = cls._normalize_heading_candidate(heading)
        normalized_snippet = cls._normalize_heading_candidate(snippet)
        if not normalized_heading:
            return False
        return normalized_heading in normalized_snippet[: max(len(normalized_heading) + 24, 120)]

    @classmethod
    def _prepend_heading_to_snippet(cls, body_text: str, snippet: str) -> str:
        heading = cls._extract_leading_heading(body_text)
        if not heading:
            return snippet
        if cls._snippet_already_shows_heading(heading, snippet):
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

    def _render_meta_actions(self, rows, article_query: str = "", body_query: str = "") -> str:
        if not rows:
            return ""
        copy_text = html.escape(self._build_bulk_copy_text(rows, article_query, body_query), quote=True)
        return (
            f"<span class='copy-feedback' hidden>コピー済み</span>"
            f"<button type='button' class='bulk-copy-button' title='全結果をコピー' "
            f"data-copy-text='{copy_text}'>全結果をコピー</button>"
        )

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
            copy_text = html.escape(self._build_copy_text(law_name, article_no, full_body), quote=True)
            copy_hidden_attr = " hidden" if is_expandable else ""
            body_html = (
                "<div class='body-wrap'>"
                f"<span class='copy-feedback body-copy-feedback' hidden>コピー済み</span>"
                f"<button type='button' class='copy-button' title='コピー' data-copy-text='{copy_text}'{copy_hidden_attr}></button>"
                f"<div class='body-preview'>{safe_body}</div>"
            )
            if is_expandable:
                body_html += f"<div class='body-full' hidden>{safe_full_body}</div>"
            body_html += "</div>"
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

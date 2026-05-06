"""SQLiteに保存した法令データをブラウザから検索するローカルWeb UI。"""

import argparse
from contextlib import closing
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if __package__ in (None, ""):
    from kokuji_database import DEFAULT_KOKUJI_DB_PATH, detect_link_label, get_kokuji_db_status, get_kokuji_text_by_id, search_kokuji
    from law_database import LawSource, connect_db, delete_law, ensure_db, fts5_enabled, law_exists, list_installed_law_ids, replace_law
    from law_registry import LAW_BY_ID, LAW_REGISTRY
    from laws_api import fetch_law_xml
    from number_text_utils import int_to_kanji, normalize_num, normalize_separators
    from source_registry import get_source_status
else:
    from .kokuji_database import DEFAULT_KOKUJI_DB_PATH, detect_link_label, get_kokuji_db_status, get_kokuji_text_by_id, search_kokuji
    from .law_database import LawSource, connect_db, delete_law, ensure_db, fts5_enabled, law_exists, list_installed_law_ids, replace_law
    from .law_registry import LAW_BY_ID, LAW_REGISTRY
    from .laws_api import fetch_law_xml
    from .number_text_utils import int_to_kanji, normalize_num, normalize_separators
    from .source_registry import get_source_status

DEFAULT_DB_PATH = REPO_ROOT / "data" / "laws.db"
DEFAULT_KOKUJI_PATH = DEFAULT_KOKUJI_DB_PATH
DEFAULT_EXPORTS_DIR = REPO_ROOT / "output" / "exports"
DOWNLOAD_RESULTS_LIMIT = 100

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
      --placeholder-color: #8b95a3;
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
      --table-head-bg: #1a2e4a;
      --table-head-text: #ffffff;
      --mark-bg: #ffdca8;
      --mark-text: inherit;
      --shadow-ring: 0 0 0 3px rgba(59, 110, 165, 0.15);
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg-color: #0d1117;
      --surface-color: #161b22;
      --surface-muted: #1f242d;
      --surface-soft: #121821;
      --surface-hover: #202833;
      --surface-accent: #1b232d;
      --text-color: #e6edf3;
      --text-strong: #f0f6fc;
      --text-muted: #9da7b3;
      --text-subtle: #8b949e;
      --placeholder-color: #7d8590;
      --link-color: #c9d1d9;
      --accent-color: #8b949e;
      --accent-hover: #a3acb7;
      --accent-soft: rgba(139, 148, 158, 0.22);
      --border-color: #30363d;
      --border-soft: #30363d;
      --border-table: #2d333b;
      --border-input: #30363d;
      --border-button: #30363d;
      --border-copy: #3d444d;
      --border-copy-hover: #6e7681;
      --nav-bg: #161b22;
      --button-text: #f0f6fc;
      --meta-strong: #f0f6fc;
      --copy-button-bg: rgba(22, 27, 34, 0.94);
      --copy-button-back: rgba(13, 17, 23, 0.98);
      --feedback-bg: rgba(22, 27, 34, 0.96);
      --feedback-border: #444c56;
      --table-head-bg: #21262d;
      --table-head-text: #f0f6fc;
      --mark-bg: #f2cc60;
      --mark-text: #24292f;
      --shadow-ring: 0 0 0 3px rgba(110, 118, 129, 0.22);
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
    .header-actions form {{
      margin: 0;
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
    .shutdown-link {{
      background: var(--surface-soft);
    }}
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
    .field.is-number-query {{
      flex: 0 1 10rem;
      min-width: 8rem;
    }}
    .field.is-main-query {{
      flex: 1 1 22rem;
      min-width: 14rem;
    }}
    label {{ font-weight: 600; font-size: 0.8125rem; color: var(--text-muted); }}
    input[type=text] {{
      width: 100%;
      max-width: 100%;
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
    input[type=text]::placeholder {{
      color: var(--placeholder-color);
    }}
    .source-switch-wrap {{
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      margin-left: auto;
      align-items: flex-end;
      justify-content: flex-end;
      min-width: 11rem;
      align-self: end;
    }}
    .search-submit {{
      flex: 0 0 auto;
      align-self: end;
      min-height: 2.35rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .source-switch-label {{
      align-self: stretch;
      text-align: right;
    }}
    .source-switch {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      border: 1px solid var(--border-button);
      border-radius: 999px;
      background: var(--surface-soft);
      padding: 0.18rem;
      gap: 0.2rem;
      flex-wrap: nowrap;
      min-height: 2.35rem;
    }}
    .source-option {{
      position: relative;
    }}
    .source-option input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .source-option-label {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 4.3rem;
      min-height: 2rem;
      padding: 0.3rem 0.85rem;
      border-radius: 999px;
      color: var(--text-subtle);
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
    }}
    .source-option input:checked + .source-option-label {{
      background: var(--accent-color);
      color: var(--button-text);
      box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.04);
    }}
    .source-option input:focus + .source-option-label {{
      box-shadow: var(--shadow-ring);
    }}
    .source-option input:not(:checked) + .source-option-label:hover {{
      background: var(--surface-muted);
      color: var(--text-strong);
    }}
    .source-option input:disabled + .source-option-label {{
      cursor: not-allowed;
      opacity: 0.45;
    }}
    .source-note {{
      margin: 0;
      font-size: 0.76rem;
      color: var(--text-subtle);
      text-align: right;
    }}
    .source-note:empty {{ display: none; }}
    .search-notice {{
      margin: 0 0 0.6rem;
      background: var(--surface-muted);
      border: 1px solid var(--border-soft);
      border-radius: 6px;
      padding: 0.45rem 0.7rem;
      font-size: 0.84rem;
      color: var(--text-muted);
    }}
    .search-notice.is-error {{
      border-color: var(--feedback-border);
      color: var(--text-strong);
    }}
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
    .text-download-button {{
      padding: 0.32rem 0.72rem;
      background: var(--surface-color);
      color: var(--link-color);
      border: 1px solid var(--border-button);
      border-radius: 5px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .text-download-button:hover, .text-download-button:focus {{
      background: var(--surface-muted);
      border-color: var(--border-input);
      color: var(--text-strong);
      outline: none;
    }}
    .text-download-button[hidden] {{ display: none; }}
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
      background: var(--table-head-bg);
      color: var(--table-head-text);
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
    .law {{
      width: 17%;
      white-space: normal;
      color: var(--accent-color);
      font-weight: 600;
      line-height: 1.58;
    }}
    .article {{
      width: 11%;
      white-space: normal;
      line-height: 1.5;
      font-variant-numeric: tabular-nums;
    }}
    .body {{
      width: 72%;
      min-width: 20rem;
      white-space: pre-wrap;
      line-height: 1.72;
      font-size: 0.9rem;
    }}
    .kokuji-name {{
      white-space: normal;
      line-height: 1.6;
      font-weight: 600;
      width: 26%;
    }}
    .kokuji-number {{
      width: 16%;
      white-space: normal;
      line-height: 1.5;
      font-variant-numeric: tabular-nums;
    }}
    .kokuji-snippet {{
      width: 48%;
      min-width: 20rem;
    }}
    .kokuji-link-cell {{
      white-space: nowrap;
      width: 10%;
    }}
    .kokuji-link-stack {{
      display: inline-flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.38rem;
      max-width: 100%;
    }}
    .kokuji-link-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 4.6rem;
      max-width: 100%;
      padding: 0.24rem 0.55rem;
      background: var(--surface-muted);
      color: var(--link-color);
      border: 1px solid var(--border-button);
      border-radius: 5px;
      font-size: 0.76rem;
      font-weight: 600;
      line-height: 1.35;
      text-decoration: none;
    }}
    .kokuji-link-button:hover,
    .kokuji-link-button:focus,
    .kokuji-copy-button:hover,
    .kokuji-copy-button:focus {{
      background: var(--surface-hover);
      border-color: var(--border-input);
      color: var(--text-strong);
      outline: none;
    }}
    .kokuji-link-stack .copy-button {{
      position: relative;
      display: inline-flex;
      flex: 0 0 auto;
    }}
    .kokuji-copy-button:disabled {{
      cursor: not-allowed;
      opacity: 0.5;
    }}
    .kokuji-copy-feedback {{
      position: static;
      top: auto;
      right: auto;
      transform: none;
      font-size: 0.72rem;
    }}
    .kokuji-meta {{
      margin-top: 0.28rem;
      font-size: 0.76rem;
      color: var(--text-subtle);
      line-height: 1.45;
    }}
    .kokuji-year {{
      font-size: 0.72rem;
    }}
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
      color: var(--mark-text);
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
      {shutdown_action}
      <a class=\"nav-link settings-link\" href=\"{settings_href}\">Settings</a>
    </div>
  </div>
  <form method=\"get\" action=\"/\" class=\"search-form\">
    <div class=\"search-row\">
      <div class=\"field is-number-query\">
        <label for=\"number_query\">{number_label}</label>
        <input id=\"number_query\" type=\"text\" name=\"{number_field_name}\" value=\"{number_query}\" placeholder=\"{number_placeholder}\" />
      </div>
      <div class=\"field is-main-query\">
        <label for=\"q\">検索キーワード</label>
        <input id=\"q\" type=\"text\" name=\"q\" value=\"{body_query}\" placeholder=\"{query_placeholder}\" />
      </div>
      <div class=\"source-switch-wrap\">
        <label class=\"source-switch-label\">検索対象</label>
        <div class=\"source-switch\">
          <label class=\"source-option\">
            <input type=\"radio\" name=\"source\" value=\"law\"{law_checked} />
            <span class=\"source-option-label\">法令</span>
          </label>
          <label class=\"source-option\">
            <input type=\"radio\" name=\"source\" value=\"kokuji\"{kokuji_checked}{kokuji_disabled} />
            <span class=\"source-option-label\">告示</span>
          </label>
        </div>
        <p class=\"source-note\">{source_note}</p>
      </div>
      <button type=\"submit\" class=\"search-submit\">検索</button>
    </div>
  </form>
  {search_notice}
  <div class=\"meta\"{meta_hidden}>
    <strong>{meta}</strong>
    <div class=\"meta-actions\">{meta_actions}</div>
  </div>
  {table}
  <script>
    document.addEventListener("DOMContentLoaded", function () {{
      const form = document.querySelector(".search-form");
      const numberInput = document.getElementById("number_query");
      const queryInput = document.getElementById("q");
      const sourceInputs = Array.from(document.querySelectorAll("input[name='source']"));
      const themeToggle = document.querySelector("[data-theme-toggle]");
      const themeIcon = themeToggle ? themeToggle.querySelector(".theme-toggle-icon") : null;
      const focusStorageKey = "archi-law-search-focus";

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

      if (!form || !numberInput || !queryInput) {{
        return;
      }}

      const numberLabel = form.querySelector("label[for='number_query']");
      const sourceConfig = {{
        law: {{
          numberLabel: "条番号",
          numberFieldName: "article",
          numberPlaceholder: "例: 112",
          keywordPlaceholder: "例: 防火、容積率、準耐火",
        }},
        kokuji: {{
          numberLabel: "告示番号",
          numberFieldName: "notice_number",
          numberPlaceholder: "例: 1436号",
          keywordPlaceholder: "例: 排煙、防火設備、準不燃",
        }},
      }};
      const updateQueryPresentation = function () {{
        const selectedSource = sourceInputs.find(function (input) {{ return input.checked; }});
        const sourceValue = selectedSource ? selectedSource.value : "law";
        const config = sourceConfig[sourceValue] || sourceConfig.law;
        if (numberLabel) {{
          numberLabel.textContent = config.numberLabel;
        }}
        numberInput.setAttribute("name", config.numberFieldName);
        numberInput.setAttribute("placeholder", config.numberPlaceholder);
        queryInput.setAttribute("placeholder", config.keywordPlaceholder);
      }};
      updateQueryPresentation();

      const AUTO_SUBMIT_DELAY_MS = 700;
      let timerId = null;
      let isComposing = false;
      let isSubmitting = false;
      window.__suppressShutdownOnUnload = false;

      const isLocalShutdownHost = function () {{
        return ["127.0.0.1", "localhost", "::1"].indexOf(window.location.hostname) >= 0;
      }};

      const persistFocusState = function (input) {{
        if (!input || !input.name) {{
          return;
        }}
        try {{
          sessionStorage.setItem(
            focusStorageKey,
            JSON.stringify({{
              name: input.name,
              selectionStart: typeof input.selectionStart === "number" ? input.selectionStart : null,
              selectionEnd: typeof input.selectionEnd === "number" ? input.selectionEnd : null,
            }})
          );
        }} catch (_error) {{
        }}
      }};

      const persistActiveFocusState = function () {{
        const activeElement = document.activeElement;
        if (!(activeElement instanceof HTMLInputElement)) {{
          return;
        }}
        if (activeElement.form !== form) {{
          return;
        }}
        persistFocusState(activeElement);
      }};

      const restoreFocusState = function () {{
        let savedState = null;
        try {{
          savedState = JSON.parse(sessionStorage.getItem(focusStorageKey) || "null");
        }} catch (_error) {{
          savedState = null;
        }}
        if (!savedState || !savedState.name) {{
          return;
        }}
        const target = form.querySelector("input[name='" + savedState.name + "']");
        if (!(target instanceof HTMLInputElement)) {{
          return;
        }}
        target.focus();
        const valueLength = target.value.length;
        const start =
          typeof savedState.selectionStart === "number" ? Math.min(savedState.selectionStart, valueLength) : valueLength;
        const end = typeof savedState.selectionEnd === "number" ? Math.min(savedState.selectionEnd, valueLength) : start;
        try {{
          target.setSelectionRange(start, end);
        }} catch (_error) {{
        }}
      }};

      restoreFocusState();

      const clearScheduledSubmit = function () {{
        if (timerId !== null) {{
          clearTimeout(timerId);
          timerId = null;
        }}
      }};

      const shouldAutoSubmit = function () {{
        const numberValue = numberInput.value.trim();
        const queryValue = queryInput.value.trim();
        const selectedSource = sourceInputs.find(function (input) {{ return input.checked; }});
        const sourceValue = selectedSource ? selectedSource.value : "law";
        const articleLikePattern = /^(?:第)?[0-9０-９一二三四五六七八九十百千〇零]+(?:条)?(?:[-の][0-9０-９一二三四五六七八九十百千〇零]+)?$/;
        if (isComposing) {{
          return false;
        }}
        if (!numberValue && !queryValue) {{
          return true;
        }}
        if (numberValue) {{
          return true;
        }}
        if (sourceValue === "law" && articleLikePattern.test(queryValue)) {{
          return true;
        }}
        if (queryValue.length < 2) {{
          return false;
        }}
        return true;
      }};

      const submitForm = function () {{
        if (isSubmitting) {{
          return;
        }}
        isSubmitting = true;
        window.__suppressShutdownOnUnload = true;
        persistActiveFocusState();
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

      [numberInput, queryInput].forEach(function (input) {{
        input.addEventListener("focus", function () {{
          persistFocusState(input);
        }});
        input.addEventListener("click", function () {{
          persistFocusState(input);
        }});
        input.addEventListener("keyup", function () {{
          persistFocusState(input);
        }});
        input.addEventListener("input", scheduleSubmit);
        input.addEventListener("compositionstart", handleCompositionStart);
        input.addEventListener("compositionend", handleCompositionEnd);
      }});
      sourceInputs.forEach(function (input) {{
        input.addEventListener("change", function () {{
          if (input.disabled) {{
            return;
          }}
          persistFocusState(numberInput);
          updateQueryPresentation();
          submitForm();
        }});
      }});
      form.addEventListener("submit", function () {{
        isSubmitting = true;
        window.__suppressShutdownOnUnload = true;
        persistActiveFocusState();
        clearScheduledSubmit();
      }});

      document.querySelectorAll(".text-download-button, .settings-link").forEach(function (element) {{
        element.addEventListener("click", function () {{
          window.__suppressShutdownOnUnload = true;
          persistActiveFocusState();
        }});
      }});

      window.addEventListener("pagehide", function () {{
        if (!isLocalShutdownHost()) {{
          return;
        }}
        if (window.__suppressShutdownOnUnload) {{
          return;
        }}
        if (typeof navigator.sendBeacon !== "function") {{
          return;
        }}
        try {{
          navigator.sendBeacon("/shutdown", "");
        }} catch (_error) {{
        }}
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

      document.querySelectorAll(".kokuji-copy-button").forEach(function (button) {{
        button.addEventListener("click", async function (event) {{
          event.preventDefault();
          event.stopPropagation();
          if (button.disabled) {{
            return;
          }}
          const noticeId = button.getAttribute("data-notice-id") || button.getAttribute("data-kokuji-id");
          if (!noticeId) {{
            return;
          }}
          const feedback = button.parentElement ? button.parentElement.querySelector(".kokuji-copy-feedback") : null;
          try {{
            const response = await fetch("/api/kokuji_text?id=" + encodeURIComponent(noticeId));
            if (!response.ok) {{
              throw new Error("fetch failed");
            }}
            const payload = await response.json();
            await copyText(payload.full_text || "");
            if (feedback) {{
              feedback.textContent = "コピー済み";
              feedback.hidden = false;
              window.setTimeout(function () {{
                feedback.hidden = true;
              }}, 1200);
            }}
          }} catch (_error) {{
            if (feedback) {{
              feedback.textContent = "失敗";
              feedback.hidden = false;
              window.setTimeout(function () {{
                feedback.hidden = true;
              }}, 1200);
            }}
          }}
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
      --placeholder-color: #8b95a3;
      --link-color: #1f3656;
      --accent-color: #3b6ea5;
      --accent-hover: #2d5585;
      --border-color: #dde1e7;
      --border-soft: #d9e2ef;
      --border-row: #eaecef;
      --border-button: #c9d3e0;
      --table-head-bg: #1a2e4a;
      --table-head-text: #ffffff;
      --mark-text: inherit;
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
      --bg-color: #0d1117;
      --surface-color: #161b22;
      --surface-muted: #1f242d;
      --surface-soft: #121821;
      --text-color: #e6edf3;
      --text-strong: #f0f6fc;
      --text-muted: #9da7b3;
      --text-subtle: #8b949e;
      --placeholder-color: #7d8590;
      --link-color: #c9d1d9;
      --accent-color: #8b949e;
      --accent-hover: #a3acb7;
      --border-color: #30363d;
      --border-soft: #30363d;
      --border-row: #2d333b;
      --border-button: #30363d;
      --table-head-bg: #21262d;
      --table-head-text: #f0f6fc;
      --mark-text: #24292f;
      --button-secondary: #434c56;
      --button-secondary-hover: #59636e;
      --button-danger: #da6d75;
      --button-danger-hover: #f0888f;
      --nav-bg: #161b22;
      --button-text: #f0f6fc;
      --notice-bg: #1f242d;
      --notice-text: #f0f6fc;
      --notice-error-bg: #2d1f23;
      --notice-error-border: #5c2f35;
      --notice-error-text: #ffd7d5;
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
      background: var(--table-head-bg);
      color: var(--table-head-text);
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
      <a class=\"nav-link back-link\" href=\"{back_href}\">検索へ戻る</a>
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
      window.__suppressShutdownOnUnload = false;
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

      const isLocalShutdownHost = function () {{
        return ["127.0.0.1", "localhost", "::1"].indexOf(window.location.hostname) >= 0;
      }};

      document.querySelectorAll(".back-link, .actions form").forEach(function (element) {{
        element.addEventListener("click", function () {{
          window.__suppressShutdownOnUnload = true;
        }});
        element.addEventListener("submit", function () {{
          window.__suppressShutdownOnUnload = true;
        }});
      }});

      window.addEventListener("pagehide", function () {{
        if (!isLocalShutdownHost()) {{
          return;
        }}
        if (window.__suppressShutdownOnUnload) {{
          return;
        }}
        if (typeof navigator.sendBeacon !== "function") {{
          return;
        }}
        try {{
          navigator.sendBeacon("/shutdown", "");
        }} catch (_error) {{
        }}
      }});
    }});
  </script>
</body>
</html>
"""


class LawSearchHandler(BaseHTTPRequestHandler):
    db_path = str(DEFAULT_DB_PATH)
    kokuji_db_path = str(DEFAULT_KOKUJI_PATH)
    LAW_DISPLAY_LABELS = {}
    VALID_SOURCES = {"law", "kokuji"}
    DEFAULT_EXPORTS_DIR = DEFAULT_EXPORTS_DIR

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._handle_search_page(parsed)
            return
        if parsed.path == "/api/kokuji_text":
            self._handle_kokuji_text_api(parsed)
            return
        if parsed.path in {"/download_results", "/export_results"}:
            self._handle_export_results(parsed)
            return
        if parsed.path == "/settings":
            self._handle_settings_page(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/shutdown":
            self._handle_shutdown_request()
            return
        if parsed.path != "/settings/action":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        self._handle_settings_action()

    def log_message(self, format, *args):
        return

    def _handle_search_page(self, parsed):
        source_state = self._get_kokuji_source_state()
        requested_source = self._parse_source(parsed.query)
        source = self._resolve_source(requested_source)
        article_query, notice_number_query, body_query = self._parse_search_inputs(parsed.query)
        display_article_query, display_notice_number_query, display_body_query = self._parse_search_display_inputs(parsed.query)
        message, message_kind = self._parse_flash_message(parsed.query)
        number_query = notice_number_query if source == "kokuji" else article_query
        display_number_query = display_notice_number_query if source == "kokuji" else display_article_query
        if source == "law" and not article_query and notice_number_query:
            article_query = notice_number_query
            number_query = article_query
            if not display_article_query and display_notice_number_query:
                display_number_query = display_notice_number_query
        if source == "kokuji" and not notice_number_query and article_query:
            notice_number_query = article_query
            number_query = notice_number_query
            if not display_notice_number_query and display_article_query:
                display_number_query = display_article_query
        has_search_inputs = self._has_search_inputs(number_query, body_query)
        query = self._display_query(number_query, body_query)

        rows = []
        warning_parts: list[str] = []
        if has_search_inputs:
            if source == "kokuji":
                rows, warning = self.search_kokuji_notice(notice_number_query, body_query, source_state)
            else:
                rows, warning = self.search_law_inputs(article_query, body_query)
            if warning:
                warning_parts.append(warning)

        if has_search_inputs:
            meta = self._build_meta(rows, " / ".join(warning_parts))
            meta_hidden = ""
        else:
            meta = ""
            meta_hidden = " hidden"

        empty_message = self._empty_message_for_source(source, source_state) if has_search_inputs else "キーワードまたは条番号を入力してください。"

        body = SEARCH_PAGE_TEMPLATE.format(
            shutdown_action=self._render_shutdown_action(),
            settings_href=html.escape(self._build_settings_href(parsed.query), quote=True),
            number_query=html.escape(display_number_query),
            body_query=html.escape(display_body_query),
            number_label=html.escape(self._number_label_for_source(source)),
            number_field_name=html.escape(self._number_field_name_for_source(source)),
            number_placeholder=html.escape(self._number_placeholder_for_source(source)),
            query_placeholder=html.escape(self._query_placeholder_for_source(source)),
            law_checked=" checked" if source == "law" else "",
            kokuji_checked=" checked" if source == "kokuji" else "",
            kokuji_disabled=" disabled" if not source_state["enabled"] else "",
            source_note=html.escape(source_state["note"]),
            search_notice=self._render_search_notice(message, message_kind),
            meta=html.escape(meta),
            meta_hidden=meta_hidden,
            meta_actions=self._render_meta_actions(
                source=source,
                article_query=article_query,
                notice_number_query=notice_number_query,
                body_query=body_query,
            ),
            table=self.render_results(rows, source=source, empty_message=empty_message),
        ).encode("utf-8")
        self._send_html(body)

    def _handle_kokuji_text_api(self, parsed):
        params = parse_qs(parsed.query)
        notice_id_raw = params.get("id", [""])[0].strip()
        try:
            notice_id = int(notice_id_raw)
            payload = get_kokuji_text_by_id(Path(self.kokuji_db_path), notice_id)
        except (ValueError, KeyError, FileNotFoundError, sqlite3.DatabaseError):
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(payload)

    def _handle_export_results(self, parsed):
        source = self._parse_source(parsed.query)
        article_query, notice_number_query, body_query = self._parse_search_inputs(parsed.query)
        if source == "law" and not article_query and notice_number_query:
            article_query = notice_number_query
        if source == "kokuji" and not notice_number_query and article_query:
            notice_number_query = article_query

        try:
            export_path, result_count = self._save_results_txt(
                source=source,
                article_query=article_query,
                notice_number_query=notice_number_query,
                body_query=body_query,
            )
        except Exception as exc:
            self._redirect_to_search(parsed.query, "error", f"TXT保存に失敗しました: {exc}")
            return

        if export_path is None:
            self._redirect_to_search(parsed.query, "error", "TXT保存に失敗しました。")
            return

        self._open_exports_folder(export_path.parent)
        export_label = self._display_export_path(export_path)
        message = f"TXTを保存しました: {export_label}"
        if result_count == 0:
            message = f"検索結果は0件でした。TXTを保存しました: {export_label}"
        self._redirect_to_search(parsed.query, "info", message)

    def _redirect_to_search(self, query_string: str, kind: str, message: str):
        params = parse_qs(query_string, keep_blank_values=True)
        params["kind"] = [kind]
        params["message"] = [message]
        encoded = urlencode(params, doseq=True)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?{encoded}")
        self.end_headers()

    def _handle_settings_page(self, parsed):
        params = parse_qs(parsed.query, keep_blank_values=True)
        message = params.get("message", [""])[0].strip()
        kind = params.get("kind", ["info"])[0].strip()
        return_to = params.get("return_to", [""])[0]
        notice = self._render_notice(message, kind) if message else ""

        installed_ids = set()
        conn = self._connect_existing_db()
        if conn is not None:
            with closing(conn):
                installed_ids = list_installed_law_ids(conn)

        body = SETTINGS_PAGE_TEMPLATE.format(
            back_href=html.escape(self._build_search_return_href(return_to), quote=True),
            notice=notice,
            rows=self.render_settings_table(installed_ids, return_to=return_to),
        ).encode("utf-8")
        self._send_html(body)

    def _handle_settings_action(self):
        params = self._read_post_params()
        action = params.get("action", [""])[0].strip()
        law_id = params.get("law_id", [""])[0].strip()
        return_to = params.get("return_to", [""])[0]
        law = LAW_BY_ID.get(law_id)
        if law is None:
            self._redirect_with_message("error", "対象の法令が見つかりません。", return_to=return_to)
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
            self._redirect_with_message("error", f"{law.law_name}: {exc}", return_to=return_to)
            return

        if action == "add":
            self._redirect_with_message("info", f"{law.law_name} を追加しました。{count}件の条文を取込済です。", return_to=return_to)
        elif action == "refresh":
            self._redirect_with_message("info", f"{law.law_name} を更新しました。{count}件の条文を再取込しました。", return_to=return_to)
        else:
            self._redirect_with_message("info", f"{law.law_name} を削除しました。", return_to=return_to)

    def _send_html(self, body: bytes):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect_with_message(self, kind: str, message: str, return_to: str = ""):
        payload = {"kind": kind, "message": message}
        if return_to:
            payload["return_to"] = return_to
        query = urlencode(payload)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/settings?{query}")
        self.end_headers()

    def _connect_existing_db(self) -> Optional[sqlite3.Connection]:
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
        return parse_qs(payload, keep_blank_values=True)

    @staticmethod
    def _parse_flash_message(query_string: str) -> Tuple[str, str]:
        params = parse_qs(query_string)
        return params.get("message", [""])[0].strip(), params.get("kind", ["info"])[0].strip()

    @staticmethod
    def _render_notice(message: str, kind: str) -> str:
        css_class = "notice is-error" if kind == "error" else "notice"
        return f"<div class='{css_class}'>{html.escape(message)}</div>"

    @staticmethod
    def _render_search_notice(message: str, kind: str) -> str:
        if not message:
            return ""
        css_class = "search-notice is-error" if kind == "error" else "search-notice"
        return f"<div class='{css_class}'>{html.escape(message)}</div>"

    @staticmethod
    def _parse_search_inputs(query_string: str) -> Tuple[str, str, str]:
        params = parse_qs(query_string, keep_blank_values=True)
        article_query = params.get("article", [""])[0].strip() or params.get("article_q", [""])[0].strip()
        notice_number_query = params.get("notice_number", [""])[0].strip()
        body_query = params.get("body_q", [""])[0].strip()
        legacy_query = params.get("q", [""])[0].strip()
        if not body_query and legacy_query:
            body_query = legacy_query
        return article_query, notice_number_query, body_query

    @staticmethod
    def _parse_search_display_inputs(query_string: str) -> Tuple[str, str, str]:
        params = parse_qs(query_string, keep_blank_values=True)
        article_query = params.get("article", [""])[0] or params.get("article_q", [""])[0]
        notice_number_query = params.get("notice_number", [""])[0]
        body_query = params.get("body_q", [""])[0]
        legacy_query = params.get("q", [""])[0]
        if not body_query and legacy_query:
            body_query = legacy_query
        return article_query, notice_number_query, body_query

    @classmethod
    def _parse_source(cls, query_string: str) -> str:
        params = parse_qs(query_string)
        return cls._normalize_source(params.get("source", ["law"])[0].strip())

    @classmethod
    def _normalize_source(cls, source: str) -> str:
        return source if source in cls.VALID_SOURCES else "law"

    @staticmethod
    def _display_query(number_query: str, body_query: str) -> str:
        return number_query or body_query

    @staticmethod
    def _has_search_inputs(number_query: str, body_query: str) -> bool:
        return bool(number_query or body_query)

    @staticmethod
    def _number_label_for_source(source: str) -> str:
        return "告示番号" if source == "kokuji" else "条番号"

    @staticmethod
    def _query_placeholder_for_source(source: str) -> str:
        if source == "kokuji":
            return "例: 排煙、防火設備、準不燃"
        return "例: 防火、容積率、準耐火"

    @staticmethod
    def _number_placeholder_for_source(source: str) -> str:
        return "例: 1436号" if source == "kokuji" else "例: 112"

    @staticmethod
    def _number_field_name_for_source(source: str) -> str:
        return "notice_number" if source == "kokuji" else "article"

    @staticmethod
    def _select_search_query(article_query: str, body_query: str) -> Tuple[str, str]:
        if article_query:
            return "article", article_query
        if body_query:
            return "body", body_query
        return "", ""

    @classmethod
    def _is_probable_article_query(cls, query: str) -> bool:
        if not query:
            return False
        _variants, parsed_article = cls._article_query_variants(query)
        main_num, _branch_num = parsed_article
        return main_num is not None

    @staticmethod
    def _build_meta(rows, warning: str) -> str:
        meta = f"{len(rows)}件ヒット"
        if warning:
            meta = f"{meta}（{warning}）"
        return meta

    def _get_kokuji_source_state(self) -> dict[str, object]:
        source_info = get_source_status("kokuji", Path(self.db_path))
        db_ok, db_message = get_kokuji_db_status(self.kokuji_db_path)
        active = bool(source_info["is_active"])
        enabled = active and db_ok

        if enabled:
            note = ""
        elif not active:
            note = "告示検索は現在無効です"
        else:
            note = db_message

        return {
            "active": active,
            "db_ok": db_ok,
            "enabled": enabled,
            "note": note,
        }

    @staticmethod
    def _resolve_source(requested_source: str) -> str:
        return "kokuji" if requested_source == "kokuji" else "law"

    @staticmethod
    def _empty_message_for_source(source: str, source_state: dict[str, object]) -> str:
        if source == "kokuji" and not source_state["db_ok"]:
            return "告示DBが未作成です。"
        if source == "kokuji" and not source_state["active"]:
            return "告示検索は現在無効です。"
        if source == "kokuji":
            return "該当する告示が見つかりませんでした。検索語を変えて再度お試しください。"
        return "該当する条文が見つかりませんでした。検索語を変えて再度お試しください。"

    def _connect_search_db(self) -> Tuple[Optional[sqlite3.Connection], str]:
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

    def search_law_inputs(self, article_query: str, body_query: str):
        if article_query and body_query:
            return self.search_article_with_body_keyword(article_query, body_query)

        search_mode, active_query = self._select_search_query(article_query, body_query)
        if search_mode == "body" and self._is_probable_article_query(active_query):
            search_mode = "article"
        if search_mode == "article":
            return self.search_article(active_query)
        if search_mode == "body":
            return self.search_body(active_query)
        return [], ""

    def search_kokuji_notice(self, notice_number_query: str, body_query: str, source_state: Optional[dict[str, object]] = None):
        state = source_state or self._get_kokuji_source_state()
        if not state["enabled"]:
            return [], str(state["note"])
        try:
            payload = search_kokuji(Path(self.kokuji_db_path), query=body_query, notice_number=notice_number_query, limit=100)
        except (FileNotFoundError, KeyError, ValueError):
            return [], "告示DBを開けません"
        highlight_terms = payload.get("highlight_terms", [])
        notice_digits = "".join(re.findall(r"\d+", normalize_num(notice_number_query or "")))
        number_highlight_terms = [notice_digits] if notice_digits else []
        body_highlight_terms = list(dict.fromkeys([*highlight_terms, *number_highlight_terms]))
        rows = [
            {
                **row,
                "display_document_number_raw": row.get("display_document_number", ""),
                "document_number_raw": row.get("document_number", ""),
                "document_number_norm_raw": row.get("document_number_norm", ""),
                "display_document_number_html": self._highlight_text_multi(
                    self._format_notice_number_display(row.get("display_document_number", "")),
                    number_highlight_terms,
                ),
                "notice_name": self._highlight_text_multi(row.get("notice_name", ""), highlight_terms),
                "display_document_number": self._highlight_text_multi(row.get("display_document_number", ""), highlight_terms),
                "document_number": self._highlight_text_multi(row.get("document_number", ""), highlight_terms),
                "document_number_norm": self._highlight_text_multi(row.get("document_number_norm", ""), highlight_terms),
                "document_number_digits": self._highlight_text_multi(row.get("document_number_digits", ""), highlight_terms),
                "snippet": self._highlight_text_multi(row.get("snippet", ""), highlight_terms),
                "full_text_html": self._highlight_text_multi(row.get("full_text", ""), body_highlight_terms),
                "body_preview_html": self._build_collapsed_body_preview(
                    self._highlight_text_multi(row.get("full_text", ""), body_highlight_terms)
                )
                if (row.get("full_text") or "").strip()
                else self._highlight_text_multi(row.get("snippet", ""), body_highlight_terms),
            }
            for row in payload["results"]
        ]
        warning = " / ".join(payload.get("warnings", []))
        return rows, warning

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
            highlight_terms = self._article_highlight_terms(query)
            main_num, branch_num = parsed_article
            where_parts = ["a.article_no = ?" for _ in article_variants]
            params = list(article_variants)
            if main_num is not None and branch_num is None:
                branchable_variants = [variant for variant in article_variants if "条" in variant]
                where_parts.extend(["a.article_no LIKE ?" for _ in branchable_variants])
                params.extend([f"{variant}の%" for variant in branchable_variants])
            try:
                rows = conn.execute(sql.format(where_clause="\n               OR ".join(where_parts)), params).fetchall()
            except sqlite3.OperationalError:
                return [], "法令DBを検索できません"
            return self._format_result_rows(rows, highlight_terms=highlight_terms), ""

    def search_body(self, query: str):
        tokens = self._tokenize_search_terms(query)
        if not tokens:
            return [], ""

        conn, warning = self._connect_search_db()
        if conn is None:
            return [], warning

        like_where_parts = ["(a.body LIKE ? OR l.law_name LIKE ?)" for _ in tokens]
        like_params: list[str] = []
        for token in tokens:
            wildcard = f"%{token}%"
            like_params.extend([wildcard, wildcard])

        like_sql = f"""
            SELECT l.law_name, a.provision_kind, a.article_no, a.body
            FROM articles a
            JOIN laws l ON l.law_id = a.law_id
            WHERE a.provision_kind = 'main' AND {" AND ".join(like_where_parts)}
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
            try:
                like_rows = conn.execute(like_sql, like_params).fetchall()
            except sqlite3.OperationalError:
                return [], "法令DBを検索できません"
            if like_rows:
                return [
                    (
                        self._display_law_name(law_name, provision_kind),
                        article_no,
                        self._build_like_snippet_multi(body, tokens),
                        self._highlight_text_multi(body, tokens),
                    )
                    for law_name, provision_kind, article_no, body in like_rows
                ], ""

            if not fts5_enabled(conn):
                return [], ""

            try:
                fts_query = self._build_fts_and_query(tokens)
                return self._format_result_rows(conn.execute(fts_sql, (fts_query,)).fetchall(), body_index=3, full_body_index=4), ""
            except sqlite3.OperationalError:
                quoted = self._build_fts_phrase_query(query)
                try:
                    rows = conn.execute(fts_sql, (quoted,)).fetchall()
                except sqlite3.OperationalError:
                    return [], ""
                return self._format_result_rows(rows, body_index=3, full_body_index=4), "クエリをフレーズ検索に変換"

    @staticmethod
    def _safe_snippet(snippet_text: str) -> str:
        placeholder_open = "__MARK_OPEN__"
        placeholder_close = "__MARK_CLOSE__"
        placeholder_br = "__LINE_BREAK__"
        safe = (
            (snippet_text or "")
            .replace("<mark>", placeholder_open)
            .replace("</mark>", placeholder_close)
            .replace("<br>", placeholder_br)
        )
        safe = html.escape(safe)
        return (
            safe.replace(placeholder_open, "<mark>")
            .replace(placeholder_close, "</mark>")
            .replace(placeholder_br, "<br>")
        )

    @staticmethod
    def _plain_text_for_copy(text: str) -> str:
        return (text or "").replace("<mark>", "").replace("</mark>", "")

    @classmethod
    def _build_copy_text(cls, law_name: str, article_no: str, full_body: str) -> str:
        return "\n".join([law_name, article_no, cls._plain_text_for_copy(full_body)])

    @staticmethod
    def _unpack_result_row(row):
        if len(row) >= 5:
            law_name, article_no, body, full_body, display_article_html = row[:5]
            return law_name, article_no, body, full_body, display_article_html
        law_name, article_no, body, full_body = row[:4]
        return law_name, article_no, body, full_body, ""

    @classmethod
    def _build_bulk_copy_text(cls, rows, article_query: str = "", body_query: str = "") -> str:
        condition_lines = [
            "検索条件",
            f"条番号: {article_query or 'なし'}",
            f"本文キーワード: {body_query or 'なし'}",
        ]
        blocks = []
        for row in rows:
            law_name, article_no, _body, full_body, _display_article_html = cls._unpack_result_row(row)
            blocks.append(cls._build_copy_text(law_name, article_no, full_body))
        if not blocks:
            return "\n".join(condition_lines)
        return "\n".join(condition_lines) + "\n\n" + "\n\n".join(blocks)

    @staticmethod
    def _strip_markup(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "")

    @classmethod
    def _format_notice_number_display(cls, document_number: str) -> str:
        text = cls._strip_markup(document_number).strip()
        if not text:
            return ""
        return re.sub(r"(.+)(第[^第]+号)$", r"\1<br>\2", text, count=1)

    def _exports_dir(self) -> Path:
        return self.DEFAULT_EXPORTS_DIR

    def _export_path_for_source(self, source: str) -> Path:
        filename = "latest_kokuji_search.txt" if source == "kokuji" else "latest_law_search.txt"
        return self._exports_dir() / filename

    @staticmethod
    def _open_exports_folder(exports_dir: Path) -> None:
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", str(exports_dir)], check=False)
            elif os.name == "nt":
                os.startfile(str(exports_dir))
            else:
                subprocess.run(["xdg-open", str(exports_dir)], check=False)
        except Exception:
            return

    @staticmethod
    def _display_export_path(export_path: Path) -> str:
        try:
            return str(export_path.relative_to(REPO_ROOT))
        except ValueError:
            return str(export_path)

    def _save_results_txt(
        self,
        *,
        source: str,
        article_query: str,
        notice_number_query: str,
        body_query: str,
    ) -> Tuple[Optional[Path], int]:
        normalized_source = self._normalize_source(source)
        if normalized_source == "kokuji":
            rows = self._fetch_kokuji_download_rows(notice_number_query, body_query)
            export_path = self._export_path_for_source("kokuji")
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(
                self._build_kokuji_download_text(rows, notice_number_query=notice_number_query, body_query=body_query),
                encoding="utf-8",
            )
            return export_path, len(rows)

        rows = self._fetch_law_download_rows(article_query, body_query)
        export_path = self._export_path_for_source("law")
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            self._build_law_download_text(rows, article_query=article_query, body_query=body_query),
            encoding="utf-8",
        )
        return export_path, len(rows)

    def _fetch_law_download_rows(self, article_query: str, body_query: str) -> list[dict[str, str]]:
        if not Path(self.db_path).exists():
            return []
        rows, _warning = self.search_law_inputs(article_query, body_query)
        return [self._law_download_row_from_search_row(row) for row in rows[:DOWNLOAD_RESULTS_LIMIT]]

    def _fetch_kokuji_download_rows(self, notice_number_query: str, body_query: str) -> list[dict[str, str]]:
        state = self._get_kokuji_source_state()
        if not state["enabled"]:
            return []
        try:
            payload = search_kokuji(
                Path(self.kokuji_db_path),
                query=body_query,
                notice_number=notice_number_query,
                limit=DOWNLOAD_RESULTS_LIMIT,
            )
        except (FileNotFoundError, KeyError, ValueError, sqlite3.DatabaseError):
            return []
        return [dict(row) for row in payload.get("results", [])]

    @classmethod
    def _build_law_download_text(cls, rows: list[dict[str, str]], *, article_query: str, body_query: str) -> str:
        lines = [
            "法令検索結果",
            "",
            "検索条件",
            f"条番号: {article_query or 'なし'}",
            f"検索キーワード: {body_query or 'なし'}",
            f"件数: {len(rows)}",
            "",
        ]
        for index, row in enumerate(rows, start=1):
            law_title = str(row.get("law_title", "") or "")
            article_number = str(row.get("article_number", "") or "")
            article_title = str(row.get("article_title", "") or "")
            article_text = str(row.get("article_text", "") or "")
            lines.extend(
                [
                    "=" * 60,
                    f"【{index}】{law_title}",
                    f"条番号: {article_number}",
                    f"見出し: {article_title or 'なし'}",
                    "",
                    article_text,
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def _law_download_row_from_search_row(cls, row) -> dict[str, str]:
        law_name, article_no, _body, full_body, _display_article_html = cls._unpack_result_row(row)
        article_text = cls._plain_text_for_copy(full_body)
        return {
            "law_title": law_name,
            "article_number": cls._display_article_no(article_no),
            "article_title": cls._extract_leading_heading(article_text).strip("（）"),
            "article_text": article_text,
            "source": "laws.db",
        }

    @classmethod
    def _build_kokuji_download_text(cls, rows: list[dict[str, str]], *, notice_number_query: str, body_query: str) -> str:
        lines = [
            "告示検索結果",
            "",
            "検索条件",
            f"告示番号: {notice_number_query or 'なし'}",
            f"検索キーワード: {body_query or 'なし'}",
            f"件数: {len(rows)}",
            "",
        ]
        for index, row in enumerate(rows, start=1):
            document_number = str(
                row.get("display_document_number")
                or row.get("document_number_norm")
                or row.get("document_number")
                or (f"{row.get('document_number_digits', '')}号" if row.get("document_number_digits") else "")
                or ""
            )
            lines.extend(
                [
                    "=" * 60,
                    f"【{index}】{document_number or '番号不明'}",
                    f"告示名: {str(row.get('notice_name', '') or '')}",
                    f"organization: {str(row.get('organization', '') or '')}",
                    f"URL: {str(row.get('url', '') or '')}",
                    "",
                    str(row.get("full_text", "") or ""),
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

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

    @staticmethod
    def _tokenize_search_terms(query: str) -> List[str]:
        return [token for token in re.split(r"[\s\u3000]+", (query or "").strip()) if token]

    @classmethod
    def _build_fts_and_query(cls, terms: List[str]) -> str:
        return " AND ".join(cls._quote_fts_term(term) for term in terms)

    @staticmethod
    def _quote_fts_term(term: str) -> str:
        return '"' + term.replace('"', '""') + '"'

    @classmethod
    def _build_fts_phrase_query(cls, query: str) -> str:
        return cls._quote_fts_term((query or "").strip())

    @classmethod
    def _build_collapsed_body_preview(cls, body_text: str, max_lines: int = 5) -> str:
        lines = (body_text or "").splitlines()
        if len(lines) <= max_lines:
            return body_text or ""
        preview_lines = lines[:max_lines]
        preview_lines[-1] = preview_lines[-1].rstrip() + "…"
        return "\n".join(preview_lines)

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

    @classmethod
    def _build_like_snippet_multi(cls, body_text: str, terms: List[str], radius: int = 80) -> str:
        body_text = body_text or ""
        match_candidates = [(body_text.find(term), term) for term in terms if term and body_text.find(term) >= 0]
        if not match_candidates:
            snippet = body_text[: radius * 2]
            return cls._highlight_text_multi(cls._prepend_heading_to_snippet(body_text, snippet), terms)

        idx, matched_term = min(match_candidates, key=lambda item: item[0])
        start = max(0, idx - radius)
        end = min(len(body_text), idx + len(matched_term) + radius)
        snippet = body_text[start:end]
        if start > 0:
            snippet = f"… {snippet}"
        if end < len(body_text):
            snippet = f"{snippet} …"
        return cls._highlight_text_multi(cls._prepend_heading_to_snippet(body_text, snippet), terms)

    @staticmethod
    def _highlight_text(text: str, query: str) -> str:
        if not text or not query or query not in text:
            return text
        return text.replace(query, f"<mark>{query}</mark>")

    @staticmethod
    def _highlight_text_multi(text: str, terms: List[str]) -> str:
        if not text:
            return text
        normalized_terms = sorted({term for term in terms if term}, key=len, reverse=True)
        if not normalized_terms:
            return text
        pattern = "|".join(re.escape(term) for term in normalized_terms)
        return re.sub(pattern, lambda match: f"<mark>{match.group(0)}</mark>", text)

    @classmethod
    def _display_law_name(cls, law_name: str, provision_kind: str) -> str:
        return cls.LAW_DISPLAY_LABELS.get((law_name, provision_kind), law_name)

    def _render_meta_actions(
        self,
        rows=None,
        article_query: str = "",
        notice_number_query: str = "",
        body_query: str = "",
        source: str = "law",
    ) -> str:
        normalized_source = self._normalize_source(source)
        number_field = "notice_number" if normalized_source == "kokuji" else "article"
        number_value = notice_number_query if normalized_source == "kokuji" else article_query
        if not number_value and not body_query:
            return ""
        href = "/export_results?" + urlencode(
            {
                "source": normalized_source,
                number_field: number_value,
                "q": body_query,
            }
        )
        return f"<a class='text-download-button' href='{html.escape(href, quote=True)}'>TXT保存</a>"

    @classmethod
    def _format_result_rows(
        cls,
        rows,
        body_index: int = 3,
        full_body_index: Optional[int] = None,
        highlight_terms: Optional[List[str]] = None,
    ):
        return [
            cls._format_result_row(
                row,
                body_index=body_index,
                full_body_index=full_body_index,
                highlight_terms=highlight_terms,
            )
            for row in rows
        ]

    @classmethod
    def _filter_article_rows_by_body_keyword(cls, rows, body_query: str):
        filtered_rows = []
        terms = cls._tokenize_search_terms(body_query)
        for row in rows:
            law_name, article_no, _body, full_body, display_article_html = cls._unpack_result_row(row)
            plain_full_body = cls._plain_text_for_copy(full_body)
            if not terms or any(term not in plain_full_body for term in terms):
                continue
            highlighted_full_body = cls._highlight_text_multi(full_body, terms)
            preview_body = cls._build_collapsed_body_preview(highlighted_full_body)
            filtered_rows.append((law_name, article_no, preview_body, highlighted_full_body, display_article_html))
        return filtered_rows

    @classmethod
    def _format_result_row(
        cls,
        row,
        body_index: int = 3,
        full_body_index: Optional[int] = None,
        highlight_terms: Optional[List[str]] = None,
    ):
        law_name, provision_kind, article_no = row[:3]
        body = row[body_index]
        full_body = body if full_body_index is None else row[full_body_index]
        display_article_no = cls._display_article_no(article_no)
        display_article_html = display_article_no
        if highlight_terms:
            display_article_html = cls._highlight_text_multi(display_article_no, highlight_terms)
            full_body = cls._highlight_text_multi(full_body, highlight_terms)
        body = cls._build_collapsed_body_preview(full_body) if full_body_index is None else body
        return (cls._display_law_name(law_name, provision_kind), article_no, body, full_body, display_article_html)

    @staticmethod
    def _display_article_no(article_no: str) -> str:
        return article_no[1:] if article_no.startswith("第") else article_no

    @staticmethod
    def _article_query_variants(query: str) -> Tuple[List[str], Tuple[Optional[int], Optional[int]]]:
        variants: List[str] = []
        seen: Set[str] = set()

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

    @classmethod
    def _article_highlight_terms(cls, query: str) -> List[str]:
        _variants, parsed_article = cls._article_query_variants(query)
        main_num, branch_num = parsed_article
        if main_num is None:
            return []

        main_digits = str(main_num)
        main_kanji = int_to_kanji(main_num)
        terms: List[str] = [
            f"第{main_digits}条",
            f"{main_digits}条",
            f"第{main_kanji}条",
            f"{main_kanji}条",
        ]
        if branch_num is not None:
            branch_digits = str(branch_num)
            branch_kanji = int_to_kanji(branch_num)
            terms.extend(
                [
                    f"第{main_digits}条の{branch_digits}",
                    f"{main_digits}条の{branch_digits}",
                    f"第{main_digits}条の{branch_kanji}",
                    f"{main_digits}条の{branch_kanji}",
                    f"第{main_kanji}条の{branch_digits}",
                    f"{main_kanji}条の{branch_digits}",
                    f"第{main_kanji}条の{branch_kanji}",
                    f"{main_kanji}条の{branch_kanji}",
                ]
            )
        return list(dict.fromkeys(terms))

    @classmethod
    def _build_body_cell_html(
        cls,
        preview_text: str,
        full_text: str,
        *,
        copy_text: str = "",
        copy_button_hidden_when_collapsed: bool = True,
    ) -> str:
        safe_preview = cls._safe_snippet(preview_text)
        safe_full = cls._safe_snippet(full_text)
        is_expandable = safe_preview != safe_full
        copy_button_html = ""
        if copy_text:
            safe_copy_text = html.escape(copy_text, quote=True)
            copy_hidden_attr = " hidden" if is_expandable and copy_button_hidden_when_collapsed else ""
            copy_button_html = (
                "<span class='copy-feedback body-copy-feedback' hidden>コピー済み</span>"
                f"<button type='button' class='copy-button' title='コピー' data-copy-text='{safe_copy_text}'{copy_hidden_attr}></button>"
            )
        body_html = f"<div class='body-wrap'>{copy_button_html}<div class='body-preview'>{safe_preview}</div>"
        if is_expandable:
            body_html += f"<div class='body-full' hidden>{safe_full}</div>"
        body_html += "</div>"
        return body_html

    def render_table(self, rows):
        if not rows:
            return "<div class='empty'>該当する条文が見つかりませんでした。検索語を変えて再度お試しください。</div>"
        lines = ["<table>", "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>", "<tbody>"]
        for row in rows:
            law_name, article_no, body, full_body, display_article_html = self._unpack_result_row(row)
            is_expandable = self._safe_snippet(body) != self._safe_snippet(full_body)
            body_class = "body is-expandable" if is_expandable else "body"
            body_html = self._build_body_cell_html(
                body,
                full_body,
                copy_text=self._build_copy_text(law_name, article_no, full_body),
            )
            article_html = display_article_html or html.escape(self._display_article_no(article_no))
            lines.append(
                "<tr>"
                f"<td class='law'>{html.escape(law_name)}</td>"
                f"<td class='article'>{article_html}</td>"
                f"<td class='{body_class}'>{body_html}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    def render_results(self, rows, source: str = "law", empty_message: str = "") -> str:
        if source == "kokuji":
            return self.render_kokuji_table(rows, empty_message=empty_message)
        if not rows and empty_message:
            return f"<div class='empty'>{html.escape(empty_message)}</div>"
        return self.render_table(rows)

    def render_kokuji_table(self, rows, empty_message: str = ""):
        if not rows:
            message = empty_message or "該当する告示が見つかりませんでした。検索語を変えて再度お試しください。"
            return f"<div class='empty'>{html.escape(message)}</div>"

        lines = [
            "<table>",
            "<thead><tr><th>告示番号</th><th>告示名</th><th>本文</th><th>リンク</th></tr></thead>",
            "<tbody>",
        ]
        for row in rows:
            url = (row.get("url") or "").strip()
            link_label = row.get("link_label") or detect_link_label(url, row.get("content_type", ""))
            link_html = (
                f"<a class='kokuji-link-button' href='{html.escape(url, quote=True)}' target='_blank' rel='noreferrer'>{html.escape(link_label)}</a>"
                if url
                else ""
            )
            safe_notice_name = self._safe_snippet(row.get("notice_name", ""))
            safe_document_number = self._safe_snippet(
                row.get("display_document_number_html")
                or self._format_notice_number_display(
                    row.get("display_document_number_raw")
                    or row.get("document_number_norm_raw")
                    or row.get("document_number_raw")
                    or row.get("display_document_number")
                    or ""
                )
            )
            full_text = row.get("full_text_html") or row.get("full_text") or ""
            preview_text = row.get("body_preview_html") or row.get("snippet", "")
            body_html = self._build_body_cell_html(preview_text, full_text or preview_text)
            is_expandable = self._safe_snippet(preview_text) != self._safe_snippet(full_text or preview_text)
            body_class = "body kokuji-snippet is-expandable" if is_expandable else "body kokuji-snippet"
            organization = (row.get("organization") or "").strip()
            organization_html = f"<div class='kokuji-meta'>{html.escape(organization)}</div>" if organization else ""
            document_year = self._extract_document_year(row.get("document_date", ""))
            year_html = f"<div class='kokuji-meta kokuji-year'>{html.escape(document_year)}年</div>" if document_year else ""
            row_id = str(row.get("row_id") or "").strip()
            has_full_text = bool((row.get("full_text") or "").strip())
            copy_button_html = ""
            if row_id and has_full_text:
                copy_button_html = (
                    f"<button type='button' class='copy-button kokuji-copy-button' title='全文コピー' aria-label='全文コピー' data-notice-id='{html.escape(row_id, quote=True)}' data-kokuji-id='{html.escape(row_id, quote=True)}'></button>"
                    "<span class='copy-feedback kokuji-copy-feedback' hidden>コピー済み</span>"
                )
            link_stack = f"<div class='kokuji-link-stack'>{link_html}{copy_button_html}</div>" if (link_html or copy_button_html) else ""
            lines.append(
                "<tr>"
                f"<td class='article kokuji-number'>{safe_document_number}</td>"
                f"<td class='kokuji-name'>{safe_notice_name}{organization_html}{year_html}</td>"
                f"<td class='{body_class}'>{body_html}</td>"
                f"<td class='kokuji-link-cell'>{link_stack}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    @staticmethod
    def _extract_document_year(document_date: str) -> str:
        match = re.match(r"\s*(\d{4})(?:-\d{2}-\d{2})?\s*$", str(document_date or ""))
        if not match:
            return ""
        return match.group(1)

    def _render_shutdown_action(self) -> str:
        if not self._is_local_shutdown_available():
            return ""
        return (
            "<form method='post' action='/shutdown' onsubmit=\"return window.confirm('ローカルサーバーを終了しますか？');\">"
            "<button type='submit' class='nav-link shutdown-link'>終了</button>"
            "</form>"
        )

    def _is_local_shutdown_available(self) -> bool:
        server = getattr(self, "server", None)
        if server is None:
            return False
        try:
            host = str(server.server_address[0])
        except Exception:
            return False
        return host in {"127.0.0.1", "localhost", "::1"}

    def _handle_shutdown_request(self) -> None:
        if not self._is_local_shutdown_available():
            self._send_json({"error": "shutdown unavailable"}, status=HTTPStatus.FORBIDDEN)
            return
        self._send_html(
            b"<!doctype html><html lang='ja'><meta charset='utf-8'><title>Shutting down</title><body>Archi_law_search server is shutting down.</body></html>"
        )
        server = getattr(self, "server", None)
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    def render_settings_table(self, installed_ids: Set[str], return_to: str = "") -> str:
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
            actions = self._render_settings_actions(law.law_id, is_installed, return_to=return_to)
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
    def _render_settings_actions(law_id: str, is_installed: bool, return_to: str = "") -> str:
        def render_form(action: str, label: str, button_class: str = "") -> str:
            class_attr = f" class='{button_class}'" if button_class else ""
            return_to_input = (
                f"<input type='hidden' name='return_to' value='{html.escape(return_to, quote=True)}' />"
                if return_to
                else ""
            )
            return (
                "<form method='post' action='/settings/action'>"
                f"<input type='hidden' name='law_id' value='{html.escape(law_id)}' />"
                f"<input type='hidden' name='action' value='{action}' />"
                f"{return_to_input}"
                f"<button type='submit'{class_attr}>{label}</button>"
                "</form>"
            )

        forms = [render_form("add", "追加")] if not is_installed else [
            render_form("refresh", "更新", "button-secondary"),
            render_form("delete", "削除", "button-danger"),
        ]
        return f"<div class='actions'>{''.join(forms)}</div>"

    @staticmethod
    def _build_settings_href(query_string: str) -> str:
        if not query_string:
            return "/settings"
        return "/settings?" + urlencode({"return_to": query_string})

    @staticmethod
    def _build_search_return_href(return_to: str) -> str:
        return f"/?{return_to}" if return_to else "/"


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

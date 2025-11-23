"""
保存済み sample_*.html 内の <script src="..."> を解析し、JS に埋め込まれた
ネットワークアクセス先 URL を列挙する調査用スクリプト。

制約:
- e-Gov へのアクセスは JS ファイル取得 1 回のみ（他にはアクセスしない）。
- 本文やリンクデータは取得しない。URL 文字列の抽出のみを行う。

使い方:
  python -m tests.js_source_inspect   # data/raw の最新 sample_*.html を対象
"""
from __future__ import annotations

import pathlib
import re
import sys
from typing import List, Optional, Set

import requests
from bs4 import BeautifulSoup

RAW_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
BASE_DOMAIN = "https://laws.e-gov.go.jp"

# URL 抽出用の正規表現
RE_FETCH_DOUBLE = re.compile(r'fetch\("([^"]+)"\)')
RE_FETCH_SINGLE = re.compile(r"fetch\('([^']+)'\)")
RE_XHR = re.compile(r'XMLHttpRequest\("([^"]+)"\)')
RE_AXIOS = re.compile(r'axios\.get\("([^"]+)"\)')
RE_URL_LIKE = re.compile(r"https?://[^\\s\"']+|/law/[\\w\\d_/.-]+|/api/[\\w\\d_/.-]+")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def latest_sample_html() -> Optional[pathlib.Path]:
    candidates = sorted(RAW_DIR.glob("sample_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def to_abs_url(src: str) -> str:
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("/"):
        return BASE_DOMAIN + src
    # 相対パスは念のためドメインを付与
    return f"{BASE_DOMAIN}/{src.lstrip('./')}"


def extract_js_urls(js_text: str) -> Set[str]:
    urls: Set[str] = set()
    for regex in (RE_FETCH_DOUBLE, RE_FETCH_SINGLE, RE_XHR, RE_AXIOS, RE_URL_LIKE):
        for m in regex.finditer(js_text):
            urls.add(m.group(1) if m.groups() else m.group(0))
    return urls


def main() -> None:
    html_path = latest_sample_html()
    if not html_path:
        warn("data/raw/ に sample_*.html が見つかりません。")
        return

    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    scripts = [tag.get("src") for tag in soup.find_all("script", src=True)]
    if not scripts:
        warn("script src が見つかりませんでした。")
        return

    # 先頭のスクリプトだけ取得する（アクセスは 1 回だけ）
    src = scripts[0]
    js_url = to_abs_url(src)

    try:
        resp = requests.get(js_url, timeout=20)
        resp.raise_for_status()
        js_text = resp.text
    except Exception as e:
        warn(f"JS 取得に失敗しました: {js_url} ({e})")
        return

    urls = extract_js_urls(js_text)
    print("[JSアクセス候補URL]")
    if not urls:
        print("- 取得できませんでした")
    else:
        for u in sorted(urls):
            print(f"- {u}")


if __name__ == "__main__":
    main()

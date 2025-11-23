"""
e-Gov HTML 版の条文ページに含まれる青字リンクを解析し、リンク先と
その位置（条・項・号）を推定して一覧表示するスクリプト。

役割:
  (A) HTML を一度だけ取得して data/raw/ に保存する（同じ law_id があれば再取得しない）
  (B) 保存済み HTML を解析してリンク情報を出力する

使い方:
  python -m tests.html_link_inspect                     # デフォルト2件を解析
  python -m tests.html_link_inspect <URL1> <URL2> ...   # 任意の URL を指定
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

RAW_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
DEFAULT_URLS = [
    "https://laws.e-gov.go.jp/law/325AC0000000201/",
    "https://laws.e-gov.go.jp/law/325CO0000000338/",
]

ARTICLE_RE = re.compile(r"第[0-9０-９一二三四五六七八九十百千]+条")
PARA_RE = re.compile(r"第[0-9０-９一二三四五六七八九十百千]+項")
ITEM_RE = re.compile(r"第[0-9０-９一二三四五六七八九十百千]+号")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def extract_law_id(url: str) -> str:
    u = url.rstrip("/").split("/")
    return u[-1] if u else "unknown"


def find_cached_html(law_id: str) -> Optional[pathlib.Path]:
    pattern = f"sample_{law_id}_*.html"
    candidates = sorted(RAW_DIR.glob(pattern))
    return candidates[-1] if candidates else None


def fetch_and_save(url: str, law_id: str) -> pathlib.Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    path = RAW_DIR / f"sample_{law_id}_{today}.html"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    path.write_text(resp.text, encoding=resp.encoding or "utf-8")
    return path


def load_html(url: str) -> Tuple[str, str]:
    """戻り値: (law_id, html文字列)。キャッシュ優先で取得。"""
    law_id = extract_law_id(url)
    cached = find_cached_html(law_id)
    if cached and cached.is_file():
        html = cached.read_text(encoding="utf-8")
        return law_id, html
    path = fetch_and_save(url, law_id)
    html = path.read_text(encoding="utf-8")
    return law_id, html


def find_marker(element, regex: re.Pattern) -> Optional[str]:
    """祖先テキストを遡って最初にヒットしたマーカーを返す。"""
    for parent in element.parents:
        if not hasattr(parent, "get_text"):
            continue
        txt = parent.get_text(separator=" ", strip=True)
        m = regex.search(txt)
        if m:
            return m.group()
    return None


def detect_position(anchor) -> str:
    """条・項・号のマーカーを推定。全て不明なら「位置不明」."""
    art = find_marker(anchor, ARTICLE_RE)
    para = find_marker(anchor, PARA_RE)
    item = find_marker(anchor, ITEM_RE)
    parts: List[str] = []
    if art:
        parts.append(art)
    if para:
        parts.append(para)
    if item:
        parts.append(item)
    return " ".join(parts) if parts else "位置不明"


def extract_links(html: str) -> List[Tuple[str, str, str]]:
    """(位置, 表示テキスト, href) のタプルを返す。"""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if not text or not href:
            continue
        pos = detect_position(a)
        links.append((pos, text, href))
    return links


def main(args: List[str]) -> None:
    urls = args or DEFAULT_URLS
    for url in urls:
        try:
            law_id, html = load_html(url)
        except Exception as e:
            warn(f"{url}: HTML取得に失敗しました: {e}")
            continue

        try:
            links = extract_links(html)
        except Exception as e:
            warn(f"{url}: 解析に失敗しました: {e}")
            continue

        print(f"=== {law_id} ===")
        if not links:
            print("リンクが見つかりませんでした。")
            continue

        for pos, text, href in links:
            print(f"[{pos}]")
            print(f"- 表示テキスト: {text}")
            print(f"- リンクURL: {href}")
            print()


if __name__ == "__main__":
    main(sys.argv[1:])

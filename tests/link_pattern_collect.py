"""
html_link_inspect が抽出するリンク表示テキストを収集し、パターン分類するスクリプト。

使い方:
  python -m tests.link_pattern_collect            # デフォルトURL（法・令）を対象
  python -m tests.link_pattern_collect <URL...>   # 任意のURLを指定

分類カテゴリ:
  - 条パターン（第○条 / 第○条の○ / 第○条第○項 など）
  - 項パターン（第○項 / 第○項の○号 など）
  - 号パターン（第○号）
  - 法令名パターン（法第○条 / 令第○条 / ○○法第○条 など）
  - その他（上記に当てはまらないもの）
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Set

# 同一フォルダの html_link_inspect を import できるようにパスを通す
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "tests"))

import html_link_inspect as inspector  # type: ignore


RE_ARTICLE = re.compile(
    r"^第[0-9０-９一二三四五六七八九十百千]+条"
    r"(?:の[0-9０-９一二三四五六七八九十百千]+)?"
    r"(?:第[0-9０-９一二三四五六七八九十百千]+項)?$"
)
RE_PARA = re.compile(
    r"^第[0-9０-９一二三四五六七八九十百千]+項"
    r"(?:の[0-9０-９一二三四五六七八九十百千]+号)?$"
)
RE_ITEM = re.compile(r"^第[0-9０-９一二三四五六七八九十百千]+号$")
RE_LAWNAME = re.compile(
    r"^(?:法|令|[\w一-龯]+法)第[0-9０-９一二三四五六七八九十百千]+条"
    r"(?:の[0-9０-９一二三四五六七八九十百千]+)?"
    r"(?:第[0-9０-９一二三四五六七八九十百千]+項)?$"
)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def collect_texts(urls: Iterable[str]) -> Set[str]:
    texts: Set[str] = set()
    for url in urls:
        try:
            _, html = inspector.load_html(url)
        except Exception as e:
            warn(f"{url}: HTML取得に失敗しました: {e}")
            continue
        try:
            links = inspector.extract_links(html)
        except Exception as e:
            warn(f"{url}: リンク抽出に失敗しました: {e}")
            continue
        for _, text, _ in links:
            if text:
                text = text.strip()
                if text:
                    texts.add(text)
    return texts


def classify(text: str) -> str:
    if RE_LAWNAME.fullmatch(text):
        return "法令名パターン"
    if RE_ARTICLE.fullmatch(text):
        return "条パターン"
    if RE_PARA.fullmatch(text):
        return "項パターン"
    if RE_ITEM.fullmatch(text):
        return "号パターン"
    return "その他"


def main(args: List[str]) -> None:
    urls = args or inspector.DEFAULT_URLS
    texts = collect_texts(urls)
    categories: Dict[str, Set[str]] = defaultdict(set)
    for t in texts:
        cat = classify(t)
        categories[cat].add(t)

    order = ["条パターン", "項パターン", "号パターン", "法令名パターン", "その他"]
    for cat in order:
        print(f"[{cat}]")
        items = sorted(categories.get(cat, []))
        if not items:
            print("- 該当なし")
        else:
            for it in items:
                print(f"- {it}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])

"""
app.py が e-Gov API の条文構造（見出し・条タイトル・項番号・号番号・号本文）を
取りこぼしていないかを検査するスクリプト。
デフォルトは全条をフルスキャンし、欠損種別のみを条ごとに表示する。

使い方:
    python -m tests.check_missing_content           # 全条スキャン
    python -m tests.check_missing_content 111 120   # 条番号を指定して限定スキャン
"""
from __future__ import annotations

import pathlib
import sys
from typing import Dict, Iterable, List, Set

# src を import パスに追加
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from app import (  # type: ignore
    LAW_MAIN_ID,
    LAW_ORDER_ID,
    clean_text_display,
    fetch_law_xml,
    get_text,
    normalize_num,
)


MISSING_LABELS: Dict[str, str] = {
    "caption": "見出し欠損（ArticleCaption）",
    "title": "条タイトル欠損（ArticleTitle）",
    "paragraph_num": "項番号欠損（ParagraphNum）",
    "item_title": "号番号欠損（ItemTitle）",
    "item_sentence": "号本文欠損（ItemSentence）",
    "not_found": "条が見つかりませんでした",
}
MISSING_ORDER = [
    "caption",
    "title",
    "paragraph_num",
    "item_title",
    "item_sentence",
    "not_found",
]


def normalize_for_compare(s: str) -> str:
    """app.py と同等の圧縮（空白除去）で比較用に整形。"""
    return clean_text_display(s).replace(" ", "")


def extract_app_text(article) -> str:
    """現在の app.py と同等のフラットテキストを生成。"""
    title = article.findtext(".//{*}ArticleTitle") or ""
    caption = article.findtext(".//{*}ArticleCaption") or ""
    text = " ".join(get_text(s) for s in article.findall(".//{*}Sentence"))
    return clean_text_display(title + caption + text)


def article_matches(article, target_norm: str) -> bool:
    """条タイトルの先頭が指定条に一致するか。"""
    title = article.findtext(".//{*}ArticleTitle") or ""
    return normalize_num(title).startswith(target_norm)


def normalize_target(num: str) -> str:
    n = normalize_num(num)
    if not n.startswith("第"):
        n = f"第{n}"
    if not n.endswith("条"):
        n = f"{n}条"
    return n


def iter_articles(root):
    return root.findall(".//{*}MainProvision//{*}Article")


def detect_missing(article) -> Set[str]:
    """構造要素の有無で欠損種別を判定（本文は表示しない）。"""
    missing: Set[str] = set()
    app_norm = normalize_for_compare(extract_app_text(article))

    caption = article.findtext(".//{*}ArticleCaption") or ""
    if caption.strip() and normalize_for_compare(caption) not in app_norm:
        missing.add("caption")

    title = article.findtext(".//{*}ArticleTitle") or ""
    if title.strip() and normalize_for_compare(title) not in app_norm:
        missing.add("title")

    for para in article.findall("./{*}Paragraph"):
        pnum = (para.findtext("./{*}ParagraphNum") or "").strip()
        if pnum and normalize_for_compare(pnum) not in app_norm:
            missing.add("paragraph_num")

        for item in para.findall("./{*}Item"):
            item_title = (item.findtext("./{*}ItemTitle") or "").strip()
            if item_title and normalize_for_compare(item_title) not in app_norm:
                missing.add("item_title")

            i_sentences = [
                clean_text_display(get_text(s))
                for s in item.findall("./{*}ItemSentence//{*}Sentence")
            ]
            item_text = " ".join(filter(None, i_sentences)).strip()
            if item_text and normalize_for_compare(item_text) not in app_norm:
                missing.add("item_sentence")

    return missing


def describe_article(article) -> str:
    title = article.findtext(".//{*}ArticleTitle") or ""
    return clean_text_display(title) or "(無題)"


def scan_law(root, label: str, target_nums: List[str]):
    targets_norm = [normalize_target(n) for n in target_nums] if target_nums else []
    articles = list(iter_articles(root))
    results = []

    for art in articles:
        if targets_norm and not any(article_matches(art, t) for t in targets_norm):
            continue
        missing = detect_missing(art)
        if missing:
            results.append((describe_article(art), missing))

    if targets_norm:
        for t in targets_norm:
            if not any(article_matches(art, t) for art in articles):
                results.append((t, {"not_found"}))
    return results


def main(args: List[str]):
    target_nums = args  # 空なら全条スキャン
    roots = [
        (fetch_law_xml(LAW_MAIN_ID), "法"),
        (fetch_law_xml(LAW_ORDER_ID), "令"),
    ]

    for root, label in roots:
        print(f"=== {label} スキャン開始 ===")
        results = scan_law(root, label, target_nums)
        if not results:
            print("欠損は見つかりませんでした。")
        else:
            for desc, missing in results:
                print(f"[{desc}]")
                for key in MISSING_ORDER:
                    if key in missing:
                        print(f"- {MISSING_LABELS.get(key, key)}")
                print()
        print(f"=== {label} スキャン終了 ===\n")


if __name__ == "__main__":
    main(sys.argv[1:])

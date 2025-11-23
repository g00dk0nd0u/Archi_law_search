"""
pytest で「条→項→号」構造を検証するテスト。
app.py には触れず、extract_structure の戻り値構造を確認する。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Dict, List, TypedDict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from app import LAW_ORDER_ID, fetch_law_xml, get_text, normalize_num  # type: ignore


class SubItem(TypedDict):
    item_number: str
    text: str


class Item(TypedDict, total=False):
    item_number: str
    text: str
    subitems: List[SubItem]


class ArticleStruct(TypedDict):
    item_number: str  # 条タイトル
    items: List[Item]  # 項のリスト


def extract_structure(root, target_article_num: str) -> ArticleStruct:
    """
    target_article_num: 数値文字列など（例: "111" or "第百十一条" でも可）。
    戻り値: { "item_number": <条タイトル>, "items": [ {item_number: 項番号, subitems: [...]}, ... ] }
    """
    target = target_article_num
    if not target.startswith("第"):
        target = f"第{target}"
    if not target.endswith("条"):
        target = f"{target}条"
    target_norm = normalize_num(target)

    article_title = ""
    items: List[Item] = []

    for art in root.findall(".//{*}MainProvision//{*}Article"):
        art_title = art.findtext(".//{*}ArticleTitle") or ""
        art_title_norm = normalize_num(art_title)
        if not art_title_norm.startswith(target_norm):
            continue
        article_title = art_title

        for para in art.findall("./{*}Paragraph"):
            pnum = para.findtext("./{*}ParagraphNum") or ""
            p_entry: Item = {
                "item_number": f"{pnum}項" if pnum else "(項番号なし)",
            }

            # Items under this paragraph
            subitems: List[SubItem] = []
            for item in para.findall("./{*}Item"):
                inum = (
                    item.findtext("./{*}ItemTitle")
                    or item.findtext("./{*}ItemNum")
                    or ""
                )
                i_sentences = [
                    get_text(s)
                    for s in item.findall("./{*}ItemSentence//{*}Sentence")
                ]
                subitems.append(
                    SubItem(item_number=inum or "(号番号なし)", text=" ".join(i_sentences).strip())
                )

            # ParagraphSentence -> Sentence (when no subitems)
            if not subitems:
                p_sentences = [
                    get_text(s)
                    for s in para.findall("./{*}ParagraphSentence//{*}Sentence")
                ]
                p_entry["text"] = " ".join(p_sentences).strip()
            else:
                p_entry["subitems"] = subitems

            items.append(p_entry)

    return ArticleStruct(item_number=article_title, items=items)


def test_extract_structure_contains_items_and_subitems():
    root = fetch_law_xml(LAW_ORDER_ID)
    struct = extract_structure(root, "111")

    assert isinstance(struct, dict), "戻り値は dict であるべき"
    assert "item_number" in struct, "最上位に item_number が必要"
    assert "items" in struct, "最上位に items が必要"
    assert struct["items"], "items は空でないこと"

    first_item = struct["items"][0]
    assert isinstance(first_item, dict), "items 内の要素は dict であるべき"
    if "subitems" in first_item:
        assert first_item["subitems"], "subitems がある場合、空であってはならない"

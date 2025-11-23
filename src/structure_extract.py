import json
import xml.etree.ElementTree as ET

try:
    from .text_utils import get_text
except ImportError:  # script fallback
    from text_utils import get_text

INDENT = "\u3000\u3000"  # 全角スペース2つで項目の余白を保持


def _extract_sentences(container: ET.Element | None):
    """ItemSentence 繧・ParagraphSentence 縺九ｉ Sentence/Column 繧帝・蛻励〒霑斐☆縲・"""
    if container is None:
        return {"sentences": [], "columns": []}
    sentences = [get_text(s) for s in container.findall(".//{*}Sentence")]
    columns = [get_text(c) for c in container.findall(".//{*}Column")]
    return {"sentences": sentences, "columns": columns}


def _extract_items(elem: ET.Element, level: int):
    """
    Item / Subitem1 / Subitem2 / Subitem3 繧貞・蟶ｰ逧・↓謚ｽ蜃ｺ縲・
    level=1 -> Item 縺ｮ驟堺ｸ九↓ subitems1
    """
    tag_map = {
        1: ("Item", "Subitem1", "subitems1"),
        2: ("Subitem1", "Subitem2", "subitems2"),
        3: ("Subitem2", "Subitem3", "subitems3"),
        4: ("Subitem3", None, None),
    }
    tag, child_tag, child_key = tag_map[level]
    results = []
    for it in elem.findall(f"./{{*}}{tag}"):
        num = it.findtext(f"./{{*}}{tag}Num") or it.findtext(f"./{{*}}{tag}Title")
        entry = {
            "number": num or None,
            "sentences": _extract_sentences(it.find(f"./{{*}}{tag}Sentence")),
        }
        if child_tag:
            entry[child_key] = _extract_items(it, level + 1)
        else:
            entry["subitems"] = []  # 譛荳句ｱ､縺ｧ繧ゅく繝ｼ繧剃ｿ晄戟・育ｩｺ驟榊・・・'
        results.append(entry)
    return results


def extract_structure(article: ET.Element):
    """
    Article 縺九ｉ Article/Paragraph/Item/Subitem1-3 繧貞・襍ｰ譟ｻ縺励・
    JSON 莠呈鋤縺ｮ霎樊嶌讒矩縺ｧ霑斐☆縲・
    """
    article_num = article.findtext(".//{*}ArticleTitle") or None
    paragraphs = []
    for para in article.findall("./{*}Paragraph"):
        pnum = para.findtext("./{*}ParagraphNum") or None
        p_sentence = _extract_sentences(para.find("./{*}ParagraphSentence"))
        items = _extract_items(para, level=1)
        paragraphs.append(
            {
                "paragraph_number": pnum,
                "paragraph_sentence": p_sentence,
                "items": items,
            }
        )

    return {
        "article_number": article_num,
        "paragraphs": paragraphs,
    }


def render_structure(title: str, struct: dict) -> str:
    """讒矩繧・JSON 譁・ｭ怜・縺ｨ縺励※霑斐☆縲る撼陦ｨ遉ｺ譚｡莉ｶ縺ｫ隧ｲ蠖薙☆繧玖ｦ∫ｴ縺ｯ逵√￥縲・"""

    def prune(obj):
        # 遨ｺ驟榊・繝ｻ遨ｺdict繝ｻNone 縺ｯ陦ｨ遉ｺ縺励↑縺・
        if obj is None:
            return None
        if isinstance(obj, list):
            pruned_list = [prune(x) for x in obj]
            pruned_list = [x for x in pruned_list if x not in (None, {}, [])]
            return pruned_list if pruned_list else None
        if isinstance(obj, dict):
            pruned_dict = {}
            for k, v in obj.items():
                if v is None:
                    continue
                pruned_val = prune(v)
                if pruned_val in (None, {}, []):
                    continue
                pruned_dict[k] = pruned_val
            return pruned_dict if pruned_dict else None
        return obj

    # article_number 縺・title 縺ｨ荳閾ｴ縺吶ｋ蝣ｴ蜷医・陦ｨ遉ｺ縺励↑縺・
    pruned_struct = dict(struct)
    if pruned_struct.get("article_number") == title:
        pruned_struct.pop("article_number", None)

    payload = {"title": title}
    pruned_structure = prune(pruned_struct)
    if pruned_structure:
        payload["structure"] = pruned_structure
    # JSON譁・ｭ怜・陦ｨ遉ｺ縺ｯ荳崎ｦ√↓縺ｪ縺｣縺溘′莠呈鋤縺ｮ縺溘ａ谿九☆
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_article_plain(title: str, struct: dict) -> str:
    """
    XML逕ｱ譚･縺ｮ髫主ｱ､讒矩繧偵・繝ｬ繝ｼ繝ｳ繝・く繧ｹ繝医↓謨ｴ蠖｢縺励※霑斐☆縲・
    謾ｹ陦後・縺ｿ縺ｧ蛹ｺ蛻・ｊ縲∫ｩｺ陦後・菴懊ｉ縺ｪ縺・・
    """
    lines = []

    def append_numbered(lines_list, line):
        if lines_list and lines_list[-1] != "":
            lines_list.append("")
        lines_list.append(line)

    # 1) 繧ｿ繧､繝医Ν陦・
    lines.append(title)
    lines.append("")

    paragraphs = struct.get("paragraphs") or []
    for para in paragraphs:
        # Paragraph譛ｬ菴・
        pnum = para.get("paragraph_number")
        p_sentences = (para.get("paragraph_sentence") or {}).get("sentences") or []
        p_body = " ".join(s for s in p_sentences if s)
        if p_body:
            prefix = f"{pnum}{INDENT}" if pnum else ""
            line = f"{prefix}{p_body}"
            if pnum:
                append_numbered(lines, line)
            else:
                lines.append(line)

        # Items
        items = para.get("items") or []
        for item in items:
            num = item.get("number")
            body_list = (item.get("sentences") or {}).get("sentences") or []
            body = " ".join(s for s in body_list if s)
            if body and num:
                append_numbered(lines, f"{num}{INDENT}{body}")
            elif body:
                lines.append(body)

            # subitems1
            subitems1 = item.get("subitems1") or []
            for sub in subitems1:
                snum = sub.get("number")
                s_body_list = (sub.get("sentences") or {}).get("sentences") or []
                s_body = " ".join(s for s in s_body_list if s)
                if not s_body:
                    continue
                if snum:
                    append_numbered(lines, f"  {snum}{INDENT}{s_body}")
                else:
                    lines.append(f"  {s_body}")

    return "\n".join(lines)


def prune_empty(obj):
    """Recursively remove empty values: None, '', [], {}."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj if obj != "" else None
    if isinstance(obj, list):
        pruned_list = [prune_empty(x) for x in obj]
        pruned_list = [x for x in pruned_list if x not in (None, {}, [])]
        return pruned_list if pruned_list else None
    if isinstance(obj, dict):
        pruned_dict = {}
        for k, v in obj.items():
            pruned_val = prune_empty(v)
            if pruned_val in (None, {}, []):
                continue
            pruned_dict[k] = pruned_val
        return pruned_dict if pruned_dict else None
    return obj

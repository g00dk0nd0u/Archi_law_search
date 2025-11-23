# -*- coding: utf-8 -*-
# 建築基準法／施行令の検索ビューア（構造保持版）
import re
import json
import copy
import uuid
import traceback
from datetime import date
import xml.etree.ElementTree as ET

import pyperclip
import requests
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, ListItem, ListView, Static

LAW_MAIN_ID = "325AC0000000201"   # 建築基準法
LAW_ORDER_ID = "325CO0000000338"  # 建築基準法施行令
BASE_URL = "https://laws.e-gov.go.jp/api/2/law_data/"


# ==== XML取得 ====
def fetch_law_xml(law_id: str, as_of_date=None):
    params = {"response_format": "xml"}
    if as_of_date:
        params["asof"] = as_of_date
    r = requests.get(BASE_URL + law_id, params=params, timeout=15)
    r.raise_for_status()
    return ET.fromstring(r.text)


def safe_fetch(law_id: str, as_of_date=None):
    """fetch_law_xml をラップして例外を吸収。失敗時は空のルートを返す。"""
    try:
        return fetch_law_xml(law_id, as_of_date)
    except Exception as e:
        print(f"[WARN] fetch_law_xml failed for {law_id}: {e}")
        traceback.print_exc()
        return ET.Element("Root")


# ==== ユーティリティ ====
def get_text(elem):
    parts = []
    if elem.text:
        parts.append(elem.text)
    for e in elem:
        parts.append(get_text(e))
        if e.tail:
            parts.append(e.tail)
    return "".join(parts)


def clean_text_display(t: str) -> str:
    return t.replace("\n", "").replace("　", "").strip()


# 数字正規化
KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
KANJI_SEQ_RE = re.compile(r"[〇零一二三四五六七八九十百千]+")


def _kanji_seq_to_int(seq: str) -> int:
    total, digit = 0, None
    for ch in seq:
        if ch in KANJI_DIGITS:
            d = KANJI_DIGITS[ch]
            digit = d if digit is None else digit * 10 + d
        elif ch in KANJI_UNITS:
            u = KANJI_UNITS[ch]
            total += (digit or 1) * u
            digit = None
    if digit is not None:
        total += digit
    return total


def normalize_num(t: str) -> str:
    if not t:
        return ""
    fw_map = {
        ord("〇"): "0",
        ord("０"): "0",
        ord("１"): "1",
        ord("２"): "2",
        ord("３"): "3",
        ord("４"): "4",
        ord("５"): "5",
        ord("６"): "6",
        ord("７"): "7",
        ord("８"): "8",
        ord("９"): "9",
    }
    t = t.translate(fw_map)
    t = KANJI_SEQ_RE.sub(lambda m: str(_kanji_seq_to_int(m.group())), t)
    t = re.sub(r"\s+", "", t)
    if "条" in t and "第" not in t:
        idx = t.find("条")
        if any(ch.isdigit() for ch in t[:idx]):
            t = "第" + t
    return t


DASH_TRANSLATE = str.maketrans(
    {
        "－": "-",
        "ー": "-",
        "―": "-",
        "‐": "-",
        "‑": "-",
        "–": "-",
        "—": "-",
        "〜": "-",
        "～": "-",
    }
)


def normalize_separators(t: str) -> str:
    """Normalize separator-like characters (various dashes) to a plain hyphen."""
    if not t:
        return ""
    return t.translate(DASH_TRANSLATE)


def extract_query_numbers(query: str) -> list[str]:
    """Extract base article numbers from the query, tolerant of prefixes/suffixes."""
    q = normalize_separators(normalize_num(query))
    q = re.sub(r"[法第条]", "", q)
    q = q.replace("の", "-")
    numbers: list[str] = []
    for piece in re.split(r"[^0-9-]+", q):
        if not piece:
            continue
        m = re.match(r"(\d+)(?:-(\d+))?", piece)
        if m:
            numbers.append(m.group(1))
            continue
        numbers.extend(re.findall(r"\d+", piece))
    seen = set()
    deduped = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def parse_number_token(token: str) -> tuple[str | None, str | None]:
    """Parse a single token and return (base, branch) if it contains a number."""
    t = normalize_separators(normalize_num(token))
    stripped = re.sub(r"[法第条]", "", t)
    stripped = stripped.replace("の", "-")
    m = re.search(r"(\d+)(?:-(\d+))?", stripped)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def generate_number_terms(base: str, branch_hint: str | None = None) -> set[str]:
    """Generate related search terms for a given article number."""
    terms: set[str] = set()
    try:
        n_int = int(base)
    except ValueError:
        return terms
    kan = int_to_kanji(n_int)
    base_forms = {
        base,
        f"{base}条",
        f"第{base}条",
        f"{kan}",
        f"{kan}条",
        f"第{kan}条",
        f"法第{base}条",
        f"令第{base}条",
        f"法第{kan}条",
        f"令第{kan}条",
        f"第{base}条の",
        f"第{kan}条の",
        f"法第{base}条の",
        f"令第{base}条の",
    }
    terms.update(base_forms)

    branch_candidates: list[str] = []
    if branch_hint:
        branch_candidates.append(branch_hint)
    branch_candidates.extend([str(i) for i in range(1, 11)])

    for b in branch_candidates:
        try:
            b_int = int(b)
        except ValueError:
            continue
        b_kan = int_to_kanji(b_int)
        terms.update(
            {
                f"第{base}条の{b}",
                f"第{kan}条の{b}",
                f"第{base}条の{b_kan}",
                f"第{kan}条の{b_kan}",
                f"法第{base}条の{b}",
                f"令第{base}条の{b}",
            }
        )

    expanded = set()
    for t in terms:
        expanded.add(t)
        expanded.add(normalize_num(t))
    return {x for x in expanded if x}


def build_term_groups(query: str, article_mode: bool = False) -> list[set[str]]:
    """Split query into tokens and expand each into OR groups."""
    tokens = [tok for tok in re.split(r"\s+", query) if tok]
    groups: list[set[str]] = []
    for tok in tokens:
        base, branch = parse_number_token(tok)
        group: set[str] = set()
        tok_norm = normalize_separators(normalize_num(tok))
        if base and article_mode:
            for term in generate_number_terms(base, branch):
                if "条" in term:
                    group.add(term)
            if "条" in tok_norm:
                group.add(tok_norm)
        else:
            group.add(tok_norm)
            if base:
                group.update(generate_number_terms(base, branch))
        groups.append({g for g in group if g})
    return groups


def matches_group(raw_text: str, norm_text: str, terms: set[str]) -> bool:
    """Check whether any term in the group matches raw or normalized text."""
    for term in terms:
        if not term:
            continue
        norm_term = normalize_num(term)
        if term in raw_text or norm_term in raw_text:
            return True
        if term in norm_text or norm_term in norm_text:
            return True
    return False


def is_branch_mode(query: str) -> bool:
    return ("の" in query) or any(ch in query for ch in ("-", "ー", "－", "―", "‐", "‑", "–", "—", "〜", "～"))


def build_branch_patterns(base: str, branch: str) -> list[re.Pattern]:
    """Generate regex patterns that require 条の/条- style with exact branch (fullmatch only)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    try:
        branch_k = int_to_kanji(int(branch))
    except Exception:
        branch_k = branch

    prefixes = ["", "法", "令"]
    base_variants = [
        f"{base}",
        f"{base_k}",
    ]
    branch_variants = [branch, branch_k]
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    for pre in prefixes:
        for b in base_variants:
            for br in branch_variants:
                pat = rf"^{pre}第?{b}条{sep}{br}$"
                patterns.append(re.compile(pat))
    return patterns


def build_branch_patterns_any(base: str) -> list[re.Pattern]:
    """Regex patterns for any branch number of given base (fullmatch)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    branch_part = r"(\d+|[一二三四五六七八九十百千〇零]+)"
    for b in (base, base_k):
        pat = rf"^(?:法|令)?第?{b}条{sep}{branch_part}$"
        patterns.append(re.compile(pat))
    return patterns


def build_branch_search_patterns_any(base: str) -> list[re.Pattern]:
    """Regex patterns (search) for any branch number of given base (non-anchored)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    branch_part = r"(\d+|[一二三四五六七八九十百千〇零]+)"
    for b in (base, base_k):
        pat = rf"(?:法|令)?第?{b}条{sep}{branch_part}"
        patterns.append(re.compile(pat))
    return patterns


def build_query_profile(query: str) -> dict:
    raw = query
    norm = normalize_separators(normalize_num(query))
    law_hint = ("法" in raw) or ("建築基準法" in raw)
    order_hint = ("令" in raw) or ("施行令" in raw)

    article_intent = ("条" in raw) or ("第" in raw) or bool(re.search(r"\d+条", norm))

    base = branch = None
    branch_any = False
    number_bases: list[str] = []
    m_branch = re.search(r"第?(\d+)条(?:の|ー|-)(\d+)$", norm)
    if m_branch:
        base, branch = m_branch.group(1), m_branch.group(2)
    else:
        m_branch_any = re.search(r"第?(\d+)条(?:の|ー|-)$", norm)
        if m_branch_any:
            base, branch_any = m_branch_any.group(1), True
        else:
            m_base = re.search(r"第?(\d+)条", norm)
            if m_base:
                base = m_base.group(1)
    if base:
        number_bases.append(base)
    elif not article_intent:
        number_bases.extend(extract_query_numbers(query))
    if not article_intent and number_bases:
        article_intent = True
    if base is None and number_bases:
        base = number_bases[0]

    title_terms = set()
    text_terms = set()
    text_patterns: list[re.Pattern] = []
    highlight_terms = set()

    def add_term_sets(terms: set[str]):
        title_terms.update(terms)
        text_terms.update(terms)
        highlight_terms.update(terms)

    prefixes = ["", "法", "令"]
    seps = ["の", "ー", "-"]

    def base_variants(b: str):
        try:
            b_kan = int_to_kanji(int(b))
        except Exception:
            b_kan = b
        return [b, b_kan]

    def branch_variants(br: str):
        try:
            br_kan = int_to_kanji(int(br))
        except Exception:
            br_kan = br
        return [br, br_kan]

    if article_intent and base:
        bvars = base_variants(base)
        if branch:
            brvars = branch_variants(branch)
            terms = set()
            for p in prefixes:
                for b in bvars:
                    for br in brvars:
                        for s in seps:
                            terms.add(f"{p}第{b}条{s}{br}")
            add_term_sets(terms)
            text_terms = terms.copy()
        elif branch_any:
            # number hits will rely on regex (branch required); terms used for highlight and text search
            terms = set()
            for p in prefixes:
                for b in bvars:
                    for s in seps:
                        terms.add(f"{p}第{b}条{s}")
            highlight_terms.update(terms)
            # text search uses regex requiring branch
            for b in bvars:
                text_patterns.append(
                    re.compile(rf"(?:法|令)?第?{b}条(?:の|ー|-)(\d+|[一二三四五六七八九十百千〇零]+)")
                )
        else:
            terms = set()
            for p in prefixes:
                for b in bvars:
                    terms.add(f"{p}第{b}条")
            add_term_sets(terms)
    else:
        nums = number_bases or extract_query_numbers(query)
        if nums:
            for num in nums:
                bvars = base_variants(num)
                bare_terms = set()
                for b in bvars:
                    bare_terms.add(b)
                    bare_terms.add(f"第{b}条")
                    bare_terms.add(f"法第{b}条")
                    bare_terms.add(f"令第{b}条")
                add_term_sets(bare_terms)
        # include raw query as text term for loose match
        text_terms.add(raw)
        highlight_terms.update(text_terms)

    return {
        "raw": raw,
        "norm": norm,
        "law_hint": law_hint,
        "order_hint": order_hint,
        "article_intent": article_intent,
        "base": base,
        "branch": branch,
        "branch_any": branch_any,
        "number_bases": number_bases,
        "title_terms_raw": title_terms,
        "title_terms_norm": {normalize_separators(normalize_num(t)) for t in title_terms},
        "text_terms_raw": text_terms,
        "text_terms_norm": {normalize_separators(normalize_num(t)) for t in text_terms},
        "text_patterns": text_patterns,
        "highlight_terms": highlight_terms,
    }


def build_formal_patterns(base: str, branch: str | None):
    """Return (title_patterns, text_patterns) for formal article matching."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    branch_k = None
    if branch is not None:
        try:
            branch_k = int_to_kanji(int(branch))
        except Exception:
            branch_k = branch

    prefixes = ["", "法", "令"]
    title_patterns = []
    text_patterns = []

    def add_patterns(b, br):
        if br is None:
            title_patterns.append(re.compile(rf"^(?:法|令)?第?{b}条$"))
            text_patterns.append(re.compile(rf"(?:法|令)?第?{b}条(?![の0-9一二三四五六七八九十百千])"))
        else:
            title_patterns.append(re.compile(rf"^(?:法|令)?第?{b}条(?:の|ー|-){br}$"))
            text_patterns.append(
                re.compile(rf"(?:法|令)?第?{b}条(?:の|ー|-){br}(?![0-9一二三四五六七八九十百千])")
            )

    add_patterns(base, branch)
    add_patterns(base_k, branch_k)

    return title_patterns, text_patterns


def matches_branch_patterns(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


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


def make_safe_id(prefix_ascii: str, title: str, i: int) -> str:
    n = normalize_num(title)
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", n)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or safe[0].isdigit():
        safe = f"_{safe}"
    return f"{prefix_ascii}_{safe}_{i}_{uuid.uuid4().hex[:8]}"


def highlight_text(s: str, terms: list[str]) -> Text:
    t = Text(s, no_wrap=False, overflow="fold")
    for term in terms:
        if not term:
            continue
        pats = {re.escape(term)}
        norm = normalize_num(term)
        if norm != term:
            pats.add(re.escape(norm))
        for pat in pats:
            for m in re.finditer(pat, s):
                t.stylize("bold black on #ff8800", m.start(), m.end())
    return t


# ==== 構造抽出（階層・配列保持） ====
def _extract_sentences(container: ET.Element | None):
    """ItemSentence や ParagraphSentence から Sentence/Column を配列で返す。"""
    if container is None:
        return {"sentences": [], "columns": []}
    sentences = [get_text(s) for s in container.findall(".//{*}Sentence")]
    columns = [get_text(c) for c in container.findall(".//{*}Column")]
    return {"sentences": sentences, "columns": columns}


def _extract_items(elem: ET.Element, level: int):
    """
    Item / Subitem1 / Subitem2 / Subitem3 を再帰的に抽出。
    level=1 -> Item の配下に subitems1
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
            entry["subitems"] = []  # 最下層でもキーを保持（空配列）
        results.append(entry)
    return results


def extract_structure(article: ET.Element):
    """
    Article から Article/Paragraph/Item/Subitem1-3 を全走査し、
    JSON 互換の辞書構造で返す。
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
    """構造を JSON 文字列として返す。非表示条件に該当する要素は省く。"""

    def prune(obj):
        # 空配列・空dict・None は表示しない
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

    # article_number が title と一致する場合は表示しない
    pruned_struct = dict(struct)
    if pruned_struct.get("article_number") == title:
        pruned_struct.pop("article_number", None)

    payload = {"title": title}
    pruned_structure = prune(pruned_struct)
    if pruned_structure:
        payload["structure"] = pruned_structure
    # JSON文字列表示は不要になったが互換のため残す
    import json as _json
    return _json.dumps(payload, ensure_ascii=False, indent=2)


def render_article_plain(title: str, struct: dict) -> str:
    """
    XML由来の階層構造をプレーンテキストに整形して返す。
    改行のみで区切り、空行は作らない。
    """
    lines = []

    def append_numbered(lines_list, line):
        if lines_list and lines_list[-1] != "":
            lines_list.append("")
        lines_list.append(line)

    # 1) タイトル行
    lines.append(title)
    lines.append("")

    paragraphs = struct.get("paragraphs") or []
    for para in paragraphs:
        # Paragraph本体
        pnum = para.get("paragraph_number")
        p_sentences = (para.get("paragraph_sentence") or {}).get("sentences") or []
        p_body = " ".join(s for s in p_sentences if s)
        if p_body:
            prefix = f"{pnum}　　" if pnum else ""
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
                append_numbered(lines, f"{num}　　{body}")
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
                    append_numbered(lines, f"  {snum}　　{s_body}")
                else:
                    lines.append(f"  {s_body}")

    return "\n".join(lines)


# ==== 章・節コンテキスト抽出 ====
def build_article_context_map(root: ET.Element):
    """
    MainProvision 内の Article ごとに章タイトル・節タイトルをマッピングする。
    節がない場合 section_title は None。
    """
    context = {}
    main_provision = root.find(".//{*}MainProvision")
    if main_provision is None:
        return context

    for chapter in main_provision.findall("./{*}Chapter"):
        chapter_title = chapter.findtext("./{*}ChapterTitle") or None

        for section in chapter.findall("./{*}Section"):
            section_title = section.findtext("./{*}SectionTitle") or None
            for art in section.findall("./{*}Article"):
                context[art] = {
                    "chapter_title": chapter_title,
                    "section_title": section_title or None,
                }

        for art in chapter.findall("./{*}Article"):
            context.setdefault(
                art, {"chapter_title": chapter_title, "section_title": None}
            )

    return context


def get_article_base_number(title: str) -> str | None:
    """ArticleTitle から条の基番号（数字）を抽出する。"""
    t_norm = normalize_num(title)
    m = re.search(r"第(\d+)条", t_norm)
    if m:
        return m.group(1)
    return None


# ==== 検索処理 ====


def search_articles_simple(root: ET.Element, profile: dict):
    """単純化した検索ロジックで条番号一致／本文中一致を返す。"""
    results_number = []
    results_text = []
    context_map = build_article_context_map(root)

    title_terms_raw = profile["title_terms_raw"]
    title_terms_norm = profile["title_terms_norm"]
    text_terms_raw = profile["text_terms_raw"]
    text_terms_norm = profile["text_terms_norm"]
    text_patterns = profile["text_patterns"]

    base = profile["base"]
    branch = profile["branch"]
    branch_any = profile["branch_any"]
    article_intent = profile["article_intent"]
    number_bases = profile.get("number_bases", [])

    branch_any_anchored = build_branch_patterns_any(base) if branch_any and base else []
    branch_any_search = build_branch_search_patterns_any(base) if branch_any and base else []
    branch_exact_patterns = build_branch_patterns(base, branch) if (branch and base) else []

    base_patterns_anchored = []
    if article_intent or number_bases:
        bases = [base] if base else number_bases
        for b_base in bases:
            try:
                b_kan = int_to_kanji(int(b_base))
            except Exception:
                b_kan = b_base
            branch_part = r"(?:(?:の|ー|-)(?:\d+|[一二三四五六七八九十百千〇零]+))?"
            for b in (b_base, b_kan):
                base_patterns_anchored.append(re.compile(rf"^(?:法|令)?第?{b}条{branch_part}$"))

    def build_entry(art):
        title = art.findtext(".//{*}ArticleTitle") or ""
        caption = art.findtext(".//{*}ArticleCaption") or ""
        struct = extract_structure(art)
        full_plain = render_article_plain(title, struct)
        body_lines = full_plain.splitlines()
        body_plain = "\n".join(body_lines[1:]) if len(body_lines) > 1 else ""
        ctx = context_map.get(art, {})
        return {
            "title": title,
            "caption": caption,
            "structure": struct,
            "full_text": full_plain,
            "body_text": body_plain,
            "chapter_title": ctx.get("chapter_title"),
            "section_title": ctx.get("section_title"),
        }

    for art in root.findall(".//{*}MainProvision//{*}Article"):
        entry = build_entry(art)
        title_raw = entry["title"]
        title_norm = normalize_separators(normalize_num(title_raw))
        body_source = entry.get("body_text") or ""
        body_raw = clean_text_display(entry["caption"] + body_source)
        body_norm = normalize_separators(normalize_num(body_raw))

        # 条番号一致
        title_match = False
        if branch and branch_exact_patterns:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in branch_exact_patterns)
        elif branch_any and branch_any_anchored:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in branch_any_anchored)
        elif (article_intent or number_bases) and base_patterns_anchored:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in base_patterns_anchored)
            if not title_match and base:
                try:
                    base_kan = int_to_kanji(int(base))
                except Exception:
                    base_kan = base
                fallback_pat = re.compile(rf"^(?:法|令)?第?(?:{base}|{base_kan})条(?:の|ー|-)?\d*$")
                if fallback_pat.match(title_norm):
                    title_match = True
        else:
            if title_raw in title_terms_raw or title_norm in title_terms_norm:
                title_match = True

        if title_match:
            results_number.append(entry)

        # 本文中一致（常に実行）
        text_hit = False
        if branch:
            for term in text_terms_raw:
                if term and (term in body_raw or term in body_norm):
                    text_hit = True
                    break
            if not text_hit:
                for term in text_terms_norm:
                    if term and (term in body_norm or term in body_raw):
                        text_hit = True
                        break
            if not text_hit and text_patterns:
                text_hit = any(p.search(body_raw) or p.search(body_norm) for p in text_patterns)
        elif branch_any and branch_any_search:
            text_hit = any(p.search(body_raw) or p.search(body_norm) for p in branch_any_search)
        else:
            if any(term and (term in body_raw or term in body_norm) for term in text_terms_raw):
                text_hit = True
            elif any(term and (term in body_raw or term in body_norm) for term in text_terms_norm):
                text_hit = True
            elif text_patterns and any(p.search(body_raw) or p.search(body_norm) for p in text_patterns):
                text_hit = True

        if text_hit:
            results_text.append(entry)

    return {"number_hits": results_number, "text_hits": results_text}


def search_both_laws(root_main, root_order, query: str):
    profile = build_query_profile(query)

    results = {
        "法": search_articles_simple(root_main, profile),
        "令": search_articles_simple(root_order, profile),
    }

    if profile["law_hint"] and not profile["order_hint"]:
        results["令"]["number_hits"] = []
    elif profile["order_hint"] and not profile["law_hint"]:
        results["法"]["number_hits"] = []

    return results


# ==== 漢数字変換 ====
KANJI_DIGITS_REV = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def int_to_kanji(n: int) -> str:
    """0〜999程度までの整数を漢数字に変換"""
    if n == 0:
        return "零"
    units = ["", "十", "百", "千"]
    s, d = "", 0
    while n > 0:
        n, r = divmod(n, 10)
        if r:
            prefix = "" if (d > 0 and r == 1) else KANJI_DIGITS_REV[r]
            s = prefix + (units[d] if d else "") + s
        d += 1
    return s


# ==== アプリ ====
class Building_Code_Search(App):
    CSS = """

    Screen { layout: vertical; background: #0f0f12; color: #e8e8e8; }
    #query_input { margin: 1; }
    #result_list { height: 15; margin: 1; border: solid #444; }
    #article_scroll { height: 1fr; margin: 1; border: solid #444; }
    #article_body { width: 100%; padding: 1; }
    #all_results_copy { margin: 1; }

    #result_list > ListItem {
        background: transparent;
        color: #e8e8e8;
    }
    #result_list > ListItem:hover,
    #result_list > ListItem.selected {
        background: #ff8800;
        color: black;
        text-style: bold;
    }
    #result_list > ListItem > Static {
        color: #e8e8e8;
    }
    #result_list > ListItem:hover > Static,
    #result_list > ListItem.selected > Static {
        color: black;
    }

    """

    BINDINGS = [("e", "quit", "Exit"), ("ctrl+c", "copy_article", "Copy Article")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Input(placeholder="検索キーワードを入力 (例: 111条 / 耐火構造)", id="query_input")
            yield ListView(id="result_list")
            self.article_body = Static("ここに本文が表示されます", id="article_body")
            yield VerticalScroll(self.article_body, id="article_scroll")
            yield Button("All_results_Copy", id="all_results_copy")
        yield Footer()

    def notify_safe(self, message: str, severity: str = "information"):
        """self.notify が使えない環境向けフォールバック。"""
        try:
            self.notify(message, severity=severity)
        except Exception:
            try:
                self.article_body.update(f"[{severity}] {message}")
            except Exception:
                print(f"[{severity}] {message}")

    def on_mount(self):
        self.root_main = None
        self.root_order = None
        self.results = {"法": {"number_hits": [], "text_hits": []}, "令": {"number_hits": [], "text_hits": []}}
        self.display_entries = []

        self.query_input = self.query_one("#query_input", Input)
        self.result_list = self.query_one("#result_list", ListView)
        self.article_scroll = self.query_one("#article_scroll", VerticalScroll)
        self.article_scroll.can_focus = True
        self.index_map = {}
        self.set_focus(self.query_input)
        self.current_article_text = ""

    def action_focus_search(self):
        self.set_focus(self.query_input)

    def on_input_submitted(self, event: Input.Submitted):
        q = event.value.strip()
        self.result_list.clear()
        self.article_body.update("ここに本文が表示されます")
        self.index_map.clear()
        self.display_entries = []

        if not q:
            self.result_list.append(ListItem(Static("❗ キーワードを入力してください")))
            self.set_focus(self.result_list)
            return

        if self.root_main is None or self.root_order is None:
            self.article_body.update("法令データ取得中…")
            self.call_after_refresh(lambda: self._perform_search(q))
            return

        self._perform_search(q)

    def _perform_search(self, q: str):
        if self.root_main is None or self.root_order is None:
            try:
                today = date.today().strftime("%Y-%m-%d")
                self.root_main = safe_fetch(LAW_MAIN_ID, today)
                self.root_order = safe_fetch(LAW_ORDER_ID, today)
            except Exception:
                self.result_list.append(ListItem(Static("データ取得に失敗しました")))
                self.notify_safe("データ取得に失敗しました", severity="error")
                self.set_focus(self.result_list)
                return

            if any(root is None or getattr(root, "tag", "") == "Root" for root in (self.root_main, self.root_order)):
                self.result_list.append(ListItem(Static("データ取得に失敗しました")))
                self.notify_safe("データ取得に失敗しました", severity="error")
                self.set_focus(self.result_list)
                return

        raw_results = search_both_laws(self.root_main, self.root_order, q)
        has_any = any(
            raw_results[law]["number_hits"] or raw_results[law]["text_hits"]
            for law in ("法", "令")
        )
        if not has_any:
            self.result_list.append(ListItem(Static("該当なし")))
            self.set_focus(self.result_list)
            return

        total_raw = sum(
            len(raw_results[law]["number_hits"]) + len(raw_results[law]["text_hits"])
            for law in ("法", "令")
        )
        limit = 100
        truncated = total_raw > limit
        buckets = {
            "条番号一致": {"法": [], "令": []},
            "本文中一致": {"法": [], "令": []},
        }

        count = 0
        reached_limit = False
        for category, key in (("条番号一致", "number_hits"), ("本文中一致", "text_hits")):
            for law in ("法", "令"):
                for entry in raw_results[law][key]:
                    if count >= limit:
                        reached_limit = True
                        break
                    entry_copy = dict(entry)
                    entry_copy["law_type"] = law
                    entry_copy["category"] = category
                    buckets[category][law].append(entry_copy)
                    self.display_entries.append(entry_copy)
                    count += 1
                if reached_limit:
                    break
            if reached_limit:
                break

        if reached_limit:
            truncated = True

        self.results = buckets

        if truncated:
            self.result_list.append(ListItem(Static("100件を超えるため上位100件のみ表示")))

        # 条番号一致
        self.result_list.append(ListItem(Static("【条番号一致】")))
        has_both_number_series = buckets["条番号一致"]["法"] and buckets["条番号一致"]["令"]
        for law in ("法", "令"):
            prefix = "LAW" if law == "法" else "ORDER"
            entries = buckets["条番号一致"][law]
            for entry in entries:
                label = f"{law} {entry['title']}"
                item_id = make_safe_id(f"{prefix}_NUM", entry["title"], len(self.index_map))
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = entry
                self.result_list.append(item)
            if law == "法" and has_both_number_series and entries:
                self.result_list.append(ListItem(Static(" ")))

        # 本文中一致
        self.result_list.append(ListItem(Static(" ")))
        self.result_list.append(ListItem(Static("【本文中一致】")))
        has_both_text_series = buckets["本文中一致"]["法"] and buckets["本文中一致"]["令"]
        for law in ("法", "令"):
            prefix = "LAW" if law == "法" else "ORDER"
            entries = buckets["本文中一致"][law]
            for entry in entries:
                label = f"{law} {entry['title']}"
                item_id = make_safe_id(f"{prefix}_TXT", entry["title"], len(self.index_map))
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = entry
                self.result_list.append(item)
            if law == "法" and has_both_text_series and entries:
                self.result_list.append(ListItem(Static(" ")))

        if not (buckets["本文中一致"]["法"] or buckets["本文中一致"]["令"]):
            self.result_list.append(ListItem(Static("該当なし")))

        self.set_focus(self.result_list)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "all_results_copy":
            self.action_all_results_copy()

    def on_list_view_selected(self, event: ListView.Selected):
        if not event.item or event.item.id not in self.index_map:
            return

        for child in self.result_list.children:
            try:
                child.remove_class("selected")
            except Exception:
                pass
        try:
            event.item.add_class("selected")
        except Exception:
            pass

        entry = self.index_map[event.item.id]
        rendered = entry.get("full_text") or render_article_plain(entry["title"], entry["structure"])

        header_lines = []
        if entry.get("law_type"):
            header_lines.append(entry["law_type"])
        if entry.get("chapter_title"):
            header_lines.append(entry["chapter_title"])
        if entry.get("section_title"):
            header_lines.append(entry["section_title"])
        if entry.get("caption"):
            header_lines.append(entry["caption"])

        display_text = rendered
        if header_lines:
            display_text = "\n".join(header_lines) + "\n\n" + rendered

        self.current_article_text = display_text

        highlight_terms = set()
        profile = build_query_profile(self.query_input.value)
        highlight_terms.update(profile.get("highlight_terms", set()))
        self.article_body.update(highlight_text(display_text, list(highlight_terms)))
        self.set_focus(self.article_scroll)

    def action_all_results_copy(self):
        """検索結果の全件をJSON配列としてクリップボードにコピーする。"""
        try:
            payload = []
            for entry in getattr(self, "display_entries", []):
                raw_entry = {
                    "law_type": entry.get("law_type"),
                    "chapter_title": entry.get("chapter_title"),
                    "section_title": entry.get("section_title"),
                    "article_title": entry.get("title"),
                    "article_caption": entry.get("caption"),
                    "full_text": entry.get("full_text")
                    or render_article_plain(
                        entry.get("title", ""), entry.get("structure") or {}
                    ),
                }
                cleaned = prune_empty(copy.deepcopy(raw_entry))
                if cleaned:
                    payload.append(cleaned)

            if not payload:
                self.notify_safe("No results to copy", severity="warning")
                return

            json_text = json.dumps(payload, ensure_ascii=False, indent=2)
            pyperclip.copy(json_text)
            self.notify_safe("📋 All results copied to clipboard", severity="information")
        except Exception as e:
            self.notify_safe(f"全件コピーに失敗しました: {e}", severity="error")

    def action_copy_article(self):
        """表示中の本文をクリップボードへコピー。"""
        try:
            text = getattr(self, "current_article_text", None)
            if not text:
                renderable = getattr(self.article_body, "renderable", None)
                if hasattr(renderable, "plain"):
                    text = renderable.plain
                elif isinstance(renderable, str):
                    text = renderable
                elif hasattr(self.article_body, "text"):
                    text = self.article_body.text
                else:
                    text = str(renderable) if renderable is not None else ""

            if not text:
                raise ValueError("コピーする本文が見つかりません")

            pyperclip.copy(text)
            self.notify_safe("📋 本文をコピーしました", severity="information")
        except Exception as e:
            self.notify_safe(f"コピー失敗: {e}", severity="error")


if __name__ == "__main__":
    Building_Code_Search().run()

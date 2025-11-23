# -*- coding: utf-8 -*-
# 建築基準法／施行令の検索ビューア（構造保持版）
import json
import re
import uuid
import traceback
from datetime import date
import xml.etree.ElementTree as ET

import pyperclip
import requests
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

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
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ==== 検索処理 ====
def search_articles(root: ET.Element, query: str):
    """法XMLから、条番号・キーワードを検索して該当条を返す。構造情報付き。"""
    norm_q = normalize_num(query)
    results = []

    def build_entry(art):
        title = art.findtext(".//{*}ArticleTitle") or ""
        caption = art.findtext(".//{*}ArticleCaption") or ""
        text = " ".join(get_text(s) for s in art.findall(".//{*}Sentence"))
        joined = clean_text_display(title + caption + text)
        struct = extract_structure(art)
        return {"title": title, "caption": caption, "joined": joined, "structure": struct}

    # --- 条数検索（完全一致） ---
    m = re.fullmatch(r"第?(\d+)条(?:の(\d+))?", norm_q)
    if m:
        base, sub = m.group(1), m.group(2)
        for art in root.findall(".//{*}MainProvision//{*}Article"):
            title = art.findtext(".//{*}ArticleTitle") or ""
            t_norm = normalize_num(title)
            if t_norm.startswith(f"第{base}条") and (not sub or f"の{sub}" in t_norm):
                results.append(build_entry(art))
        return results

    # --- 通常キーワード検索 ---
    tokens = [normalize_num(k) for k in query.strip().split()]
    if not tokens:
        return results

    key_groups = []
    for tok in tokens:
        opts = {tok}
        if tok.isdigit():
            opts.update({
                f"第{tok}条", f"第{tok}条の",
                f"法第{tok}条", f"令第{tok}条",
                f"法第{tok}条の", f"令第{tok}条の",
            })
        key_groups.append(opts)

    for art in root.findall(".//{*}MainProvision//{*}Article"):
        title = art.findtext(".//{*}ArticleTitle") or ""
        caption = art.findtext(".//{*}ArticleCaption") or ""
        text = " ".join(get_text(s) for s in art.findall(".//{*}Sentence"))
        joined = clean_text_display(title + caption + text)
        jn = normalize_num(joined)
        if all(any(opt in jn for opt in group) for group in key_groups):
            struct = extract_structure(art)
            results.append({"title": title, "caption": caption, "joined": joined, "structure": struct})

    return results


def search_both_laws(root_main, root_order, query: str):
    return {
        "法": search_articles(root_main, query),
        "令": search_articles(root_order, query),
    }


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
        today = date.today().strftime("%Y-%m-%d")
        self.root_main = safe_fetch(LAW_MAIN_ID, today)
        self.root_order = safe_fetch(LAW_ORDER_ID, today)
        self.results = {"法": [], "令": []}

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

        if not q:
            self.result_list.append(ListItem(Static("❗ キーワードを入力してください")))
            self.set_focus(self.result_list)
            return

        self.results = search_both_laws(self.root_main, self.root_order, q)
        if not (self.results["法"] or self.results["令"]):
            self.result_list.append(ListItem(Static("該当なし")))
            self.set_focus(self.result_list)
            return

        if self.results["法"]:
            self.result_list.append(ListItem(Static("【建築基準法】")))
            for i, entry in enumerate(self.results["法"]):
                label = f"法 {entry['title']} {entry['caption'].strip() if entry['caption'] else ''}"
                item_id = make_safe_id("LAW", entry["title"], i)
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = ("法", i)
                self.result_list.append(item)

        if self.results["令"]:
            self.result_list.append(ListItem(Static(" ")))
            self.result_list.append(ListItem(Static("【建築基準法施行令】")))
            for i, entry in enumerate(self.results["令"]):
                label = f"令 {entry['title']} {entry['caption'].strip() if entry['caption'] else ''}"
                item_id = make_safe_id("ORDER", entry["title"], i)
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = ("令", i)
                self.result_list.append(item)

        self.set_focus(self.result_list)

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

        law_type, idx = self.index_map[event.item.id]
        entry = self.results[law_type][idx]
        rendered = render_structure(entry["title"], entry["structure"])
        self.current_article_text = rendered

        raw_terms = [normalize_num(t) for t in self.query_input.value.strip().split()]
        expanded_terms = set()
        for t in raw_terms:
            expanded_terms.add(t)
            if t.isdigit():
                kan = int_to_kanji(int(t))
                expanded_terms.update({
                    f"{t}", f"第{t}条", f"第{t}条の",
                    f"{kan}", f"第{kan}条", f"第{kan}条の"
                })
        terms = list(expanded_terms)
        self.article_body.update(highlight_text(rendered, terms))
        self.set_focus(self.article_scroll)

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

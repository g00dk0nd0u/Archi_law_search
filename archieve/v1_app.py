# -*- coding: utf-8 -*-
# 建築基準法／施行令 両方を検索（安定版・VerticalScroll）
import re
import requests
import xml.etree.ElementTree as ET
from datetime import date
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, ListView, ListItem, Static
from textual.containers import Vertical, VerticalScroll
from rich.text import Text
import uuid
import pyperclip
import traceback

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
    """fetch_law_xml をラップして例外を吸収。失敗時は空のルートを返す"""
    try:
        return fetch_law_xml(law_id, as_of_date)
    except Exception as e:
        # printing to console helps debugging when running with --console
        print(f"[WARN] fetch_law_xml failed for {law_id}: {e}")
        traceback.print_exc()
        return ET.Element("Root")  # 空のダミーで継続可能

def strip_ns(tag): return tag.split('}', 1)[-1] if '}' in tag else tag
def get_text(elem):
    parts = []
    if elem.text: parts.append(elem.text)
    for e in elem:
        parts.append(get_text(e))
        if e.tail: parts.append(e.tail)
    return ''.join(parts)

# ==== 整形 ====
def clean_text_display(t): return t.replace('\n', '').replace('　', '').strip()
def add_linebreaks(txt: str) -> str:
    res, depth = [], 0
    for ch in txt:
        if ch == '（': depth += 1
        elif ch == '）' and depth > 0: depth -= 1
        res.append(ch)
        if ch == '。' and depth == 0:
            res.append('\n\n')
    return ''.join(res).strip()

# ==== 数字正規化 ====
KANJI_DIGITS = {'〇':0,'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
KANJI_UNITS = {'十':10,'百':100,'千':1000}
KANJI_SEQ_RE = re.compile(r'[〇零一二三四五六七八九十百千]+')

def _kanji_seq_to_int(seq: str) -> int:
    total, digit = 0, None
    for ch in seq:
        if ch in KANJI_DIGITS:
            d = KANJI_DIGITS[ch]
            digit = d if digit is None else digit*10 + d
        elif ch in KANJI_UNITS:
            u = KANJI_UNITS[ch]
            total += (digit or 1) * u
            digit = None
    if digit is not None: total += digit
    return total

def normalize_num(t: str) -> str:
    if not t: return ""
    t = t.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    t = KANJI_SEQ_RE.sub(lambda m: str(_kanji_seq_to_int(m.group())), t)
    t = re.sub(r'\s+', '', t)
    if "条" in t and "第" not in t:
        idx = t.find("条")
        if any(ch.isdigit() for ch in t[:idx]):
            t = "第" + t
    return t

# ==== ID生成 ====
def make_safe_id(prefix_ascii: str, title: str, i: int) -> str:
    n = normalize_num(title)
    safe = re.sub(r'[^0-9A-Za-z_-]+', '_', n)
    safe = re.sub(r'_+', '_', safe).strip('_')
    if not safe or safe[0].isdigit():
        safe = f"_{safe}"
    return f"{prefix_ascii}_{safe}_{i}_{uuid.uuid4().hex[:8]}"

# ==== ハイライト ====
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

# ==== 検索処理 ====
def search_articles(root: ET.Element, query: str):
    """指定した法XMLから、条番号・キーワードを検索して該当条文を返す。"""
    norm_q = normalize_num(query)
    results = []

    # --- 条数検索（完全一致） ---
    m = re.fullmatch(r'第?(\d+)条(?:の(\d+))?', norm_q)
    if m:
        base, sub = m.group(1), m.group(2)
        for art in root.findall(".//{*}MainProvision//{*}Article"):
            title = art.findtext('.//{*}ArticleTitle') or ''
            caption = art.findtext('.//{*}ArticleCaption') or ''
            text = ' '.join(get_text(s) for s in art.findall('.//{*}Sentence'))
            joined = clean_text_display(title + caption + text)
            t_norm = normalize_num(title)
            if t_norm.startswith(f"第{base}条") and (not sub or f"の{sub}" in t_norm):
                results.append((title, caption, joined))
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
                f"法第{tok}条の", f"令第{tok}条の"
            })
        key_groups.append(opts)

    for art in root.findall(".//{*}MainProvision//{*}Article"):
        title = art.findtext('.//{*}ArticleTitle') or ''
        caption = art.findtext('.//{*}ArticleCaption') or ''
        text = ' '.join(get_text(s) for s in art.findall('.//{*}Sentence'))
        joined = clean_text_display(title + caption + text)
        jn = normalize_num(joined)
        if all(any(opt in jn for opt in group) for group in key_groups):
            results.append((title, caption, joined))

    return results

def search_both_laws(root_main, root_order, query: str):
    return {
        "法": search_articles(root_main, query),
        "令": search_articles(root_order, query)
    }

# ==== 漢数字変換 ====
KANJI_DIGITS_REV = ['零','一','二','三','四','五','六','七','八','九']
def int_to_kanji(n: int) -> str:
    """0～9999程度までの整数を漢数字に変換"""
    if n == 0:
        return '零'
    units = ['', '十', '百', '千']
    s, d = '', 0
    while n > 0:
        n, r = divmod(n, 10)
        if r:
            prefix = '' if (d > 0 and r == 1) else KANJI_DIGITS_REV[r]
            s = prefix + (units[d] if d else '') + s
        d += 1
    return s

# ==== アプリ ====
class  Building_Code_Search(App):
    CSS = """

    Screen { layout: vertical; background: #0f0f12; color: #e8e8e8; }
    #query_input { margin: 1; }
    #result_list { height: 15; margin: 1; border: solid #444; }
    #article_scroll { height: 1fr; margin: 1; border: solid #444; }
    #article_body { width: 100%; padding: 1; }

    /* 非選択時の ListItem 見た目 */
    #result_list > ListItem {
        background: transparent;
        color: #e8e8e8;
    }

    /* hover / selected はオレンジ背景＋黒文字 */
    #result_list > ListItem:hover,
    #result_list > ListItem.selected {
        background: #ff8800;
        color: black;
        text-style: bold;
    }

    /* ListItem 内の Static に色を明示（選択時と非選択時を切替） */
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
            yield Input(placeholder="検索キーワード入力欄　例: 111条 / 耐火構造", id="query_input")
            yield ListView(id="result_list")
            self.article_body = Static("ここに本文が表示されます。", id="article_body")
            yield VerticalScroll(self.article_body, id="article_scroll")
        yield Footer()

    def notify_safe(self, message: str, severity: str = "information"):
        """self.notify が使えない環境のフォールバックを提供"""
        try:
            # prefer built-in notify if available
            self.notify(message, severity=severity)
        except Exception:
            # fallback: brief message in article body without clobbering content long-term
            try:
                # 一時的表示（3行以内） -> 既存本文を上書きしないため元に戻す処理はしないが、
                # ここではシンプルに短いメッセージを表示する
                self.article_body.update(f"[{severity}] {message}")
            except Exception:
                # 最終手段：stdoutに吐く
                print(f"[{severity}] {message}")

    def on_mount(self):
        today = date.today().strftime("%Y-%m-%d")
        # safe_fetch を使いネットワーク失敗でクラッシュしない
        self.root_main = safe_fetch(LAW_MAIN_ID, today)
        self.root_order = safe_fetch(LAW_ORDER_ID, today)
        self.results = {"法": [], "令": []}

        self.query_input = self.query_one("#query_input", Input)
        self.result_list  = self.query_one("#result_list", ListView)
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
        self.article_body.update("ここに本文が表示されます。")
        self.index_map.clear()

        if not q:
            self.result_list.append(ListItem(Static("❌ キーワードを入力してください")))
            self.set_focus(self.result_list)
            return

        self.results = search_both_laws(self.root_main, self.root_order, q)
        if not (self.results["法"] or self.results["令"]):
            self.result_list.append(ListItem(Static("該当なし")))
            self.set_focus(self.result_list)
            return

        if self.results["法"]:
            self.result_list.append(ListItem(Static("【建築基準法】")))
            for i, (title, caption, _) in enumerate(self.results["法"]):
                label = f"法 {title} {caption.strip() if caption else ''}"
                item_id = make_safe_id("LAW", title, i)
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = ("法", i)
                self.result_list.append(item)

        if self.results["令"]:
            self.result_list.append(ListItem(Static(" ")))
            self.result_list.append(ListItem(Static("【建築基準法施行令】")))
            for i, (title, caption, _) in enumerate(self.results["令"]):
                label = f"令 {title} {caption.strip() if caption else ''}"
                item_id = make_safe_id("ORDER", title, i)
                item = ListItem(Static(label), id=item_id)
                self.index_map[item_id] = ("令", i)
                self.result_list.append(item)

        self.set_focus(self.result_list)


    def on_list_view_selected(self, event: ListView.Selected):
        # まず有効性チェック
        if not event.item or event.item.id not in self.index_map:
            return

        # --- 見た目の selected クラスを全解除して、選択アイテムに付与 ---
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
        _, _, text = self.results[law_type][idx]
        m = re.match(r"^(第[0-9０-９一二三四五六七八九十百千]+条(の[0-9０-９一二三四五六七八九十百千]+)?（.*?）)", text)
        body = m.group(1) + "\n\n" + text[m.end():].lstrip() if m else text
        self.current_article_text = add_linebreaks(body)

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
        self.article_body.update(highlight_text(add_linebreaks(body), terms))
        self.set_focus(self.article_scroll)


    def action_copy_article(self):
        """本文コピー＋通知（プレーンテキストを優先）"""
        try:
            # まず表示時に保存したプレーンテキストを使う（最も信頼できる）
            text = getattr(self, "current_article_text", None)
            # フォールバック：renderable から取り出す（従来の方式）
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
                raise ValueError("コピーする本文が見つかりません。")

            pyperclip.copy(text)
            self.notify_safe("📋 本文をコピーしました", severity="information")
        except Exception as e:
            self.notify_safe(f"コピー失敗: {e}", severity="error")


if __name__ == "__main__":
     Building_Code_Search().run()

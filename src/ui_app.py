import copy
import json
import re
import asyncio
import uuid
from datetime import date

import pyperclip
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
)

try:
    from .laws_api import LAW_MAIN_ID, LAW_ORDER_ID, safe_fetch
    from .number_text_utils import normalize_num
    from .search_logic import build_query_profile, search_both_laws
    from .structure_extract import prune_empty, render_article_plain
except ImportError:  # script fallback
    from laws_api import LAW_MAIN_ID, LAW_ORDER_ID, safe_fetch
    from number_text_utils import normalize_num
    from search_logic import build_query_profile, search_both_laws
    from structure_extract import prune_empty, render_article_plain


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


class Building_Code_Search(App):
    CSS = """

    Screen { layout: vertical; background: #0f0f12; color: #e8e8e8; }
    #query_input { margin: 1; }
    #result_list { height: 15; margin: 1; border: solid #444; }
    #article_scroll { height: 1fr; margin: 1; border: solid #444; }
    #article_body { width: 100%; padding: 1; }
    #all_results_copy { margin: 1; }
    #single_results_copy { margin: 1; }

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
            with Horizontal():
                yield Button("All_results_Copy", id="all_results_copy")
                yield Button("Single_results_Copy", id="single_results_copy")
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

    async def show_loading_indicator(self):
        """法令データ取得中アニメーションを表示"""
        try:
            self.spinner = LoadingIndicator()
            await self.mount(self.spinner)
            await self.refresh()
        except Exception:
            pass

    async def hide_loading_indicator(self):
        """スピナーを安全に削除"""
        try:
            spinner = getattr(self, "spinner", None)
            if spinner is not None and spinner.parent:
                spinner.remove()
                await self.refresh()
        except Exception:
            pass

    def scroll_to_first_hit_center(self, body_text: str, header_line_count: int, terms: set[str]):
        """本文中の最初のヒット行が画面中央に来るようスクロール（折返し考慮）"""
        if not body_text or not terms:
            return

        from rich.console import Console
        from rich.cells import cell_len
        from rich.text import Text as RichText

        # 画面幅（セル幅）を取得。paddingぶん少し引いて安全側に
        width = max(10, (self.article_scroll.size.width or 0) - 2)
        console = Console(width=width, record=False)

        # 最初に出てくるマッチ位置（文字index）を探す
        first_pos = None
        first_term = None
        for term in terms:
            if not term:
                continue
            for t0 in {term, normalize_num(term)}:
                m = re.search(re.escape(t0), body_text)
                if m:
                    pos = m.start()
                    if first_pos is None or pos < first_pos:
                        first_pos = pos
                        first_term = t0

        if first_pos is None:
            return

        prefix_text = body_text[:first_pos]
        match_line_idx = prefix_text.count("\n")
        col_text = prefix_text.split("\n")[-1]  # マッチ行内での位置（文字列）
        lines = body_text.splitlines()

        # 1) マッチ行より上の「実表示行数（折返し後）」を合算
        visual_before = 0
        for l in lines[:match_line_idx]:
            visual_before += len(RichText(l).wrap(console, width))

        # 2) マッチ行内でも、折返しのどの段にいるか算出
        wrapped_match = RichText(lines[match_line_idx] if match_line_idx < len(lines) else "").wrap(console, width)
        col_cells = cell_len(col_text)
        acc = 0
        sub_offset = 0
        for i, wline in enumerate(wrapped_match):
            acc += cell_len(wline.plain)
            if acc > col_cells:
                sub_offset = i
                break

        target_visual_line = header_line_count + visual_before + sub_offset

        viewport_h = max(1, self.article_scroll.size.height)
        target_y = max(0, target_visual_line - viewport_h // 2)

        self.article_scroll.scroll_to(y=target_y, animate=True, force=True)

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

    async def on_input_submitted(self, event: Input.Submitted):
        q = event.value.strip()
        self.result_list.clear()
        self.article_body.update("ここに本文が表示されます")
        self.index_map.clear()
        self.display_entries = []

        if not q:
            self.result_list.append(ListItem(Static("❗ キーワードを入力してください")))
            self.set_focus(self.result_list)
            return

        await self._perform_search(q)

    async def _perform_search(self, q: str):
        if self.root_main is None or self.root_order is None:
            await self.show_loading_indicator()
            try:
                today = date.today().strftime("%Y-%m-%d")
                self.root_main = await asyncio.to_thread(safe_fetch, LAW_MAIN_ID, today)
                self.root_order = await asyncio.to_thread(safe_fetch, LAW_ORDER_ID, today)
            except Exception:
                self.result_list.append(ListItem(Static("データ取得に失敗しました")))
                self.notify_safe("データ取得に失敗しました", severity="error")
                self.set_focus(self.result_list)
                await self.hide_loading_indicator()
                return

            if any(root is None or getattr(root, "tag", "") == "Root" for root in (self.root_main, self.root_order)):
                self.result_list.append(ListItem(Static("データ取得に失敗しました")))
                self.notify_safe("データ取得に失敗しました", severity="error")
                self.set_focus(self.result_list)
                await self.hide_loading_indicator()
                return
            await self.hide_loading_indicator()

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
        if not buckets["条番号一致"]["法"] and not buckets["条番号一致"]["令"]:
            self.result_list.append(ListItem(Static("該当なし")))
        else:
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
        elif event.button.id == "single_results_copy":
            self.action_single_results_copy()

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

        # ヘッダの行数を数える（本文検索は rendered のみ）
        header_block = ("\n".join(header_lines) + "\n\n") if header_lines else ""
        header_line_count = header_block.count("\n")

        # レイアウト確定後にスクロール
        self.call_after_refresh(
            lambda: self.scroll_to_first_hit_center(rendered, header_line_count, highlight_terms)
        )

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

    def action_single_results_copy(self):
        """
        選択中の1条文だけを JSON形式でクリップボードにコピーする。
        全件コピーではなく、現在 result_list で選択されている entry のみを対象とする。
        """
        try:
            selected = self.result_list.index
            if selected is None:
                self.notify_safe("コピーする条文が選択されていません", severity="warning")
                return

            item = self.result_list.children[selected]
            if not hasattr(item, "id") or item.id not in self.index_map:
                self.notify_safe("条文が選択されていません", severity="warning")
                return

            entry = self.index_map[item.id]

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

            import json
            import pyperclip

            json_text = json.dumps(cleaned, ensure_ascii=False, indent=2)
            pyperclip.copy(json_text)

            self.notify_safe("📋 Selected result copied (JSON)", severity="information")

        except Exception as e:
            self.notify_safe(f"コピー失敗: {e}", severity="error")

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

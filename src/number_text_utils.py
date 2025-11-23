import re

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

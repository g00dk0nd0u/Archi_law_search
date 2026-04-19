"""XML要素から本文文字列を取り出して表示用に整える共通関数。"""

import xml.etree.ElementTree as ET


def get_text(elem: ET.Element):
    parts = []
    if elem.text:
        parts.append(elem.text)
    for e in elem:
        parts.append(get_text(e))
        if e.tail:
            parts.append(e.tail)
    return "".join(parts)


def clean_text_display(t: str) -> str:
    return t.replace("\n", "").replace("縲", "").strip()

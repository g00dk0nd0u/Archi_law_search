"""Settings UI と初期取込で使う法令マスタ一覧。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LawDefinition:
    law_name: str
    law_id: str
    default_enabled: bool = False


LAW_REGISTRY = [
    LawDefinition("建築基準法", "325AC0000000201", default_enabled=True),
    LawDefinition("建築基準法施行令", "325CO0000000338", default_enabled=True),
    LawDefinition("建築士法", "325AC1000000202", default_enabled=True),
    LawDefinition("建設業法", "324AC0000000100"),
    LawDefinition("高齢者、障害者等の移動等の円滑化の促進に関する法律", "418AC0000000091"),
    LawDefinition("高齢者、障害者等の移動等の円滑化の促進に関する法律施行令", "418CO0000000379"),
    LawDefinition("建築物の耐震改修の促進に関する法律", "407AC0000000123"),
    LawDefinition("住宅の品質確保の促進等に関する法律", "411AC0000000081"),
    LawDefinition("特定住宅瑕疵担保責任の履行の確保等に関する法律", "419AC0000000066"),
    LawDefinition("長期優良住宅の普及の促進に関する法律", "420AC0000000087"),
    LawDefinition("都市計画法", "343AC0000000100"),
    LawDefinition("駐車場法", "332AC0000000106"),
    LawDefinition("景観法", "416AC0000000110"),
    LawDefinition("都市緑地法", "348AC0000000072"),
    LawDefinition("宅地造成及び特定盛土等規制法", "336AC0000000191"),
    LawDefinition("土地区画整理法", "329AC0000000119"),
    LawDefinition("都市再開発法", "344AC0000000038"),
    LawDefinition("消防法", "323AC1000000186"),
    LawDefinition("消防法施行令", "336CO0000000037"),
    LawDefinition("建築物のエネルギー消費性能の向上等に関する法律", "427AC0000000053"),
    LawDefinition("建築物における衛生的環境の確保に関する法律", "345AC1000000020"),
    LawDefinition("浄化槽法", "358AC1000000043"),
    LawDefinition("下水道法", "333AC0000000079"),
    LawDefinition("水道法", "332AC0000000177"),
    LawDefinition("建設工事に係る資材の再資源化等に関する法律", "412AC0000000104"),
    LawDefinition("建物の区分所有等に関する法律", "337AC0000000069"),
    LawDefinition("労働安全衛生法", "347AC0000000057"),
    LawDefinition("不動産登記法", "416AC0000000123"),
]

LAW_BY_ID = {law.law_id: law for law in LAW_REGISTRY}
DEFAULT_LAWS = [law for law in LAW_REGISTRY if law.default_enabled]

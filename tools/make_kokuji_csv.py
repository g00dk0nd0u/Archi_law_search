#!/usr/bin/env python3
"""Create accepted kokuji CSV rows from the source workbook using only stdlib."""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_XLSX = REPO_ROOT / "data" / "001992597.xlsx"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "data" / "accepted_kokuji_notices.csv"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": NS_MAIN, "r": NS_REL, "pr": NS_PACKAGE_REL}

TARGET_COLUMNS = ("A", "B", "C", "D", "F")
OUTPUT_COLUMNS = ("notice_name", "document_number", "document_date", "organization", "url", "match_reason")

PRIORITY_ACCEPT_ORGANIZATION_KEYWORDS = ("建築指導課",)
PRIORITY_ACCEPT_KEYWORDS = ("身体障害者", "車いす", "車椅子", "車イス", "高齢者、身体障害者", "移動等円滑化", "バリアフリー")
PRIORITY_EXCLUDE_ORGANIZATION_KEYWORDS = ("道路局", "河川局", "航空局", "自動車局", "海事局", "港湾局", "鉄道局", "観光庁", "水資源")
STRONG_ACCEPT_KEYWORDS = (
    "建築基準法", "都市計画法", "建築士法", "建設業法", "消防法", "確認申請", "建築確認", "中間検査",
    "完了検査", "検査済証", "開発許可", "用途地域", "容積率", "建蔽率", "建ぺい率", "高さ制限", "日影",
    "防火", "耐火", "不燃", "準不燃", "内装制限", "避難", "採光", "換気", "排煙", "構造方法", "構造計算",
    "工事監理", "移動等円滑化", "バリアフリー", "住宅性能表示", "長期優良住宅", "住宅瑕疵担保",
    "耐震改修", "建築物省エネ", "宅地造成", "盛土", "景観法", "駐車場法", "都市再開発", "土地区画整理", "都市緑地",
)
BUILDING_CONTEXT_KEYWORDS = (
    "建築", "住宅", "宅地", "市街地", "都市", "都市計画", "床面積", "緑化", "広告物", "高齢者", "身体障害者",
    "エネルギー", "まちづくり", "風土", "棟", "道路", "接道", "開発道路", "道路斜線", "区画整理", "再開発", "駐車場", "避難", "防災",
)
HARD_EXCLUDE_ORGANIZATION_KEYWORDS = ("航空局", "自動車局", "海事局", "港湾局", "河川局", "鉄道局", "観光庁", "水資源", "海上保安", "道路局")
EXCLUDED_KEYWORDS = ("海上", "船員", "軌道", "新幹線", "空港", "海洋", "海岸", "暴力", "地価", "家賃", "敷金", "公営住宅", "地方住宅", "補助制度", "補助金", "貸付", "融資", "利子", "控除", "金融", "賃貸", "入居")
REVIEW_ORGANIZATION_KEYWORDS = ("住宅局", "建築指導課", "市街地建築課", "都市局")
REVIEW_DOC_NUMBER_KEYWORDS = ("国土交通省告示", "建設省告示")
REVIEW_TITLE_PATTERNS = ("を定める件", "の基準を定める件", "の構造方法を定める件", "の仕様を定める件")


def excel_column_name(cell_ref: str) -> str:
    match = re.match(r"([A-Z]+)", cell_ref or "")
    return match.group(1) if match else ""


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in root.findall("a:si", NS):
        text = "".join(node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t"))
        shared_strings.append(text)
    return shared_strings


def workbook_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets = workbook_root.find("a:sheets", NS)
    if sheets is None or not list(sheets):
        raise ValueError("No worksheets found in workbook.")
    first_sheet = list(sheets)[0]
    rel_id = first_sheet.attrib.get(f"{{{NS_REL}}}id")
    if not rel_id:
        raise ValueError("Worksheet relationship id not found.")
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels_root.findall("pr:Relationship", NS):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "")
            if target:
                return "xl/" + target.lstrip("/")
            break
    raise ValueError("Worksheet target not found from workbook relationships.")


def cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    if cell_type == "s" and value is not None and value.text:
        return shared_strings[int(value.text)]
    if cell_type == "inlineStr":
        inline = cell.find("a:is", NS)
        if inline is not None:
            return "".join(node.text or "" for node in inline.iter(f"{{{NS_MAIN}}}t"))
        return ""
    if cell_type == "str" and value is not None:
        return value.text or ""
    if value is not None and value.text is not None:
        return value.text
    return ""


def iter_sheet_rows(xlsx_path: Path) -> list[tuple[int, dict[str, str]]]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings = read_shared_strings(zf)
        sheet_path = workbook_sheet_path(zf)
        sheet_root = ET.fromstring(zf.read(sheet_path))
    sheet_data = sheet_root.find("a:sheetData", NS)
    if sheet_data is None:
        return []
    rows: list[tuple[int, dict[str, str]]] = []
    for row in sheet_data.findall("a:row", NS):
        row_number = int(row.attrib.get("r", "0"))
        values = {column: "" for column in TARGET_COLUMNS}
        for cell in row.findall("a:c", NS):
            column_name = excel_column_name(cell.attrib.get("r", ""))
            if column_name in values:
                values[column_name] = cell_text(cell, shared_strings).strip()
        rows.append((row_number, values))
    return rows


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value)


def validate_header(rows: list[tuple[int, dict[str, str]]], source_file: Path) -> None:
    header_row = next((values for row_no, values in rows if row_no == 3), None)
    if header_row is None:
        raise ValueError(f"Header row 3 not found in {source_file.name}")
    expected = {"A": "告示・通達等の名称", "B": "文書番号", "C": "文書年月日", "D": "組織名", "F": "URL"}
    for column, label in expected.items():
        actual = normalize_header(header_row.get(column, ""))
        if label not in actual:
            raise ValueError(f"Unexpected header in {source_file.name} {column}3: {header_row.get(column, '')}")


def normalize_document_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        serial = float(text)
        if serial > 0:
            base_date = datetime(1899, 12, 30)
            return (base_date + timedelta(days=serial)).date().isoformat()
    return text


def find_contains_matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def is_empty_notice_row(values: dict[str, str]) -> bool:
    return not any(values[column].strip() for column in TARGET_COLUMNS)


def build_base_record(values: dict[str, str]) -> dict[str, str]:
    return {
        "notice_name": values["A"],
        "document_number": values["B"],
        "document_date": normalize_document_date(values["C"]),
        "organization": values["D"],
        "url": values["F"],
    }


def classify_record(base_record: dict[str, str]) -> tuple[str, list[str]]:
    notice_name = base_record["notice_name"]
    document_number = base_record["document_number"]
    organization = base_record["organization"]
    target_text = f"{notice_name} {organization}"

    priority_exclude_org_reasons = [f"priority_exclude_org: {keyword}" for keyword in find_contains_matches(organization, PRIORITY_EXCLUDE_ORGANIZATION_KEYWORDS)]
    priority_accept_org_reasons = [f"priority_accept_org: {keyword}" for keyword in find_contains_matches(organization, PRIORITY_ACCEPT_ORGANIZATION_KEYWORDS)]
    priority_accept_keyword_reasons = [f"priority_accept_keyword: {keyword}" for keyword in find_contains_matches(target_text, PRIORITY_ACCEPT_KEYWORDS)]
    strong_accept_reasons = [f"strong_accept: {keyword}" for keyword in find_contains_matches(target_text, STRONG_ACCEPT_KEYWORDS)]
    building_context_reasons = [f"building_context: {keyword}" for keyword in find_contains_matches(target_text, BUILDING_CONTEXT_KEYWORDS)]
    hard_exclude_org_reasons = [f"hard_exclude_org: {keyword}" for keyword in find_contains_matches(organization, HARD_EXCLUDE_ORGANIZATION_KEYWORDS)]
    soft_exclude_reasons = [f"soft_exclude: {keyword}" for keyword in find_contains_matches(target_text, EXCLUDED_KEYWORDS)]
    review_reasons: list[str] = []
    for keyword in find_contains_matches(organization, REVIEW_ORGANIZATION_KEYWORDS):
        review_reasons.append(f"review_condition: organization={keyword}")
    for keyword in find_contains_matches(document_number, REVIEW_DOC_NUMBER_KEYWORDS):
        review_reasons.append(f"review_condition: document_number={keyword}")
    for pattern in REVIEW_TITLE_PATTERNS:
        if pattern in notice_name:
            review_reasons.append(f"review_condition: notice_name={pattern}")

    if priority_exclude_org_reasons:
        return ("excluded_notices", priority_exclude_org_reasons)
    if priority_accept_org_reasons:
        return ("accepted_notices", priority_accept_org_reasons)
    if priority_accept_keyword_reasons:
        return ("accepted_notices", priority_accept_keyword_reasons)
    if strong_accept_reasons:
        return ("accepted_notices", strong_accept_reasons)
    if hard_exclude_org_reasons:
        if building_context_reasons or strong_accept_reasons:
            return ("review_notices", [*hard_exclude_org_reasons, *building_context_reasons, *strong_accept_reasons])
        return ("excluded_notices", hard_exclude_org_reasons)
    if soft_exclude_reasons:
        if building_context_reasons:
            return ("review_notices", [*soft_exclude_reasons, *building_context_reasons])
        return ("excluded_notices", soft_exclude_reasons)
    if building_context_reasons:
        return ("review_notices", building_context_reasons)
    if review_reasons:
        return ("review_notices", review_reasons)
    return ("excluded_notices", ["no_match"])


def collect_records(xlsx_path: Path) -> tuple[list[dict[str, str]], int, int]:
    rows = iter_sheet_rows(xlsx_path)
    validate_header(rows, xlsx_path)
    accepted_records: list[dict[str, str]] = []
    review_count = 0
    excluded_count = 0
    for row_number, values in rows:
        if row_number < 4 or is_empty_notice_row(values):
            continue
        base_record = build_base_record(values)
        bucket, reasons = classify_record(base_record)
        if bucket == "accepted_notices":
            accepted_records.append({**base_record, "match_reason": " / ".join(reasons)})
        elif bucket == "review_notices":
            review_count += 1
        else:
            excluded_count += 1
    return accepted_records, review_count, excluded_count


def write_csv(output_path: Path, records: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def parse_args() -> tuple[Path, Path]:
    import argparse
    parser = argparse.ArgumentParser(description="Create data/accepted_kokuji_notices.csv from the source workbook.")
    parser.add_argument("--input-xlsx", default=str(DEFAULT_INPUT_XLSX), help="Source workbook path")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="Accepted kokuji CSV output path")
    args = parser.parse_args()
    return Path(args.input_xlsx).expanduser(), Path(args.output_csv).expanduser()


def main() -> int:
    input_xlsx, output_csv = parse_args()
    if not input_xlsx.exists():
        print("Input workbook not found.")
        print(f"Checked: {input_xlsx}")
        print("Place the source workbook at data/001992597.xlsx or pass --input-xlsx.")
        return 1
    accepted_records, review_count, excluded_count = collect_records(input_xlsx)
    write_csv(output_csv, accepted_records)
    print(f"Accepted records: {len(accepted_records)}")
    print(f"Review records: {review_count}")
    print(f"Excluded records: {excluded_count}")
    print(f"Output file: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import traceback
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LAW_MAIN_ID = "325AC0000000201"   # 建築基準法
LAW_ORDER_ID = "325CO0000000338"  # 建築基準法施行令
BASE_URL = "https://laws.e-gov.go.jp/api/2/law_data/"


def fetch_law_xml(law_id: str, as_of_date=None):
    """e-Gov法令APIから法令XMLを取得してElementTreeへ変換する。"""
    params = {"response_format": "xml"}
    if as_of_date:
        params["asof"] = as_of_date

    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{law_id}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "ArchiLawSearch/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
    return ET.fromstring(body)


def safe_fetch(law_id: str, as_of_date=None):
    """fetch_law_xmlをラップして失敗時は空ルートを返す。"""
    try:
        return fetch_law_xml(law_id, as_of_date)
    except Exception as e:
        print(f"[WARN] fetch_law_xml failed for {law_id}: {e}")
        traceback.print_exc()
        return ET.Element("Root")

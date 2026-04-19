"""e-Gov法令APIからXMLを安全に取得する通信処理をまとめる。"""

import traceback
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

LAW_MAIN_ID = "325AC0000000201"   # 建築基準法
LAW_ORDER_ID = "325CO0000000338"  # 建築基準法施行令
BASE_URL = "https://laws.e-gov.go.jp/api/2/law_data/"
DEFAULT_CA_BUNDLE_PATH = Path(__file__).resolve().parent.parent / "certs" / "cacert.pem"


def get_ca_bundle_path() -> Path:
    return DEFAULT_CA_BUNDLE_PATH


def create_ssl_context() -> ssl.SSLContext:
    ca_bundle_path = get_ca_bundle_path()
    if not ca_bundle_path.exists():
        raise FileNotFoundError(f"CA bundle not found: {ca_bundle_path}")
    return ssl.create_default_context(cafile=str(ca_bundle_path))


def fetch_law_xml(law_id: str, as_of_date=None):
    """e-Gov法令APIから法令XMLを取得してElementTreeへ変換する。"""
    params = {"response_format": "xml"}
    if as_of_date:
        params["asof"] = as_of_date

    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{law_id}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "ArchiLawSearch/1.0"})
    ssl_context = create_ssl_context()
    with urllib.request.urlopen(request, timeout=15, context=ssl_context) as response:
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

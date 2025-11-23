import traceback
import xml.etree.ElementTree as ET

import requests

LAW_MAIN_ID = "325AC0000000201"   # 蟒ｺ遽牙渕貅匁ｳ・
LAW_ORDER_ID = "325CO0000000338"  # 蟒ｺ遽牙渕貅匁ｳ墓命陦御ｻ､
BASE_URL = "https://laws.e-gov.go.jp/api/2/law_data/"


# ==== XML蜿門ｾ・====
def fetch_law_xml(law_id: str, as_of_date=None):
    params = {"response_format": "xml"}
    if as_of_date:
        params["asof"] = as_of_date
    r = requests.get(BASE_URL + law_id, params=params, timeout=15)
    r.raise_for_status()
    return ET.fromstring(r.text)


def safe_fetch(law_id: str, as_of_date=None):
    """fetch_law_xml 繧偵Λ繝・・縺励※萓句､悶ｒ蜷ｸ蜿弱ょ､ｱ謨玲凾縺ｯ遨ｺ縺ｮ繝ｫ繝ｼ繝医ｒ霑斐☆縲・"""
    try:
        return fetch_law_xml(law_id, as_of_date)
    except Exception as e:
        print(f"[WARN] fetch_law_xml failed for {law_id}: {e}")
        traceback.print_exc()
        return ET.Element("Root")

"""One-click connectivity check, run from the deployed app.

Each check makes a single plain request (no retries) and reports what came
back, so we can see from the server's own network what the sources do.
The OpenFun token is only ever reported as configured or not.
"""
import requests
from datetime import datetime, timedelta

import pytz

import scrapers.utils
from scrapers.g0vScraper import openfun_headers

PYTHON_DEFAULT_HEADERS = {"User-Agent": requests.utils.default_user_agent()}


def _get(url, headers=None, timeout=(10, 60)):
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        return r, None
    except requests.RequestException as e:
        return None, type(e).__name__


def _describe(response, error):
    if error:
        return f"連線失敗：{error}"
    return f"HTTP {response.status_code}，{len(response.content):,} bytes"


def run(config_path):
    config = scrapers.utils.load_config(config_path)
    g0v = config['websites']['g0v']['api']
    base, endpoints = g0v['base_url'], g0v['endpoints']
    headers = openfun_headers()
    results = []

    def add(check, outcome, detail=None):
        results.append({"檢查項目": check, "結果": outcome, "細節": detail or ""})

    # Server's outbound IP (what the source sites see)
    r, err = _get("https://api.ipify.org?format=json", timeout=(10, 15))
    try:
        ip = r.json().get("ip") if r is not None and r.ok else _describe(r, err)
    except ValueError:
        ip = _describe(r, err)
    add("本機對外 IP", ip)

    add("OpenFun token", "已設定" if "Authorization" in headers else "未設定（Secrets 缺 OPENFUN_TOKEN）")

    r, err = _get(base + endpoints['info'], headers=headers)
    detail = ""
    if r is not None and r.ok:
        try:
            info = r.json()
            detail = f"最新資料：{info.get('latest_date') or info}"
        except ValueError:
            detail = "回應不是 JSON"
    add("g0v getinfo", _describe(r, err), detail)

    # listbydate for yesterday (Taiwan time) — the call the scraper now relies on
    day = (datetime.now(pytz.timezone("Asia/Taipei")) - timedelta(days=1)).strftime("%Y%m%d")
    r, err = _get(f"{base}{endpoints['list_date']}date={day}", headers=headers, timeout=(10, 90))
    sample = None
    detail = ""
    if r is not None and r.ok:
        try:
            records = r.json().get("records", []) or []
            sample = records[0] if records else None
            if sample:
                detail = (f"{len(records)} 筆；欄位 {sorted(sample.keys())}；"
                          f"brief 欄位 {sorted((sample.get('brief') or {}).keys())}；"
                          f"含 detail：{'detail' in sample}")
            else:
                detail = "0 筆"
        except ValueError:
            detail = "回應不是 JSON"
    add(f"g0v listbydate {day}", _describe(r, err), detail)

    # Same detail URL with different request styles, to see which one is refused
    if sample and sample.get("tender_api_url"):
        url = sample["tender_api_url"]
        https_url = base + endpoints['tenders'] + url.split("?", 1)[-1]
        r, err = _get(url, headers=PYTHON_DEFAULT_HEADERS)
        add("g0v 明細：原網址、程式預設標頭", _describe(r, err), url)
        r, err = _get(https_url, headers=PYTHON_DEFAULT_HEADERS)
        add("g0v 明細：https、程式預設標頭", _describe(r, err))
        r, err = _get(https_url, headers=headers)
        add("g0v 明細：https、帶 token 與識別", _describe(r, err))
        browser = dict(headers, **{
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                          "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Referer": "https://openfunltd.github.io/",
            "Origin": "https://openfunltd.github.io",
        })
        r, err = _get(https_url, headers=browser)
        add("g0v 明細：https、模擬瀏覽器", _describe(r, err))

    # Direct PCC site
    pcc = config['websites']['pcc_gov']['listing_base_url']
    r, err = _get(pcc, timeout=(10, 20))
    add("政府採購網直連", _describe(r, err))

    return results

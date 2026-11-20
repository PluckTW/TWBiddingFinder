# 政府電子採購網「公開取得電子報價單」招標公告 scraper.
#
# Why: g0v (our main source) and PCC's open-data XML both lack tender notices of
# the 公開取得電子報價單 method (small purchases under the 1.5M threshold), so
# cases like 台大 1152B026 細胞成像系統 or 中興 FT-115032 多功能全波長分光光譜儀
# were invisible to us while they were open. Only the PCC website lists them.
#
# How: the 標的分類查詢 page submits its form with GET
# (proctrgTenderSearch(): window.location = action + "?" + form.serialize()),
# so one URL returns every e-quotation tender in 財物類 still open for bidding
# (dateType=isSpdt, 等標期內). Running daily therefore never misses a day.
#
# PCC blocks non-Taiwan IPs (incl. Streamlit Cloud), so this runs on a machine
# in Taiwan: see runner/README_ADMIN.md.
import re
import time
from datetime import date
from urllib.parse import urlencode, urljoin, urlsplit, parse_qsl

import requests
from bs4 import BeautifulSoup

BASE = "https://web.pcc.gov.tw"
LIST_PATH = "/prkms/tender/common/proctrg/readTenderProctrg"
PAGE_SIZE = 100
MAX_PAGES = 30
DELAY_SECONDS = 2

TENDER_WAY = "TENDER_WAY_12"            # 公開取得電子報價單
PROCTRG_CATE = "RAD_PROCTRG_CATE_2"     # 財物類

# Text of PCC's WAF page when it refuses our IP
_BLOCKED_MARKERS = ("Web Page Blocked", "The URL you requested has been blocked")
_EMPTY_MARKERS = ("查無資料", "無符合條件")


class PccBlockedError(RuntimeError):
    """PCC's firewall refused the request (usually a non-Taiwan IP)."""


class PccFormatError(RuntimeError):
    """The result page no longer looks like what the parser expects."""


def roc_today(today=None):
    d = today or date.today()
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def roc_to_int(text):
    """'115/11/19' -> 20261119, or None."""
    m = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", str(text or ""))
    if not m:
        return None
    return (int(m.group(1)) + 1911) * 10000 + int(m.group(2)) * 100 + int(m.group(3))


def list_url(today=None):
    """Same parameters the page's form sends (jQuery serialize order)."""
    day = roc_today(today)
    params = [
        ("pageSize", PAGE_SIZE),
        ("firstSearch", "false"),
        ("searchType", "tpam"),
        ("isBinding", "N"),
        ("isLogIn", "N"),
        ("level_1", "on"),                  # radio 招標 (no value attribute)
        ("tenderStatus", "TENDER_STATUS_0"),
        ("tenderWay", TENDER_WAY),
        ("radProctrgCate", PROCTRG_CATE),
        ("proctrgCode1", ""),
        ("proctrgCode2", ""),
        ("proctrgCode3", ""),
        ("dateType", "isSpdt"),             # 等標期內
        ("tenderStartDate", day),
        ("tenderEndDate", day),
    ]
    return f"{BASE}{LIST_PATH}?{urlencode(params)}"


def _cell_text(td):
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()


def parse_list(html):
    """Rows of the result table (id='tpam').

    Columns as shown on the site: 項次 | 機關名稱 | 標案案號 + 標案名稱 |
    傳輸次數 | 招標方式 | 採購性質 | 公告日期 | 截止投標 | 預算金額 | 功能選項.
    """
    if any(m in html for m in _BLOCKED_MARKERS):
        raise PccBlockedError("政府電子採購網防火牆拒絕連線（多為非台灣 IP）")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tpam")
    if table is None:
        if any(m in html for m in _EMPTY_MARKERS):
            return []
        raise PccFormatError("找不到結果表格 table#tpam，採購網頁面格式可能已改版")

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 9:
            continue            # header / empty-result row
        org = _cell_text(tds[1])
        case_cell = tds[2]
        link = case_cell.find("a") or tr.find("a", href=re.compile("pkPmsMain"))
        title = _cell_text(link) if link is not None else ""
        job = _cell_text(case_cell)
        if title and job.endswith(title):
            job = job[: -len(title)].strip()
        href = link.get("href") if link is not None else None
        detail = tr.find("a", href=re.compile("pkPmsMain"))
        url = urljoin(BASE, detail["href"]) if detail is not None else (
            urljoin(BASE, href) if href and not href.startswith(("javascript", "#")) else None)
        rows.append({
            "機關名稱": org,
            "job_number": job,
            "title": title or job,
            "傳輸次數": _cell_text(tds[3]),
            "招標方式": _cell_text(tds[4]),
            "採購性質": _cell_text(tds[5]),
            "公告日期": _cell_text(tds[6]),
            "領投開標:截止投標": _cell_text(tds[7]),
            "採購資料:預算金額": _cell_text(tds[8]),
            "url": url,
        })
    return rows


def other_page_urls(html, current_url):
    """URLs of the remaining result pages (displaytag '...-p=N' links)."""
    # Built from current_url + the page parameter, not from the link itself,
    # so a link carrying only '?d-xxx-p=N' can't drop the search parameters.
    soup = BeautifulSoup(html, "html.parser")
    page_key, last = None, 1
    for a in soup.find_all("a", href=True):
        query = dict(parse_qsl(urlsplit(a["href"]).query, keep_blank_values=True))
        for key, value in query.items():
            if key.endswith("-p") and value.isdigit():
                page_key, last = key, max(last, int(value))
    if page_key is None:
        return []
    base = re.sub(rf"&{re.escape(page_key)}=\d+", "", current_url)
    return [f"{base}&{page_key}={n}" for n in range(2, min(last, MAX_PAGES) + 1)]


def fetch(session, url):
    response = session.get(url, timeout=(10, 60))
    if response.status_code != 200 and any(m in response.text for m in _BLOCKED_MARKERS):
        raise PccBlockedError("政府電子採購網防火牆拒絕連線（多為非台灣 IP）")
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def scrape(session=None, today=None, dump_path=None):
    """Every open e-quotation tender in 財物類. Returns a list of dicts."""
    session = session or requests.Session()
    first_url = list_url(today)
    html = fetch(session, first_url)
    if dump_path:
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
    rows = parse_list(html)
    seen_pages = set()
    for url in other_page_urls(html, first_url):
        if url in seen_pages:
            continue
        seen_pages.add(url)
        time.sleep(DELAY_SECONDS)
        rows += parse_list(fetch(session, url))
    # Same tender can't appear twice; keep the first
    unique = {}
    for r in rows:
        unique.setdefault((r["機關名稱"], r["job_number"], r["傳輸次數"]), r)
    return list(unique.values())


def match_keywords(rows, keywords):
    """Rows whose title contains a keyword; adds 'keyword' (、-joined)."""
    out = []
    for r in rows:
        title = re.sub(r"\s+", "", r["title"])
        hits = [kw for kw in keywords if kw and kw in title]
        if hits:
            out.append({**r, "keyword": "、".join(hits)})
    return out

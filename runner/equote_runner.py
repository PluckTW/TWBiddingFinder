"""Daily job for the company Windows machine: fetch open 公開取得電子報價單
tenders from PCC, keep the keyword matches, and append them to the Google
Sheet tab EQuote_RAW. Every run, success or failure, adds one row to EQuoteLog
so admins only need to look at the last row.

Run:  python -m runner.equote_runner            (normal daily run)
      python -m runner.equote_runner --check    (connectivity test, writes nothing)

Settings: runner/config.json (copy from runner/config.example.json).
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scrapers import pcc_equote  # noqa: E402
from data_processing import sheets_sync  # noqa: E402
import config.configLoader as cfg  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))
RAW_TAB = "EQuote_RAW"
LOG_TAB = "EQuoteLog"
LOG_HEADERS = ["run_at", "status", "listed", "matched", "new", "message"]
COLUMNS = ["date", "title", "keyword", "job_number", "機關名稱", "領投開標:截止投標",
           "採購資料:預算金額", "招標資料:招標狀態", "採購性質", "url"]


def load_settings():
    path = os.path.join(HERE, "config.json")
    if not os.path.exists(path):
        sys.exit(f"找不到設定檔 {path}，請先複製 config.example.json 為 config.json 並填寫。")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def open_sheet(settings):
    from google.oauth2.service_account import Credentials
    import gspread
    creds = Credentials.from_service_account_file(settings["service_account_file"],
                                                  scopes=sheets_sync._SCOPES)
    return gspread.authorize(creds).open_by_key(settings["google_sheet_id"])


def make_session(settings):
    session = requests.Session()
    proxy = (settings.get("proxy") or "").strip()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def to_frame(rows):
    out = []
    for r in rows:
        out.append({
            "date": pcc_equote.roc_to_int(r["公告日期"]),
            "title": r["title"],
            "keyword": r["keyword"],
            "job_number": r["job_number"],
            "機關名稱": r["機關名稱"],
            "領投開標:截止投標": r["領投開標:截止投標"],
            "採購資料:預算金額": r["採購資料:預算金額"],
            # Dedup key with job_number: a re-tender gets a new transmission no.
            "招標資料:招標狀態": f"{r['招標方式']} 傳輸次數{r['傳輸次數']}",
            "採購性質": r["採購性質"],
            "url": r["url"] or "",
        })
    return pd.DataFrame(out, columns=COLUMNS)


def write_log(spreadsheet, status, listed=0, matched=0, new=0, message=""):
    try:
        ws = sheets_sync.ensure_headers(spreadsheet, LOG_TAB, LOG_HEADERS)
        ws.append_rows([[datetime.now(TAIPEI).isoformat(timespec="seconds"), status,
                         listed, matched, new, message[:500]]], value_input_option="RAW")
    except Exception as e:
        print(f"寫入 {LOG_TAB} 失敗：{e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="只測試連線（採購網與 Google Sheet），不寫入資料")
    args = parser.parse_args()
    settings = load_settings()
    now = datetime.now(TAIPEI)
    print(f"=== {now:%Y-%m-%d %H:%M} 電子報價單抓取 {'(連線測試)' if args.check else ''} ===")

    spreadsheet = open_sheet(settings)
    print(f"Google Sheet 連線成功：{spreadsheet.title}")

    try:
        keywords = cfg.load_keywords(spreadsheet)["title"]
    except Exception:
        keywords = cfg.TITLE_KEYWORDS

    logs = os.path.join(HERE, "logs")
    os.makedirs(logs, exist_ok=True)
    dump = os.path.join(logs, "last_list_page.html")
    try:
        rows = pcc_equote.scrape(make_session(settings), today=now.date(), dump_path=dump)
        matched = pcc_equote.match_keywords(rows, keywords)
        print(f"採購網：等標期內電子報價單（財物類）{len(rows)} 筆，關鍵字命中 {len(matched)} 筆")
        if args.check:
            for r in matched[:20]:
                print(f"  {r['公告日期']} {r['機關名稱']} {r['job_number']} {r['title']}")
            print("連線測試完成（未寫入 Google Sheet）")
            return 0
        new = sheets_sync.append_new_records(
            spreadsheet, to_frame(matched), RAW_TAB, now.strftime("%Y%m%d%H%M"),
            now.isoformat(timespec="seconds"),
            dedup_keys=["job_number", "招標資料:招標狀態"])
        print(f"寫入 {RAW_TAB}：新增 {new} 筆")
        write_log(spreadsheet, "OK", len(rows), len(matched), new)
        return 0
    except pcc_equote.PccBlockedError as e:
        msg = f"{e}。請確認這台電腦的對外 IP 在台灣，或公司 proxy 設定。"
    except pcc_equote.PccFormatError as e:
        msg = f"{e}。原始頁面已存到 {dump}，請交給維護者。"
    except requests.RequestException as e:
        msg = f"連線採購網失敗：{type(e).__name__} {e}"
    except Exception as e:
        traceback.print_exc()
        msg = f"未預期錯誤：{type(e).__name__} {e}"
    print(f"失敗：{msg}")
    if not args.check:
        write_log(spreadsheet, "FAIL", message=msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())

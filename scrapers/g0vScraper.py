import pandas as pd
import streamlit as sl
import scrapers.utils
import config.configLoader as cfg
from config.configLoader import AWARD_SELECTED_COLUMNS, TENDER_SELECTED_COLUMNS, NOT_AWARD_SELECTED_COLUMNS
from datetime import datetime, timedelta
import pytz
from urllib.parse import urlsplit, parse_qs, urlencode
import re
import time


VALID_TENDER_TYPES = ['無法決標公告', '決標公告', '公開招標公告', '公開取得報價單或企劃書公告',
                      '公開取得報價單或企劃書更正公告', '經公開評選或公開徵求之限制性招標公告']
AWARD_TYPES = ('決標公告', '無法決標公告')
VIEWER_URL = "https://openfunltd.github.io/pcc-viewer/tender.html?"


def openfun_headers():
    """Identify ourselves and send the OpenFun token (Streamlit secret
    OPENFUN_TOKEN) when configured; token holders get a higher rate limit."""
    headers = {"User-Agent": "TWBiddingFinder/1.0"}
    try:
        token = sl.secrets.get("OPENFUN_TOKEN")
    except Exception:
        token = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class G0vScraper:
    """Fetches every notice per day via listbydate (one call per day, like
    bidscan.tw) and matches keywords locally, instead of one search per
    keyword plus one detail call per hit, which got us throttled/blocked."""

    def __init__(self, start_date, config_path):
        self.config = scrapers.utils.load_config(config_path)
        endpoints = self.config['websites']['g0v']['api']['endpoints']
        self.base_url = self.config['websites']['g0v']['api']['base_url']
        self.tender_api = endpoints['tenders']
        self.date_api = endpoints['list_date']
        self.start_date = start_date
        self.headers = openfun_headers()
        self.breaker = scrapers.utils.CircuitBreaker("g0v API")
        self.warning = None  # shown on the results tab when a source failed
        self.detail_attempted = 0
        self.detail_failed = 0


    @property
    def details_broken(self):
        # Every detail call so far has failed: the endpoint itself is broken,
        # so stop paying ~2s per record for the rest of the run.
        return self.detail_attempted >= 10 and self.detail_failed == self.detail_attempted


    def detail_url(self, tender_api_url):
        # Rebuild on the configured base so all calls go to the same host/scheme.
        return f"{self.base_url}{self.tender_api}{urlsplit(tender_api_url).query}"


    def write_to_df(self, record, record_type):
        filtered_dict = {}
        for key in record_type:

            # Access the nested value if nested
            if "." in key:
                nested_keys = key.split(".")
                nested_value = record
                for nested_key in nested_keys:
                    if nested_key in nested_value:
                        nested_value = nested_value[nested_key]
                    else:
                        nested_value = None
                        break
                filtered_dict[nested_key] = nested_value
            elif key in record:
                filtered_dict[key] = record[key]

        df = pd.DataFrame([filtered_dict])
        return df


    def dates_to_fetch(self):
        # Server runs in UTC; notices are dated in Taiwan time
        today = datetime.now(pytz.timezone("Asia/Taipei")).date()
        day = datetime.strptime(str(self.start_date), "%Y%m%d").date()
        while day <= today:
            yield int(day.strftime("%Y%m%d"))
            day += timedelta(days=1)


    def list_by_date(self, date):
        api = f"{self.base_url}{self.date_api}date={date}"
        # A whole day's notices is a big response; allow it more read time.
        response = scrapers.utils.request(api, timeout=(10, 90), breaker=self.breaker,
                                          headers=self.headers)
        if response is None:
            print(f"g0v: listbydate failed for {date}, skipping.")
            return []
        try:
            return response.json().get('records', []) or []
        except ValueError as e:
            print(f"g0v: JSON parse error for {date}: {e}, skipping.")
            return []


    @staticmethod
    def match_keywords(record):
        """Keywords this notice matches: title keywords against the title,
        and for award notices dealer names against the bidding companies."""
        brief = record.get('brief') or {}
        notice_type = brief.get('type')
        if notice_type not in VALID_TENDER_TYPES:
            return []
        # g0v titles have spaces between words; keywords don't
        title = re.sub(r'\s+', '', str(brief.get('title') or ''))
        matched = []
        if notice_type in AWARD_TYPES:
            names = (brief.get('companies') or {}).get('names') or []
            matched += [kw for kw in cfg.COMPANY_KEYWORDS if any(kw in str(n) for n in names)]
        matched += [kw for kw in cfg.TITLE_KEYWORDS if kw in title]
        return matched


    def fetch_detail(self, record):
        if self.breaker.is_open or self.details_broken or not record.get('tender_api_url'):
            return None
        time.sleep(1)
        self.detail_attempted += 1
        response = scrapers.utils.request(self.detail_url(record['tender_api_url']),
                                          breaker=self.breaker, headers=self.headers)
        if response is None:
            self.detail_failed += 1
            return None
        try:
            records = response.json().get('records', []) or []
        except ValueError:
            self.detail_failed += 1
            return None
        return next((r for r in records if r.get('filename') == record.get('filename')), None)


    @staticmethod
    def listing_row(record, notice_type):
        """Row built from the listing alone, used when the detail call fails,
        so a matched notice is still reported (without contact columns)."""
        brief = record.get('brief') or {}
        query = parse_qs(urlsplit(record.get('tender_api_url') or '').query)
        unit_id = record.get('unit_id') or (query.get('unit_id') or [None])[0]
        job_number = record.get('job_number') or (query.get('job_number') or [None])[0]
        row = {
            'date': record.get('date'),
            'title': brief.get('title'),
            'job_number': job_number,
            '機關資料:機關名稱': record.get('unit_name'),
            'url': VIEWER_URL + urlencode({'unit_id': unit_id, 'job_number': job_number})
                   if unit_id and job_number else None,
        }
        if notice_type in AWARD_TYPES:
            row['type'] = notice_type
        else:
            row['category'] = brief.get('category')
            row['採購資料:標的分類'] = brief.get('category')
        return pd.DataFrame([row])


    def record_to_df(self, record):
        notice_type = (record.get('brief') or {}).get('type')
        # listbydate may already carry the full detail; only call tender if not
        full = record if record.get('detail') else self.fetch_detail(record)
        if full is None:
            return self.listing_row(record, notice_type)
        if notice_type == '決標公告':
            return self.write_to_df(full, AWARD_SELECTED_COLUMNS)
        if notice_type == '無法決標公告':
            return self.write_to_df(full, NOT_AWARD_SELECTED_COLUMNS)
        return self.write_to_df(full, TENDER_SELECTED_COLUMNS)


    def run_scraper(self):
        sl.write("g0v scraper is now running:")
        status = sl.empty()

        # 1) one listbydate call per day, match locally
        dates = list(self.dates_to_fetch())
        matches = []
        for i, date in enumerate(dates, 1):
            if self.breaker.is_open:
                break
            status.text(f"g0v: 讀取 {date} 公告（{i}/{len(dates)} 天）")
            for record in self.list_by_date(date):
                if int(record.get('date') or 0) < self.start_date:
                    continue
                keywords = self.match_keywords(record)
                if keywords:
                    matches.append((record, "、".join(keywords)))
            time.sleep(1)

        # 2) details only for the matched notices
        tender_frames, award_frames = [], []
        for i, (record, keyword) in enumerate(matches, 1):
            status.text(f"g0v: 查詢明細 {i}/{len(matches)}")
            try:
                df = self.record_to_df(record)
            except Exception as e:
                print(f"g0v: row build error for {record.get('filename')}: {e}, skipping.")
                continue
            df.insert(0, 'keyword', keyword)
            if (record.get('brief') or {}).get('type') in AWARD_TYPES:
                award_frames.append(df)
            else:
                tender_frames.append(df)

        new_tender_df = pd.concat(tender_frames, ignore_index=True) if tender_frames else pd.DataFrame()
        new_award_df = pd.concat(award_frames, ignore_index=True) if award_frames else pd.DataFrame()
        new_tender_df = new_tender_df.rename(columns={'機關資料:機關名稱': '機關名稱'})

        if self.breaker.is_open:
            msg = (f"g0v API 連續 {self.breaker.failures} 次失敗（{self.breaker.last_error}），"
                   f"已停止讀取剩餘日期")
            print(f"g0v: {msg}")
            self.warning = msg
            status.warning(msg)
        elif self.detail_attempted and self.detail_failed == self.detail_attempted:
            msg = (f"g0v 明細查詢 {self.detail_failed} 筆全部失敗，已改用列表資料"
                   f"（缺聯絡人、金額等欄位）")
            print(f"g0v: {msg}")
            self.warning = msg
            status.warning(msg)
        else:
            status.text(f"g0v: 完成，{len(dates)} 天、比對到 {len(matches)} 筆")

        ## Award table formatting

        # Define the column pairs for combination
        column_pairs = [
            ('機關名稱', '機關資料:機關名稱', '無法決標公告:機關名稱'),
            ('單位名稱', '機關資料:單位名稱', '無法決標公告:單位名稱'),
            ('聯絡人', '機關資料:聯絡人', '無法決標公告:聯絡人'),
            ('聯絡電話', '機關資料:聯絡電話', '無法決標公告:聯絡電話'),
            ('電子郵件信箱', '機關資料:電子郵件信箱', '無法決標公告:電子郵件信箱'),
            ('傳真號碼', '機關資料:傳真號碼', '無法決標公告:傳真號碼'),
            ('標的分類', '採購資料:標的分類', '無法決標公告:標的分類')
        ]

        for new_col, col1, col2 in column_pairs:
            if col1 in new_award_df.columns and col2 in new_award_df.columns:
                new_award_df[new_col] = new_award_df[col1].combine_first(new_award_df[col2])
            elif col1 in new_award_df.columns:
                new_award_df[new_col] = new_award_df[col1]
            elif col2 in new_award_df.columns:
                new_award_df[new_col] = new_award_df[col2]

        # Check for '已公告資料:標的分類' separately since it is only used in the last step
        if '已公告資料:標的分類' in new_award_df.columns:
            new_award_df['標的分類'] = new_award_df['標的分類'].combine_first(new_award_df['已公告資料:標的分類'])

        # Drop only the columns that exist in the DataFrame
        columns_to_drop = ['機關資料:機關名稱', '無法決標公告:機關名稱', '機關資料:單位名稱', '無法決標公告:單位名稱',
                        '機關資料:聯絡人', '無法決標公告:聯絡人', '機關資料:聯絡電話', '無法決標公告:聯絡電話',
                        '機關資料:電子郵件信箱', '無法決標公告:電子郵件信箱', '機關資料:傳真號碼',
                        '無法決標公告:傳真號碼', '採購資料:標的分類', '已公告資料:標的分類', '無法決標公告:標的分類']

        # Use set intersection to find only columns that exist in the DataFrame
        existing_columns_to_drop = [col for col in columns_to_drop if col in new_award_df.columns]

        # Drop the existing columns
        new_award_df.drop(existing_columns_to_drop, axis=1, inplace=True)


        # New tender標的分類
        values_to_keep = ['財物類352-醫藥產品', '財物類481-醫療,外科及矯形設備', '財物類482-做為測量、檢查、航行及其他目的用之儀器和裝置，除光學儀器;工業程序控制設備;上述各項之零件及附件', '財物類483-光學儀器,攝影設備及其零件與附件', '財物類449-其他特殊用途之機具及其零件']

        if '採購資料:標的分類' in new_tender_df.columns:
            category = new_tender_df['採購資料:標的分類']
            new_tender_df = new_tender_df[category.isna() | category.isin(values_to_keep)]

        return new_tender_df, new_award_df

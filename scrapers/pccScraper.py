import streamlit as sl
import pandas as pd
import re
import scrapers.utils
from bs4 import BeautifulSoup
from config.configLoader import TITLE_KEYWORDS, COMPANY_KEYWORDS, AWARD_SELECTED_COLUMNS, TENDER_SELECTED_COLUMNS, NOT_AWARD_SELECTED_COLUMNS


class PccScraper:
    def __init__(self, start_date, config_path):
        self.config = scrapers.utils.load_config(config_path)
        self.base_url = self.config['websites']['pcc_gov']['baseUrl']
        self.listing_base_url = self.config['websites']['pcc_gov']['listing_base_url']
        self.start_date = start_date
        self.search_year_minguo = (start_date//10000)-1911

    def _parse_award_rows(self, tbody):
        """Extract award/no-award rows from a <tbody>. Returns (names already parsed
        upstream, organizations, job_numbers, hyperlinks, dates, types)."""
        organizations, job_numbers, hyperlinks, award_dates, award_types = [], [], [], [], []
        tds = tbody.find_all("td")
        i = 0
        for td in tds:
            try:
                if i % 10 == 2:
                    organizations.append(td.get_text(strip=True))
                elif i % 10 == 3:
                    a_tag = td.find('a')
                    if a_tag is None:
                        # malformed row — pad all lists so lengths stay aligned
                        hyperlinks.append(None)
                        job_numbers.append(td.get_text(strip=True))
                    else:
                        hyperlinks.append(self.base_url + a_tag['href'])
                        job_numbers.append(td.get_text(strip=True))
                elif i % 10 == 5:
                    td_date = td.get_text(strip=True)
                    m = re.search(r'\d+/\d+/\d+', td_date)
                    if m:
                        roc_year, month, day = m.group().split('/')
                        award_dates.append(str(int(roc_year) + 1911) + month + day)
                    else:
                        award_dates.append(None)
                    award_types.append('無法決標公告' if td.find('span') else '決標公告')
            except Exception as e:
                print(f"PCC row parse error at cell {i}: {e}")
            i += 1
        return organizations, job_numbers, hyperlinks, award_dates, award_types

    def _parse_tender_rows(self, tbody):
        organizations, job_numbers, hyperlinks, tender_dates, award_dates = [], [], [], [], []
        tds = tbody.find_all("td")
        i = 0
        for td in tds:
            try:
                if i % 10 == 2:
                    organizations.append(td.get_text(strip=True))
                elif i % 10 == 3:
                    a_tag = td.find('a')
                    if a_tag is None:
                        hyperlinks.append(None)
                        job_numbers.append(td.get_text(strip=True))
                    else:
                        hyperlinks.append(self.base_url + a_tag['href'])
                        job_numbers.append(td.get_text(strip=True))
                elif i % 10 == 4:
                    date = td.get_text(strip=True)
                    parts = date.split('/')
                    if len(parts) == 3:
                        tender_dates.append(str(int(parts[0]) + 1911) + parts[1] + parts[2])
                    else:
                        tender_dates.append(None)
                elif i % 10 == 6:
                    award_dates.append(td.get_text(strip=True))
            except Exception as e:
                print(f"PCC tender row parse error at cell {i}: {e}")
            i += 1
        return organizations, job_numbers, hyperlinks, tender_dates, award_dates

    def _fetch_award_df(self, query_strings, keyword, award_names):
        """Fetch one award search page and return a DataFrame (empty on failure)."""
        response = scrapers.utils.request(self.listing_base_url + query_strings)
        if response is None:
            print(f"PCC: request failed for award keyword '{keyword}', skipping.")
            return pd.DataFrame()
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        tbody = soup.find("tbody")
        if tbody is None:
            return pd.DataFrame()
        # award_names come from the regex on the same html; re-extract here to stay in sync
        names = re.findall(r'Geps3\.CNS\.pageCode2Img\("([^"]*)"\)', html)
        orgs, job_nums, links, dates, types = self._parse_award_rows(tbody)
        min_len = min(len(names), len(orgs), len(job_nums), len(links), len(dates), len(types))
        if min_len == 0:
            return pd.DataFrame()
        df = pd.DataFrame({
            'date': dates[:min_len],
            'title': names[:min_len],
            'keyword': keyword,
            'type': types[:min_len],
            'job_number': job_nums[:min_len],
            '機關名稱': orgs[:min_len],
            'url': links[:min_len],
        })
        df['date'] = pd.to_numeric(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])
        df['date'] = df['date'].astype(int)
        return df[df['date'] >= self.start_date]

    def run_scraper(self):
        sl.write("pcc scraper is now running:")

        gov_tender = pd.DataFrame()
        gov_award = pd.DataFrame()
        keyword_placeholder = sl.empty()

        for keyword in TITLE_KEYWORDS:
            keyword_placeholder.text(f"Processing keyword: {keyword}")

            # ── Tender ──────────────────────────────────────────────────────
            try:
                tqs = ("?querySentence=" + keyword
                       + "&tenderStatusType=%E6%8B%9B%E6%A8%99"
                       + "&sortCol=TENDER_NOTICE_DATE"
                       + "&timeRange=" + str(self.search_year_minguo)
                       + "&pageSize=100")
                response = scrapers.utils.request(self.listing_base_url + tqs)
                if response is None:
                    print(f"PCC: tender request failed for '{keyword}', skipping.")
                else:
                    html = response.text
                    soup = BeautifulSoup(html, "html.parser")
                    tbody = soup.find("tbody")
                    if tbody is not None:
                        tender_names = re.findall(r'Geps3\.CNS\.pageCode2Img\("([^"]*)"\)', html)
                        orgs, job_nums, links, t_dates, a_dates = self._parse_tender_rows(tbody)
                        min_len = min(len(tender_names), len(orgs), len(job_nums),
                                      len(links), len(t_dates), len(a_dates))
                        if min_len > 0:
                            raw = pd.DataFrame({
                                'date': t_dates[:min_len],
                                'title': tender_names[:min_len],
                                'keyword': keyword,
                                'job_number': job_nums[:min_len],
                                '機關名稱': orgs[:min_len],
                                '領投開標:截止投標': a_dates[:min_len],
                                'url': links[:min_len],
                            })
                            raw['date'] = pd.to_numeric(raw['date'], errors='coerce')
                            raw = raw.dropna(subset=['date'])
                            raw['date'] = raw['date'].astype(int)
                            gov_tender = pd.concat(
                                [gov_tender, raw[raw['date'] >= self.start_date]],
                                ignore_index=True)
            except Exception as e:
                print(f"PCC scraper error (tender, keyword='{keyword}'): {e}")

            # ── Award ────────────────────────────────────────────────────────
            try:
                aqs = ("?querySentence=" + keyword
                       + "&tenderStatusType=%E6%B1%BA%E6%A8%99"
                       + "&sortCol=AWARD_NOTICE_DATE"
                       + "&timeRange=" + str(self.search_year_minguo)
                       + "&pageSize=100")
                df2 = self._fetch_award_df(aqs, keyword, [])
                gov_award = pd.concat([gov_award, df2], ignore_index=True)
            except Exception as e:
                print(f"PCC scraper error (award, keyword='{keyword}'): {e}")

        # ── Company keywords (awards only) ───────────────────────────────────
        for keyword in COMPANY_KEYWORDS:
            keyword_placeholder.text(f"Processing keyword: {keyword}")
            try:
                aqs = ("?querySentence=" + keyword
                       + "&tenderStatusType=%E6%B1%BA%E6%A8%99"
                       + "&sortCol=AWARD_NOTICE_DATE"
                       + "&timeRange=" + str(self.search_year_minguo)
                       + "&pageSize=100")
                df2 = self._fetch_award_df(aqs, keyword, [])
                gov_award = pd.concat([gov_award, df2], ignore_index=True)
            except Exception as e:
                print(f"PCC scraper error (company award, keyword='{keyword}'): {e}")

        return gov_tender, gov_award

import pandas as pd
import streamlit as sl
import scrapers.utils
from config.configLoader import TITLE_KEYWORDS, COMPANY_KEYWORDS, AWARD_SELECTED_COLUMNS, TENDER_SELECTED_COLUMNS, NOT_AWARD_SELECTED_COLUMNS
from urllib.parse import quote
import time



class G0vScraper:
    def __init__(self, start_date, config_path):
        self.config = scrapers.utils.load_config(config_path)
        self.base_url = self.config['websites']['g0v']['api']['base_url']
        self.title_api = self.config['websites']['g0v']['api']['endpoints']['search_title']
        self.company_api = self.config['websites']['g0v']['api']['endpoints']['search_company']
        self.start_date = start_date


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


    def search_listings(self, keyword, keyword_type):
        full_records = pd.DataFrame()
        endpoint = keyword_type
        query = quote(f'{keyword}')
        page = 1

        api = f'{self.base_url}{endpoint}query={query}&page={page}'
        json_data = scrapers.utils.request(api).json()

        records = json_data.get('records', [])
        if not records:
            return full_records
        raw_records_df = pd.DataFrame(records)
        records_df = raw_records_df[['date', 'filename', 'brief', 'tender_api_url']]
        filtered_df = records_df[records_df['date'] >= self.start_date]
        full_records = pd.concat([full_records, filtered_df], ignore_index=True)
        # next page
        while len(filtered_df) == 100:
            page += 1
            api = f'{self.base_url}{endpoint}query={query}&page={page}'
            json_data = scrapers.utils.request(api).json()
            records = json_data.get('records', [])
            if not records:
                break
            raw_records_df = pd.DataFrame(records)
            records_df = raw_records_df[['date', 'filename', 'brief', 'tender_api_url']]
            filtered_df = records_df[records_df['date'] >= self.start_date]
            full_records = pd.concat([full_records, filtered_df], ignore_index=True)

        full_records['tender_type'] = full_records['brief'].apply(lambda x: x['type'])
        del full_records['brief']
        valid_tender_types = ['無法決標公告', '決標公告', '公開招標公告','公開取得報價單或企劃書公告','公開取得報價單或企劃書更正公告','經公開評選或公開徵求之限制性招標公告']
        full_records = full_records[full_records['tender_type'].isin(valid_tender_types)]

        return full_records
    

    def scrape_details(self, record_df):
        tenders_df = pd.DataFrame()
        awards_df = pd.DataFrame()

        for index, row in record_df.iterrows():
            time.sleep(1)
            api_url = row['tender_api_url']
            filename = row['filename']
            json_data = scrapers.utils.request(api_url).json()

            # find matching record with filename
            records = json_data.get('records', [])
            matching_record = next((record for record in records if record.get('filename', '') == filename), None)

            if row['tender_type'] == '決標公告':
                award_df = self.write_to_df(matching_record, AWARD_SELECTED_COLUMNS)
                awards_df = pd.concat([awards_df, award_df], ignore_index=True)

            elif row['tender_type'] == '無法決標公告':
                award_df = self.write_to_df(matching_record, NOT_AWARD_SELECTED_COLUMNS)
                awards_df = pd.concat([awards_df, award_df], ignore_index=True)

            else:
                tender_df = self.write_to_df(matching_record, TENDER_SELECTED_COLUMNS)
                tenders_df = pd.concat([tenders_df, tender_df], ignore_index=True)

        return tenders_df, awards_df
    

    def run_scraper(self):
        sl.write("g0v scraper is now running:")

        new_tender_df = pd.DataFrame()
        new_award_df = pd.DataFrame()

        keyword_placeholder = sl.empty()

        # search with title
        for keyword in TITLE_KEYWORDS:
            keyword_placeholder.text(f"Processing keyword: {keyword}")


            title_search_df = self.search_listings(keyword, self.title_api)
            tender_df, award_df = self.scrape_details(title_search_df)

            tender_df.insert(0, 'keyword', keyword)
            award_df.insert(0, 'keyword', keyword)
            new_tender_df = pd.concat([new_tender_df, tender_df], ignore_index=True)
            new_award_df = pd.concat([new_award_df, award_df], ignore_index=True)

        new_tender_df = new_tender_df.rename(columns={'機關資料:機關名稱': '機關名稱'})

        # search with company
        for keyword in COMPANY_KEYWORDS:
            keyword_placeholder.text(f"Processing keyword: {keyword}")

            company_search_df = self.search_listings(keyword, self.company_api)
            tender_df, award_df = self.scrape_details(company_search_df)
            tender_df.insert(0, 'keyword', keyword)
            award_df.insert(0, 'keyword', keyword)
            new_tender_df = pd.concat([new_tender_df, tender_df], ignore_index=True)
            new_award_df = pd.concat([new_award_df, award_df], ignore_index=True)


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
            new_tender_df = new_tender_df.drop(new_tender_df.index[~new_tender_df['採購資料:標的分類'].isin(values_to_keep)])

        return new_tender_df, new_award_df

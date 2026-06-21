import streamlit as sl
import os
import json
import pytz
from data_processing.data_cleaner import delete_duplicates
from data_processing.data_exporter import save_dataframes_as_csv

from datetime import datetime
from scrapers.g0vScraper import G0vScraper
from scrapers.pccScraper import PccScraper
from data_processing.pcc_g0v_merger import PccG0vMerger
from config.configLoader import CONFIG_PATH
from model.text_classification import gpt_classification



# Streamlit configuration
sl.set_page_config(page_title="標案下載", page_icon='🐄')
utc_time = datetime.now(pytz.utc)
taiwan_time = utc_time.astimezone(pytz.timezone('Asia/Taipei'))
today_date = taiwan_time.date()
#today_date = datetime.today().strftime('%Y-%m-%d')
ai_threshold = 70

# Load configuration, keywords
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)
sl.session_state["title_keywords"] = config['keywords']['by_title']
sl.session_state["company_keywords"] = config['keywords']['by_company']


# Set new session state
if 'scraping_status' not in sl.session_state:
    tenders_df = None
    awards_df = None
    sl.session_state['tender'] = None
    sl.session_state['award'] = None
    sl.session_state['scraping_status'] = 'idle'
    

    

# UI 1
if sl.session_state['scraping_status'] == 'idle':

    # Title
    sl.markdown("<h1 style='text-align: center;'>Moldev相關標案下載</h1>", unsafe_allow_html=True)
    sl.markdown("---")


    # Preview Keywords
    tk_str = ", ".join(sl.session_state["title_keywords"])
    ck_str = ", ".join(sl.session_state["company_keywords"])

    sl.write(f"Current date: {today_date}")
    #sl.write(today_date)
    #sl.write(datetime.now().date())
    sl.write(f"### Title Keywords: \n{tk_str}")
    sl.write(f"### Company Keywords: \n{ck_str}")

    # Form
    with sl.form("設定"):
        start_date = sl.date_input("開始日期", value=None)
        sl.write(f"AI選擇相關標案 (threshold={ai_threshold})")
        s_state = sl.form_submit_button("完成設定")



    # Submitted
    if s_state:
        # Invalid date
        if start_date is None or start_date > today_date:
            sl.warning("請輸入有效開始日期！")


        else:
            formatted_date = int(start_date.strftime("%Y%m%d"))

            # Run the scrapers and merger
            g0vScraper = G0vScraper(formatted_date, CONFIG_PATH)
            g0vTenderDf, g0vAwardDf = g0vScraper.run_scraper()

            pccScraper = PccScraper(formatted_date, CONFIG_PATH)
            pccTenderDf, pccAwardDf = pccScraper.run_scraper()

            scrapeDataMerger = PccG0vMerger(pccTenderDf, pccAwardDf, g0vTenderDf, g0vAwardDf)
            tenders_df, awards_df = scrapeDataMerger.run_merger()

            # Clean duplicates
            delete_duplicates(tenders_df, awards_df)

            # Add AI score
            sl.write("Calculating Relevance...")
            tender_score = tenders_df['title'].apply(gpt_classification)
            award_score = awards_df['title'].apply(gpt_classification)

            tenders_df.insert(0, 'score', tender_score)
            awards_df.insert(0, 'score', award_score)

            if tenders_df['score'].isna().all() and awards_df['score'].isna().all():
                sl.warning("⚠️ AI 評分全部失敗（API 連線或金鑰問題），score 欄位將顯示為空，篩選功能暫時無效。")

            tenders_df['score'] = tenders_df['score'].fillna(-1).astype(int)
            awards_df['score'] = awards_df['score'].fillna(-1).astype(int)



            # If scraped not empty -> Preview, Download
            if tenders_df is not None and awards_df is not None:
                sl.session_state['tender'] = tenders_df
                sl.session_state['award'] = awards_df
                sl.session_state['scraping_status'] = 'done'
                sl.session_state['ai_threshold'] = ai_threshold
                sl.rerun()


            # If scraped empty -> Warning
            else:
                sl.warning("No data available")
                sl.session_state['scraping_status'] = 'done'
                sl.rerun()


# UI 2
else:
    # Title
    sl.markdown("<h2 style='text-align: center;'>Moldev相關標案下載</h2>", unsafe_allow_html=True)
    
    # Function to toggle preview visibility
    def toggle_preview():
        # Toggle the state of the preview flag in session state
        sl.session_state['preview_open'] = not sl.session_state.get('preview_open', False)
    
    # Function to convert DataFrame to CSV
    def convert_df_to_csv(df):
        return df.to_csv(index=False).encode('utf-8-sig')
    
    # Preview and download button
    if 'tender' in sl.session_state and 'award' in sl.session_state:

        # Remove irrelevant
        ai_filered_tenders_df = sl.session_state['tender'][sl.session_state['tender']['score'] >= sl.session_state['ai_threshold']]
        ai_filtered_awards_df = sl.session_state['award'][sl.session_state['award']['score'] >= sl.session_state['ai_threshold']]


        tender_csv = convert_df_to_csv(ai_filered_tenders_df)
        award_csv = convert_df_to_csv(ai_filtered_awards_df)
        full_tender_csv = convert_df_to_csv(sl.session_state['tender'])
        full_award_csv = convert_df_to_csv(sl.session_state['award'])

        # Download buttons for tender and award data
        filtered_tender_filename = f"{today_date}_filtered_tender_data.csv"
        sl.download_button(
            label="下載招標資料 CSV",
            data=tender_csv,
            file_name=filtered_tender_filename,
            mime="text/csv"
        )
        filtered_award_filename = f"{today_date}_filtered_award_data.csv"
        sl.download_button(
            label="下載招標資料 CSV",
            data=award_csv,
            file_name=filtered_award_filename,
            mime="text/csv"
        )
        tender_filename = f"{today_date}_tender_data.csv"
        sl.download_button(
            label="下載完整關鍵字招標資料 CSV",
            data=full_tender_csv,
            file_name=tender_filename,
            mime="text/csv"
        )
        award_filename = f"{today_date}_award_data.csv"
        sl.download_button(
            label="下載完整關鍵字決標資料 CSV",
            data=full_award_csv,
            file_name=award_filename,
            mime="text/csv"
        )
    else:
        sl.warning("No data to download.")

    preview_btn = sl.button("預覽", on_click=toggle_preview)

    # Show preview if preview_open is True
    if 'preview_open' in sl.session_state and sl.session_state['preview_open']:
        if 'tender' in sl.session_state and 'award' in sl.session_state:
            sl.write('招標資料')
            sl.write(sl.session_state['tender'])
            sl.write('決標資料')
            sl.write(sl.session_state['award'])
        else:
            sl.warning("No data to preview.")


    def reset_state():
        # Clear session state (removes all session data)
        sl.session_state.clear()

        sl.rerun()  # Forces a rerun, showing the initial form

        # Reset button
    sl.button("重置", on_click=reset_state)

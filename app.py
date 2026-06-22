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
from model.text_classification import score_titles, get_last_provider, get_diagnostics



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

            # Add AI score (batch scoring with automatic model fallback)
            sl.write("Calculating Relevance...")

            # ── Debug: inspect titles before scoring ──────────────────────
            tender_titles = tenders_df['title'].tolist() if 'title' in tenders_df.columns else []
            award_titles  = awards_df['title'].tolist()  if 'title' in awards_df.columns  else []
            valid_tender = [t for t in tender_titles if isinstance(t, str) and t.strip()]
            valid_award  = [t for t in award_titles  if isinstance(t, str) and t.strip()]
            sl.write(f"🔍 待評分：招標 {len(valid_tender)}/{len(tender_titles)} 筆有效；"
                     f"決標 {len(valid_award)}/{len(award_titles)} 筆有效")
            if valid_tender:
                sl.write("招標 title 範例：" + " | ".join(valid_tender[:3]))
            if valid_award:
                sl.write("決標 title 範例：" + " | ".join(valid_award[:3]))
            # ─────────────────────────────────────────────────────────────

            tender_score = score_titles(tender_titles)
            award_score  = score_titles(award_titles)

            tenders_df.insert(0, 'score', tender_score)
            awards_df.insert(0, 'score', award_score)

            # Persist scoring outcome so it survives the rerun() into UI 2.
            if tenders_df['score'].isna().all() and awards_df['score'].isna().all():
                sl.session_state['score_failed'] = True
                sl.session_state['score_diag'] = get_diagnostics()
                sl.session_state['score_provider'] = None
            else:
                sl.session_state['score_failed'] = False
                sl.session_state['score_diag'] = None
                sl.session_state['score_provider'] = get_last_provider()

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

    # Show AI scoring outcome (persisted from the scraping run so it survives rerun).
    if sl.session_state.get('score_failed'):
        sl.warning("⚠️ AI 評分全部失敗（所有模型 API 連線或金鑰問題），score 欄位顯示為 -1，篩選功能暫時無效。")
        diag = sl.session_state.get('score_diag') or {}
        if diag.get("configured"):
            sl.write(f"已設定金鑰的模型：{', '.join(diag['configured'])}")
        if diag.get("missing"):
            sl.write(f"未設定金鑰的模型：{', '.join(diag['missing'])}")
        if diag.get("errors"):
            sl.error("實際錯誤訊息：\n" + "\n".join(f"- {e}" for e in diag["errors"]))
        else:
            sl.info("沒有捕捉到 API 錯誤；請確認 Streamlit secrets 內的金鑰名稱為 "
                    "OPENAI_API_KEY / GEMINI_API_KEY / GROQ_API_KEY，且帳戶有額度。")
    elif sl.session_state.get('score_provider'):
        sl.write(f"✅ 評分模型：{sl.session_state['score_provider']}")

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

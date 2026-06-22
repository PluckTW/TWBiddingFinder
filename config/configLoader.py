import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")



with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# Keywords
TITLE_KEYWORDS = config['keywords']['by_title']
COMPANY_KEYWORDS = config['keywords']['by_company']

# Search Methods, might delete
API_BASE_URL = config['websites']['g0v']['api']['base_url']
API_BY_TITLE = config['websites']['g0v']['api']['endpoints']['search_title']
API_BY_COMPANY = config['websites']['g0v']['api']['endpoints']['search_company']

# Record Methods
TENDER_SELECTED_COLUMNS = config["data_to_collect"]["pcc_gov"]["tender_columns"]
AWARD_SELECTED_COLUMNS = config["data_to_collect"]["pcc_gov"]["award_columns"]
NOT_AWARD_SELECTED_COLUMNS = config["data_to_collect"]["pcc_gov"]["not_award_columns"]

_CONFIG_KEYWORDS = {
    "title": config['keywords']['by_title'],
    "company": config['keywords']['by_company'],
}


def load_keywords(sheets_spreadsheet=None):
    """Return {"title": [...], "company": [...]} from the best available source.

    Priority: Google Sheets Keywords tab → config.json fallback.
    If sheets_spreadsheet is None the config.json values are returned directly.
    """
    if sheets_spreadsheet is None:
        return dict(_CONFIG_KEYWORDS)

    try:
        from data_processing.sheets_sync import load_keywords_from_sheet, SheetNotReadyError
        return load_keywords_from_sheet(sheets_spreadsheet)
    except Exception as e:
        try:
            import streamlit as sl
            sl.warning(f"無法從 Google Sheets 讀取關鍵字（{e}），改用 config.json 備用清單。")
        except Exception:
            print(f"[configLoader] keywords fallback to config.json: {e}")
        return dict(_CONFIG_KEYWORDS)

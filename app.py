import streamlit as sl
import uuid
import pytz
import altair as alt
from datetime import datetime
from data_processing.data_cleaner import delete_duplicates
from data_processing import sheets_sync
from scrapers.g0vScraper import G0vScraper
from scrapers.pccScraper import PccScraper
from data_processing.pcc_g0v_merger import PccG0vMerger
import config.configLoader as cfg
from config.configLoader import CONFIG_PATH
from model.text_classification import score_titles, get_last_provider, get_diagnostics


# ── Page config ───────────────────────────────────────────────────────────────
sl.set_page_config(page_title="標案下載", page_icon="🐄", layout="wide")
_tz_taipei = pytz.timezone("Asia/Taipei")
today_date = datetime.now(pytz.utc).astimezone(_tz_taipei).date()
_AI_THRESHOLD_DEFAULT = 70

# ── Sheets auth (once per session) ───────────────────────────────────────────
if "sheets_available" not in sl.session_state:
    _client = sheets_sync.get_sheets_client()
    _sp = sheets_sync.get_spreadsheet(_client) if _client else None
    sl.session_state["spreadsheet"] = _sp
    sl.session_state["sheets_available"] = _sp is not None

# ── Keyword loading (once per session) ───────────────────────────────────────
if "keywords_loaded" not in sl.session_state:
    _kw = cfg.load_keywords(sl.session_state.get("spreadsheet"))
    cfg.TITLE_KEYWORDS = _kw["title"]
    cfg.COMPANY_KEYWORDS = _kw["company"]
    sl.session_state["title_keywords"] = _kw["title"]
    sl.session_state["company_keywords"] = _kw["company"]
    sl.session_state["keywords_loaded"] = True

# ── Session state defaults ────────────────────────────────────────────────────
if "scraping_status" not in sl.session_state:
    sl.session_state["tender"] = None
    sl.session_state["award"] = None
    sl.session_state["scraping_status"] = "idle"

# ── Page title ────────────────────────────────────────────────────────────────
sl.markdown("<h1 style='text-align: center;'>Moldev 相關標案下載</h1>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = sl.tabs(["⚙️ 設定", "📥 結果", "📊 後台統計"])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1: 設定
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    sl.markdown("---")

    # Keyword preview
    tk_str = ", ".join(sl.session_state["title_keywords"])
    ck_str = ", ".join(sl.session_state["company_keywords"])
    sl.write(f"Current date: {today_date}")
    sl.write(f"### Title Keywords: \n{tk_str}")
    sl.write(f"### Company Keywords: \n{ck_str}")

    if sl.session_state["sheets_available"]:
        sl.caption("✅ Google Sheets 後台已連線，關鍵字從 Keywords 分頁讀取")
    else:
        sl.caption("⚠️ Google Sheets 未設定，關鍵字從本機 config.json 讀取")

    with sl.form("設定"):
        start_date = sl.date_input("開始日期", value=None)
        sl.write(f"AI 將自動為每筆標案評分（0–100），可於結果頁調整篩選門檻（預設 {_AI_THRESHOLD_DEFAULT}）")
        s_state = sl.form_submit_button("完成設定")

    if s_state:
        if start_date is None or start_date > today_date:
            sl.warning("請輸入有效開始日期！")
        else:
            formatted_date = int(start_date.strftime("%Y%m%d"))

            # ── Scrape ────────────────────────────────────────────────────
            g0vScraper = G0vScraper(formatted_date, CONFIG_PATH)
            g0vTenderDf, g0vAwardDf = g0vScraper.run_scraper()

            pccScraper = PccScraper(formatted_date, CONFIG_PATH)
            pccTenderDf, pccAwardDf = pccScraper.run_scraper()

            scrapeDataMerger = PccG0vMerger(pccTenderDf, pccAwardDf, g0vTenderDf, g0vAwardDf)
            tenders_df, awards_df = scrapeDataMerger.run_merger()
            delete_duplicates(tenders_df, awards_df)

            # ── AI Score ──────────────────────────────────────────────────
            tender_titles = tenders_df["title"].tolist() if "title" in tenders_df.columns else []
            award_titles  = awards_df["title"].tolist()  if "title" in awards_df.columns  else []

            n_tender = len([t for t in tender_titles if isinstance(t, str) and t.strip()])
            n_award  = len([t for t in award_titles  if isinstance(t, str) and t.strip()])
            total_valid = n_tender + n_award
            progress_bar = sl.progress(0.0, text="AI 評分中…")
            _progress_state = {"base": 0}

            def _update_progress(done, _total):
                overall = _progress_state["base"] + done
                frac = overall / total_valid if total_valid else 1.0
                progress_bar.progress(min(frac, 1.0), text=f"AI 評分中… {overall}/{total_valid}")

            tender_score = score_titles(tender_titles, progress_callback=_update_progress)
            _progress_state["base"] = n_tender
            award_score  = score_titles(award_titles, progress_callback=_update_progress)
            progress_bar.empty()

            tenders_df.insert(0, "score", tender_score)
            awards_df.insert(0, "score", award_score)

            # Persist scoring outcome so it survives rerun() into Tab 2
            if tenders_df["score"].isna().all() and awards_df["score"].isna().all():
                sl.session_state["score_failed"] = True
                sl.session_state["score_diag"] = get_diagnostics()
                sl.session_state["score_provider"] = None
            else:
                sl.session_state["score_failed"] = False
                sl.session_state["score_diag"] = None
                sl.session_state["score_provider"] = get_last_provider()

            tenders_df["score"] = tenders_df["score"].fillna(-1).astype(int)
            awards_df["score"]  = awards_df["score"].fillna(-1).astype(int)

            # ── Google Sheets push ────────────────────────────────────────
            t_new = 0
            a_new = 0
            if sl.session_state["sheets_available"]:
                _sp = sl.session_state["spreadsheet"]
                _run_id = str(uuid.uuid4())
                _ts = datetime.now(_tz_taipei).isoformat()
                try:
                    with sl.spinner("同步至 Google Sheets…"):
                        t_new = sheets_sync.append_new_records(_sp, tenders_df, "Tenders_RAW", _run_id, _ts)
                        a_new = sheets_sync.append_new_records(_sp, awards_df,  "Awards_RAW",  _run_id, _ts)
                        sheets_sync.append_run_log(_sp, {
                            "run_id":           _run_id,
                            "run_at":           _ts,
                            "start_date":       formatted_date,
                            "end_date":         int(today_date.strftime("%Y%m%d")),
                            "tenders_scraped":  len(tenders_df),
                            "awards_scraped":   len(awards_df),
                            "tenders_new":      t_new,
                            "awards_new":       a_new,
                            "ai_provider":      sl.session_state.get("score_provider") or "FAILED",
                            "score_failed":     sl.session_state.get("score_failed", False),
                        })
                except Exception as e:
                    sl.warning(f"Google Sheets 同步失敗（資料仍可從結果頁下載）：{e}")

                sl.session_state["run_id"]       = _run_id
                sl.session_state["tenders_new"]  = t_new
                sl.session_state["awards_new"]   = a_new
                # Invalidate stats cache so Tab 3 reflects the new run
                sl.session_state.pop("stats_data", None)

            # ── Persist & rerun ───────────────────────────────────────────
            sl.session_state["tender"]          = tenders_df
            sl.session_state["award"]           = awards_df
            sl.session_state["scraping_status"] = "done"
            sl.session_state["ai_threshold"]    = _AI_THRESHOLD_DEFAULT
            sl.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2: 結果
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    if sl.session_state.get("scraping_status") != "done":
        sl.info("請先在 ⚙️ 設定頁選擇日期並執行抓取。")
    else:
        # AI scoring status banner
        if sl.session_state.get("score_failed"):
            sl.warning("⚠️ AI 評分全部失敗（所有模型 API 連線或金鑰問題），score 欄位顯示為 -1，篩選功能暫時無效。")
            _diag = sl.session_state.get("score_diag") or {}
            if _diag.get("configured"):
                sl.write(f"已設定金鑰的模型：{', '.join(_diag['configured'])}")
            if _diag.get("missing"):
                sl.write(f"未設定金鑰的模型：{', '.join(_diag['missing'])}")
            if _diag.get("errors"):
                sl.error("實際錯誤訊息：\n" + "\n".join(f"- {e}" for e in _diag["errors"]))
            else:
                sl.info("沒有捕捉到 API 錯誤；請確認 Streamlit secrets 內的金鑰名稱為 "
                        "OPENAI_API_KEY / GEMINI_API_KEY / GROQ_API_KEY，且帳戶有額度。")
        elif sl.session_state.get("score_provider"):
            sl.write(f"✅ 評分模型：{sl.session_state['score_provider']}")

        # Sheets sync result
        if sl.session_state.get("sheets_available") and "tenders_new" in sl.session_state:
            sl.success(
                f"✅ 已同步至 Google Sheets：招標 {sl.session_state['tenders_new']} 筆新增、"
                f"決標 {sl.session_state['awards_new']} 筆新增"
            )

        def _convert_df_to_csv(df):
            return df.to_csv(index=False).encode("utf-8-sig")

        if sl.session_state.get("tender") is not None:
            # Threshold slider
            threshold = sl.slider(
                "AI 相關度篩選門檻 (score ≥)",
                min_value=0, max_value=100,
                value=int(sl.session_state.get("ai_threshold", _AI_THRESHOLD_DEFAULT)),
                step=5,
            )
            sl.session_state["ai_threshold"] = threshold

            _t_df = sl.session_state["tender"]
            _a_df = sl.session_state["award"]
            ai_tenders = _t_df[_t_df["score"] >= threshold]
            ai_awards  = _a_df[_a_df["score"] >= threshold]
            sl.caption(f"符合門檻：招標 {len(ai_tenders)} 筆、決標 {len(ai_awards)} 筆")

            sl.download_button(
                label="下載招標資料 CSV (AI篩選)",
                data=_convert_df_to_csv(ai_tenders),
                file_name=f"{today_date}_filtered_tender_data.csv",
                mime="text/csv",
            )
            sl.download_button(
                label="下載決標資料 CSV (AI篩選)",
                data=_convert_df_to_csv(ai_awards),
                file_name=f"{today_date}_filtered_award_data.csv",
                mime="text/csv",
            )
            sl.download_button(
                label="下載完整關鍵字招標資料 CSV",
                data=_convert_df_to_csv(_t_df),
                file_name=f"{today_date}_tender_data.csv",
                mime="text/csv",
            )
            sl.download_button(
                label="下載完整關鍵字決標資料 CSV",
                data=_convert_df_to_csv(_a_df),
                file_name=f"{today_date}_award_data.csv",
                mime="text/csv",
            )

            def _toggle_preview():
                sl.session_state["preview_open"] = not sl.session_state.get("preview_open", False)

            sl.button("預覽", on_click=_toggle_preview)
            if sl.session_state.get("preview_open"):
                sl.write("招標資料")
                sl.dataframe(_t_df, use_container_width=True)
                sl.write("決標資料")
                sl.dataframe(_a_df, use_container_width=True)
        else:
            sl.warning("No data to download.")

        def _reset_state():
            _keep = ["sheets_available", "spreadsheet", "keywords_loaded",
                     "title_keywords", "company_keywords"]
            _saved = {k: sl.session_state[k] for k in _keep if k in sl.session_state}
            sl.session_state.clear()
            sl.session_state.update(_saved)
            sl.rerun()

        sl.button("重置", on_click=_reset_state)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3: 後台統計
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    if not sl.session_state.get("sheets_available"):
        sl.warning("Google Sheets 後台尚未設定。請在 Streamlit Cloud → Settings → Secrets 加入：")
        sl.code(
            'GOOGLE_SHEET_ID = "your-spreadsheet-id"\n\n'
            '[gcp_service_account]\n'
            'type = "service_account"\n'
            'project_id = "your-project-id"\n'
            'private_key_id = "..."\n'
            'private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"\n'
            'client_email = "service-account@project.iam.gserviceaccount.com"\n'
            'client_id = "..."\n'
            'auth_uri = "https://accounts.google.com/o/oauth2/auth"\n'
            'token_uri = "https://oauth2.googleapis.com/token"\n'
            'auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"\n'
            'client_x509_cert_url = "..."',
            language="toml",
        )
        sl.markdown(
            "並建立 Google Sheet，加入 4 個分頁（名稱需完全一致）：\n"
            "`Keywords` · `Tenders_RAW` · `Awards_RAW` · `RunLog`\n\n"
            "**Keywords 分頁格式**：`keyword` | `type`（title/company）| `active`（TRUE/FALSE）| `notes`"
        )
    else:
        _sp3 = sl.session_state["spreadsheet"]

        # Toolbar row
        _col_refresh, _col_link = sl.columns([1, 3])
        with _col_refresh:
            if sl.button("🔄 刷新統計"):
                with sl.spinner("讀取後台統計…"):
                    try:
                        sl.session_state["stats_data"] = {
                            "totals":     sheets_sync.load_cumulative_totals(_sp3),
                            "history":    sheets_sync.load_run_history(_sp3),
                            "score_dist": sheets_sync.load_score_distribution(_sp3),
                            "top_orgs":   sheets_sync.load_top_organizations(_sp3),
                        }
                    except Exception as _e:
                        sl.warning(f"統計讀取失敗：{_e}")

        with _col_link:
            try:
                _sheet_id = sl.secrets.get("GOOGLE_SHEET_ID")
                if _sheet_id:
                    sl.link_button(
                        "📊 在 Google Sheets 查看完整資料",
                        f"https://docs.google.com/spreadsheets/d/{_sheet_id}",
                    )
            except Exception:
                pass

        if "stats_data" not in sl.session_state:
            sl.info("點選「🔄 刷新統計」載入後台累積資料")
        else:
            _data = sl.session_state["stats_data"]
            _totals = _data["totals"]

            # Cumulative metrics
            _m1, _m2, _m3 = sl.columns(3)
            _m1.metric("累積招標筆數", _totals.get("total_tenders", 0))
            _m2.metric("累積決標筆數", _totals.get("total_awards", 0))
            _m3.metric("總執行次數",   _totals.get("total_runs", 0))

            sl.markdown("---")

            # Run history
            sl.subheader("最近執行紀錄")
            _hist = _data["history"]
            if _hist.empty:
                sl.info("尚無執行紀錄")
            else:
                sl.dataframe(_hist, use_container_width=True)

            sl.markdown("---")

            # Score distribution
            sl.subheader("AI 相關度分數分佈")
            _sd = _data["score_dist"]
            if _sd.empty:
                sl.info("尚無評分資料（-1 為評分失敗，已排除）")
            else:
                _chart = (
                    alt.Chart(_sd)
                    .mark_bar(opacity=0.75)
                    .encode(
                        alt.X("score:Q", bin=alt.Bin(step=10), title="相關度分數"),
                        alt.Y("count():Q", title="件數"),
                        alt.Color("source:N", title="類型"),
                        tooltip=[
                            alt.Tooltip("source:N", title="類型"),
                            alt.Tooltip("count():Q", title="件數"),
                        ],
                    )
                    .properties(height=300)
                )
                sl.altair_chart(_chart, use_container_width=True)

            sl.markdown("---")

            # Top organizations
            sl.subheader("前 10 大採購機關")
            _orgs = _data["top_orgs"]
            if _orgs.empty:
                sl.info("尚無機關資料")
            else:
                sl.dataframe(_orgs, use_container_width=True)

import streamlit as sl
import threading
import uuid
import pytz
import altair as alt
import pandas as pd
from datetime import datetime
from data_processing.data_cleaner import delete_duplicates
from data_processing import sheets_sync
from scrapers.g0vScraper import G0vScraper
from scrapers.pccScraper import PccScraper
from scrapers import diagnostics
from data_processing.pcc_g0v_merger import PccG0vMerger
import config.configLoader as cfg
from config.configLoader import CONFIG_PATH
from model.text_classification import score_titles, get_last_provider, get_diagnostics
import streamlit.components.v1 as components
from ui import theme, radar


# ── Page config ───────────────────────────────────────────────────────────────
sl.set_page_config(page_title="Moldev 標案雷達", page_icon="📡", layout="wide")
sl.markdown(theme.CSS, unsafe_allow_html=True)
_tz_taipei = pytz.timezone("Asia/Taipei")
today_date = datetime.now(pytz.utc).astimezone(_tz_taipei).date()
_AI_THRESHOLD_DEFAULT = 70


@sl.cache_resource
def _scrape_lock():
    # One lock shared by every browser session on this server, so two
    # colleagues (or a page refresh) can't run overlapping scrapes that
    # double the load on the source sites and trip their rate limits.
    return threading.Lock()

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

# ── Overview from Sheets (cached; cleared after each scan) ───────────────────
@sl.cache_data(ttl=600, show_spinner=False)
def _overview(_spreadsheet, company_keywords, day):
    return sheets_sync.load_overview(_spreadsheet, list(company_keywords), day)


overview = None
if sl.session_state["sheets_available"]:
    try:
        overview = _overview(sl.session_state["spreadsheet"],
                             tuple(sl.session_state["company_keywords"]), today_date)
    except Exception as e:
        print(f"[app] overview failed: {e}")

# ── Nav bar ───────────────────────────────────────────────────────────────────
if overview and overview["last_run_at"]:
    _last = overview["last_run_at"][5:16].replace("T", " ")
    _status = f"最後掃描 <b>{_last}</b> · 共 {overview['total_runs']} 次"
elif sl.session_state["sheets_available"]:
    _status = "尚無掃描紀錄"
else:
    _status = "Google Sheets 未連線"
sl.markdown(theme.nav(_status), unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = sl.tabs(["總覽", "掃描結果", "後台統計"])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1: 設定
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    _hero_l, _hero_r = sl.columns([1.25, 1], gap="large")
    with _hero_l:
        sl.markdown(theme.hero_text(len(sl.session_state["title_keywords"]),
                                    len(sl.session_state["company_keywords"])),
                    unsafe_allow_html=True)
        with sl.form("設定"):
            _c_date, _c_btn = sl.columns([3, 1], vertical_alignment="bottom")
            start_date = _c_date.date_input("從哪一天開始掃描", value=None, max_value=today_date)
            s_state = _c_btn.form_submit_button("開始掃描", use_container_width=True)
        sl.markdown(theme.chips("產品關鍵字", sl.session_state["title_keywords"], limit=7)
                    + theme.chips("經銷商", sl.session_state["company_keywords"], dealer=True, limit=6),
                    unsafe_allow_html=True)
        with sl.expander("完整監測清單"):
            sl.markdown(theme.chips("產品關鍵字", sl.session_state["title_keywords"])
                        + theme.chips("經銷商", sl.session_state["company_keywords"], dealer=True),
                        unsafe_allow_html=True)
            if sl.session_state["sheets_available"]:
                sl.caption(f"來自 Google Sheets「Keywords」分頁 · AI 預設門檻 {_AI_THRESHOLD_DEFAULT} 分")
            else:
                sl.caption("⚠️ Google Sheets 未設定，關鍵字從本機 config.json 讀取")

    with _hero_r:
        # Blips: this session's results if any, else the latest notices in Sheets
        _items = []
        for _kind, _key in (("招標", "tender"), ("決標", "award")):
            _df = sl.session_state.get(_key)
            if _df is not None and len(_df):
                _items += [{"kind": _kind, "title": r.get("title", ""), "job": r.get("job_number", ""),
                            "score": r.get("score")} for _, r in _df.iterrows()]
        if _items:
            _cap = f"本次掃描 {len(_items)} 筆"
        elif overview and overview["recent"]:
            _items, _cap = overview["recent"], f"最近收錄 {len(overview['recent'])} 筆"
        else:
            _cap = "示意畫面 · 掃描後顯示實際標案"
        components.html(radar.html(_items, _cap), height=440)

    if s_state:
        if start_date is None or start_date > today_date:
            sl.warning("請輸入有效開始日期！")
        elif not _scrape_lock().acquire(blocking=False):
            sl.warning("另一位同事正在執行抓取，請等對方完成後再試。")
        else:
            try:
                formatted_date = int(start_date.strftime("%Y%m%d"))

                # ── Scrape ────────────────────────────────────────────────────
                g0vScraper = G0vScraper(formatted_date, CONFIG_PATH)
                g0vTenderDf, g0vAwardDf = g0vScraper.run_scraper()

                # Direct PCC scraping is switched off in config.json (unreachable
                # from Streamlit Cloud); the module stays for a Taiwan-hosted deploy.
                pcc_warning = None
                if cfg.config['websites']['pcc_gov'].get('enabled', True):
                    pccScraper = PccScraper(formatted_date, CONFIG_PATH)
                    pccTenderDf, pccAwardDf = pccScraper.run_scraper()
                    pcc_warning = pccScraper.warning
                else:
                    pccTenderDf, pccAwardDf = pd.DataFrame(), pd.DataFrame()
                source_warnings = [w for w in (g0vScraper.warning, pcc_warning) if w]

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
                # Nothing scraped means nothing to score — not a scoring failure
                if total_valid and tenders_df["score"].isna().all() and awards_df["score"].isna().all():
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

                    with sl.spinner("同步招標資料至 Google Sheets…"):
                        try:
                            t_new = sheets_sync.append_new_records(
                                _sp, tenders_df, "Tenders_RAW", _run_id, _ts,
                                dedup_keys=["job_number", "招標資料:招標狀態"],
                            )
                        except Exception as e:
                            sl.warning(f"招標資料 Sheets 同步失敗（資料仍可從結果頁下載）：{e}")

                    with sl.spinner("同步決標資料至 Google Sheets…"):
                        try:
                            a_new = sheets_sync.append_new_records(
                                _sp, awards_df, "Awards_RAW", _run_id, _ts,
                            )
                        except Exception as e:
                            sl.warning(f"決標資料 Sheets 同步失敗（資料仍可從結果頁下載）：{e}")

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

                    sl.session_state["run_id"]       = _run_id
                    sl.session_state["tenders_new"]  = t_new
                    sl.session_state["awards_new"]   = a_new
                    # Invalidate stats cache so Tab 3 reflects the new run
                    sl.session_state.pop("stats_data", None)
                    _overview.clear()

                # ── Persist & rerun ───────────────────────────────────────────
                sl.session_state["tender"]          = tenders_df
                sl.session_state["award"]           = awards_df
                sl.session_state["source_warnings"] = source_warnings
                sl.session_state["scraping_status"] = "done"
                sl.session_state["ai_threshold"]    = _AI_THRESHOLD_DEFAULT
                sl.rerun()
            finally:
                _scrape_lock().release()

    if overview:
        _top_dealer = overview["dealer_wins"][0] if overview["dealer_wins"] else None
        sl.markdown(theme.kpis([
            ("dark", "累積追蹤標案", f"{overview['total']:,}",
             f"招標 {overview['total_tenders']:,} · 決標 {overview['total_awards']:,}"),
            ("green", "現在招標中", f"{overview['open_tenders']:,}", "截止日未到、還能投"),
            ("gray", "經銷商得標", f"{overview['dealer_win_total']:,}",
             f"{_top_dealer[0]} 最多（{_top_dealer[1]} 件）" if _top_dealer
             else f"最大決標 {theme.money(overview['max_amount'])}"),
        ]), unsafe_allow_html=True)

        sl.markdown(theme.section("標案數據總覽",
                                  f"{overview['total']:,} 件 · 來源 Google Sheets 累積資料"),
                    unsafe_allow_html=True)
        sl.markdown(theme.grid([
            theme.card("標案狀態", theme.donut([
                ("招標中", overview["open_tenders"], theme.GREEN),
                ("已截止", overview["closed_tenders"], "#b8b8b2"),
                ("已決標", overview["awarded"], "#8e8e93"),
                ("無法決標", overview["failed"], "#c2611f"),
            ], "件")),
            theme.card("決標金額分布", theme.bars(overview["amount_buckets"])),
            theme.card("經銷商得標排行", theme.bars(overview["dealer_wins"][:8], color=theme.GREEN,
                                                   empty="尚無經銷商得標紀錄"), "依得標廠商比對"),
            theme.card("最常發標的機關", theme.bars(overview["top_orgs"], color=theme.GREEN), "TOP 8"),
        ]), unsafe_allow_html=True)

    sl.write("")
    with sl.expander("🔧 資料來源連線診斷"):
        sl.caption("從這台伺服器實際連一次 g0v API 與政府採購網，約需 1 分鐘")
        if sl.button("執行診斷"):
            with sl.spinner("診斷中…"):
                sl.session_state["diagnostics"] = diagnostics.run(CONFIG_PATH)
        if sl.session_state.get("diagnostics"):
            sl.dataframe(sl.session_state["diagnostics"], use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2: 結果
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    if sl.session_state.get("scraping_status") != "done":
        sl.info("請先在「總覽」選擇開始日期並按「開始掃描」。")
    else:
        # Data source failures (site unreachable, API rate limit, ...)
        for _w in sl.session_state.get("source_warnings") or []:
            sl.warning(f"⚠️ {_w}")

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
            sl.markdown(theme.kpis([
                ("dark", "本次招標", f"{len(_t_df):,}", f"符合門檻 {len(ai_tenders)} 筆"),
                ("green", "符合門檻", f"{len(ai_tenders) + len(ai_awards):,}", f"AI 分數 ≥ {threshold}"),
                ("gray", "本次決標", f"{len(_a_df):,}", f"符合門檻 {len(ai_awards)} 筆"),
            ]), unsafe_allow_html=True)

            _d1, _d2, _d3, _d4 = sl.columns(4)
            _d1.download_button("⬇ 招標（符合門檻）", _convert_df_to_csv(ai_tenders),
                                f"{today_date}_filtered_tender_data.csv", "text/csv", use_container_width=True)
            _d2.download_button("⬇ 決標（符合門檻）", _convert_df_to_csv(ai_awards),
                                f"{today_date}_filtered_award_data.csv", "text/csv", use_container_width=True)
            _d3.download_button("⬇ 招標（全部）", _convert_df_to_csv(_t_df),
                                f"{today_date}_tender_data.csv", "text/csv", use_container_width=True)
            _d4.download_button("⬇ 決標（全部）", _convert_df_to_csv(_a_df),
                                f"{today_date}_award_data.csv", "text/csv", use_container_width=True)

            _cols_cfg = {
                "score": sl.column_config.ProgressColumn("AI", min_value=0, max_value=100, format="%d"),
                "url": sl.column_config.LinkColumn("公告", display_text="開啟"),
                "title": sl.column_config.TextColumn("標案名稱", width="large"),
                "date": sl.column_config.NumberColumn("日期", format="%d"),
                "keyword": "關鍵字", "機關名稱": "機關", "type": "類型",
                "決標品項:第1品項:得標廠商1:得標廠商": "得標廠商",
                "決標資料:總決標金額": "決標金額",
                "領投開標:截止投標": "截止投標", "採購資料:預算金額": "預算",
            }

            def _show(df, cols):
                cols = [c for c in cols if c in df.columns]
                view = df.sort_values("score", ascending=False)[cols]
                text_cols = [c for c in cols if c not in ("score", "date")]
                view[text_cols] = view[text_cols].fillna("")   # no "None" in empty cells
                sl.dataframe(view, column_config=_cols_cfg, hide_index=True, use_container_width=True)

            _award_cols = ["score", "date", "title", "keyword", "機關名稱",
                           "決標品項:第1品項:得標廠商1:得標廠商", "決標資料:總決標金額", "type", "url"]
            _tender_cols = ["score", "date", "title", "keyword", "機關名稱",
                            "領投開標:截止投標", "採購資料:預算金額", "url"]
            sl.markdown(theme.section("決標", f"符合門檻 {len(ai_awards)} 筆"), unsafe_allow_html=True)
            _show(ai_awards, _award_cols)
            sl.markdown(theme.section("招標", f"符合門檻 {len(ai_tenders)} 筆"), unsafe_allow_html=True)
            _show(ai_tenders, _tender_cols)
            with sl.expander(f"全部資料（不分門檻）：招標 {len(_t_df)} 筆、決標 {len(_a_df)} 筆"):
                _show(_a_df, _award_cols)
                _show(_t_df, _tender_cols)
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
                            "history":    sheets_sync.load_run_history(_sp3),
                            "score_dist": sheets_sync.load_score_distribution(_sp3),
                        }
                        _overview.clear()
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

            # Run history
            sl.markdown(theme.section("最近執行紀錄"), unsafe_allow_html=True)
            _hist = _data["history"]
            if _hist.empty:
                sl.info("尚無執行紀錄")
            else:
                sl.dataframe(_hist, use_container_width=True)

            # Score distribution
            sl.markdown(theme.section("AI 相關度分數分佈"), unsafe_allow_html=True)
            _sd = _data["score_dist"]
            if _sd.empty:
                sl.info("尚無評分資料（-1 為評分失敗，已排除）")
            else:
                _chart = (
                    alt.Chart(_sd)
                    .mark_bar(opacity=0.85, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        alt.X("score:Q", bin=alt.Bin(step=10), title="相關度分數"),
                        alt.Y("count():Q", title="件數"),
                        alt.Color("source:N", title="類型",
                                  scale=alt.Scale(domain=["招標", "決標"], range=[theme.GREEN, "#c2611f"])),
                        tooltip=[
                            alt.Tooltip("source:N", title="類型"),
                            alt.Tooltip("count():Q", title="件數"),
                        ],
                    )
                    .properties(height=300)
                )
                sl.altair_chart(_chart, use_container_width=True)

import pandas as pd

try:
    import gspread
    from google.oauth2.service_account import Credentials
    _GSPREAD_AVAILABLE = True
except ImportError:
    _GSPREAD_AVAILABLE = False

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


class SheetNotReadyError(Exception):
    """Raised when a tab exists but has no header row (not yet initialized)."""


def get_sheets_client():
    """Authenticate with the GCP service account from Streamlit secrets.

    Returns a gspread.Client, or None if secrets are absent or auth fails.
    """
    if not _GSPREAD_AVAILABLE:
        return None
    try:
        import streamlit as sl
        creds_info = dict(sl.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_info, scopes=_SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[sheets_sync] auth failed: {e}")
        return None


def get_spreadsheet(client):
    """Open the spreadsheet by ID stored in st.secrets['GOOGLE_SHEET_ID'].

    Returns a gspread.Spreadsheet, or None on any failure.
    """
    if client is None:
        return None
    try:
        import streamlit as sl
        sheet_id = sl.secrets["GOOGLE_SHEET_ID"]
        return client.open_by_key(sheet_id)
    except Exception as e:
        print(f"[sheets_sync] open spreadsheet failed: {e}")
        return None


def sheets_available():
    """Return True if Sheets is reachable this session (cached in session_state)."""
    try:
        import streamlit as sl
        if "sheets_available" in sl.session_state:
            return bool(sl.session_state["sheets_available"])
        client = get_sheets_client()
        sp = get_spreadsheet(client) if client else None
        sl.session_state["spreadsheet"] = sp
        result = sp is not None
        sl.session_state["sheets_available"] = result
        return result
    except Exception:
        return False


# ── Keywords ─────────────────────────────────────────────────────────────────

def load_keywords_from_sheet(spreadsheet):
    """Read the 'Keywords' tab and return {"title": [...], "company": [...]}.

    Only rows where active column is truthy are included.
    Raises SheetNotReadyError if the tab is missing or has no data rows.
    """
    try:
        ws = spreadsheet.worksheet("Keywords")
    except Exception:
        try:
            available = [s.title for s in spreadsheet.worksheets()]
            raise SheetNotReadyError(
                f"找不到名為「Keywords」的分頁。"
                f"試算表中現有的分頁：{available}。"
                f"請將分頁名稱改為完全符合「Keywords」（區分大小寫）。"
            )
        except SheetNotReadyError:
            raise
        except Exception:
            raise SheetNotReadyError("Keywords tab not found in spreadsheet")

    records = ws.get_all_records()
    if not records:
        raise SheetNotReadyError("Keywords tab is empty — seed it with keyword/type/active columns")

    def _active(r):
        v = str(r.get("active", "")).strip().upper()
        return v in ("TRUE", "1", "YES")

    title_kws   = [str(r["keyword"]) for r in records if str(r.get("type","")).strip().lower() == "title"   and _active(r)]
    company_kws = [str(r["keyword"]) for r in records if str(r.get("type","")).strip().lower() == "company" and _active(r)]
    return {"title": title_kws, "company": company_kws}


# ── Headers / Tab management ──────────────────────────────────────────────────

def ensure_headers(spreadsheet, tab_name, headers):
    """Return the worksheet for tab_name, creating it and writing headers if needed.

    - Tab missing → create it, write headers as row 1.
    - Tab exists, row 1 empty → write headers.
    - Tab exists, row 1 non-empty → leave as-is (user data preserved).
    """
    try:
        ws = spreadsheet.worksheet(tab_name)
        existing = ws.row_values(1)
        if not existing:
            ws.update(range_name="A1", values=[headers])
    except Exception as e:
        if "not found" in str(e).lower() or "worksheet" in str(e).lower():
            ws = spreadsheet.add_worksheet(title=tab_name, rows="5000", cols=str(max(len(headers) + 5, 30)))
            ws.update(range_name="A1", values=[headers])
        else:
            raise
    return ws


# ── RAW data append ───────────────────────────────────────────────────────────

def append_new_records(spreadsheet, df, tab_name, run_id, appended_at, dedup_keys=None):
    """Append rows from df that are not already in the sheet.

    dedup_keys: list of column names forming the composite dedup key.
                Defaults to ["job_number"] when None.
    Prepends run_id + appended_at columns; appends tags + user_notes at the end.
    Returns the count of rows actually appended.
    """
    if df is None or df.empty:
        return 0

    if dedup_keys is None:
        dedup_keys = ["job_number"]

    df = df.copy()
    # Prepend housekeeping, append user-editable columns
    df.insert(0, "appended_at", appended_at)
    df.insert(0, "run_id", run_id)
    if "tags" not in df.columns:
        df["tags"] = ""
    if "user_notes" not in df.columns:
        df["user_notes"] = ""

    headers = list(df.columns)
    ws = ensure_headers(spreadsheet, tab_name, headers)

    # Read existing composite keys from sheet for dedup. Only keys present in
    # both the data and the sheet header are compared, so a sheet created
    # before a key column existed still dedups on the remaining keys instead
    # of treating every row as new.
    existing_combos: set = set()
    # First-key values of sheet rows whose other keys are blank (e.g. rows
    # from the old PCC scraper had no 招標狀態): such a row can't tell
    # re-tenders apart, so it matches any incoming row with that first key.
    wildcard_first: set = set()
    existing_first: set = set()
    sheet_hdr: list = []
    try:
        sheet_hdr = ws.row_values(1)
    except Exception:
        pass
    available_keys = [k for k in dedup_keys if k in headers and k in sheet_hdr]
    if available_keys:
        try:
            cols_data = [ws.col_values(sheet_hdr.index(k) + 1)[1:] for k in available_keys]
            max_len = max((len(c) for c in cols_data), default=0)
            for i in range(max_len):
                parts = [c[i] if i < len(c) else "" for c in cols_data]
                if any(parts):
                    existing_combos.add("|".join(parts))
                    existing_first.add(parts[0])
                    if len(parts) > 1 and parts[0] and not any(parts[1:]):
                        wildcard_first.add(parts[0])
        except Exception:
            pass

    if available_keys:
        # Same normalisation as the write below (NaN -> ""), so keys match
        keys = df[available_keys].fillna("").astype(str)
        incoming = keys.agg("|".join, axis=1)
        first = keys[available_keys[0]]
        seen = incoming.isin(existing_combos) | first.isin(wildcard_first)
        if len(available_keys) > 1:
            # Same in reverse: an incoming row with the other keys blank
            # (e.g. listing-only fallback) matches on the first key alone.
            other_blank = (keys[available_keys[1:]] == "").all(axis=1)
            seen |= other_blank & first.isin(existing_first)
        new_df = df[~seen].copy()
    else:
        new_df = df.copy()

    if new_df.empty:
        return 0

    # Align columns to the header order in the sheet (in case schema differs)
    actual_hdr = ws.row_values(1) or headers
    # Rows are appended by position, so every header column needs a value;
    # a missing column would shift the values after it under wrong headers.
    for c in actual_hdr:
        if c not in new_df.columns:
            new_df[c] = ""
    aligned_cols = list(actual_hdr)
    # Any columns in df but not in sheet header go at the end
    extra_cols = [c for c in new_df.columns if c not in actual_hdr]
    aligned_cols += extra_cols
    new_df = new_df[aligned_cols]

    rows = new_df.fillna("").astype(str).values.tolist()
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


# ── Run log ───────────────────────────────────────────────────────────────────

_RUNLOG_HEADERS = [
    "run_id", "run_at", "start_date", "end_date",
    "tenders_scraped", "awards_scraped", "tenders_new", "awards_new",
    "ai_provider", "score_failed",
]


def append_run_log(spreadsheet, log_entry):
    """Append one row to RunLog. Silent on failure (audit trail is non-critical)."""
    try:
        ws = ensure_headers(spreadsheet, "RunLog", _RUNLOG_HEADERS)
        row = [str(log_entry.get(k, "")) for k in _RUNLOG_HEADERS]
        ws.append_rows([row], value_input_option="RAW")
    except Exception as e:
        print(f"[sheets_sync] append_run_log failed: {e}")


# ── Overview for the landing page ─────────────────────────────────────────────

# (label, lower bound inclusive, upper bound exclusive)
_AMOUNT_BUCKETS = [("2000萬+", 20_000_000, None), ("500–2000萬", 5_000_000, 20_000_000),
                   ("100–500萬", 1_000_000, 5_000_000), ("100萬↓", 0, 1_000_000)]


def _tab_frame(spreadsheet, tab):
    """Whole tab as a DataFrame of strings (one API call). Empty on failure."""
    try:
        values = spreadsheet.worksheet(tab).get_all_values()
    except Exception as e:
        print(f"[sheets_sync] read {tab} failed: {e}")
        return pd.DataFrame()
    if len(values) < 2:
        return pd.DataFrame()
    width = len(values[0])
    rows = [r + [""] * (width - len(r)) for r in values[1:]]
    return pd.DataFrame(rows, columns=values[0])


def _roc_date(text):
    """'115/11/04 17:00' (ROC calendar) -> date, or None."""
    import re
    from datetime import date
    m = re.match(r"\s*(\d{2,3})/(\d{1,2})/(\d{1,2})", str(text or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _amount(text):
    """'24,000,000元' -> 24000000.0, or None."""
    import re
    digits = re.sub(r"[^\d.]", "", str(text or ""))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def load_overview(spreadsheet, company_keywords, today):
    """Everything the landing page shows, from three sheet reads."""
    tenders = _tab_frame(spreadsheet, "Tenders_RAW")
    awards = _tab_frame(spreadsheet, "Awards_RAW")
    runs = _tab_frame(spreadsheet, "RunLog")

    def col(df, name):
        return df[name] if name in df.columns else pd.Series([""] * len(df), dtype=str)

    deadlines = col(tenders, "領投開標:截止投標").map(_roc_date)
    open_tenders = int(sum(1 for d in deadlines if d and d >= today))
    award_types = col(awards, "type")
    awarded = int((award_types == "決標公告").sum())
    failed = int((award_types == "無法決標公告").sum())

    # Only awarded notices carry an amount; failed awards have none by nature
    amounts = [_amount(v) for v in col(awards, "決標資料:總決標金額")[award_types == "決標公告"]]
    buckets = [(label, sum(1 for a in amounts if a is not None and a >= lo and (hi is None or a < hi)))
               for label, lo, hi in _AMOUNT_BUCKETS]
    buckets.append(("未公開", sum(1 for a in amounts if a is None)))

    winners = col(awards, "決標品項:第1品項:得標廠商1:得標廠商")
    dealer_wins = sorted(((kw, int(winners.str.contains(kw, regex=False).sum()))
                          for kw in company_keywords), key=lambda x: -x[1])
    dealer_wins = [(kw, n) for kw, n in dealer_wins if n]

    orgs = pd.concat([col(tenders, "機關名稱"), col(awards, "機關名稱")])
    top_orgs = list(orgs[orgs != ""].value_counts().head(8).items())

    max_amount = max((a for a in amounts if a), default=0)

    # Most recent notices, for the radar blips
    recent = []
    for kind, df in (("招標", tenders), ("決標", awards)):
        for _, r in df.tail(40).iterrows():
            recent.append({"kind": kind, "title": r.get("title", ""), "job": r.get("job_number", ""),
                           "score": pd.to_numeric(r.get("score", ""), errors="coerce"),
                           "date": r.get("date", "")})
    recent.sort(key=lambda r: str(r["date"]), reverse=True)

    # Scores for the stats-tab histogram (Series, not ndarray: -1 = scoring failed)
    score_rows = []
    for label, df in (("招標", tenders), ("決標", awards)):
        sc = pd.to_numeric(pd.Series(col(df, "score")), errors="coerce").dropna()
        score_rows.append(pd.DataFrame({"source": label, "score": sc[sc >= 0]}))
    scores = pd.concat(score_rows, ignore_index=True)

    return {
        "runs": runs,
        "scores": scores,
        "total": len(tenders) + len(awards),
        "total_tenders": len(tenders),
        "total_awards": len(awards),
        "total_runs": len(runs),
        "last_run_at": str(runs["run_at"].iloc[-1]) if "run_at" in runs.columns and len(runs) else "",
        "open_tenders": open_tenders,
        "closed_tenders": len(tenders) - open_tenders,
        "awarded": awarded,
        "failed": failed,
        "amount_buckets": buckets,
        "max_amount": max_amount,
        "dealer_wins": dealer_wins,
        "dealer_win_total": sum(n for _, n in dealer_wins),
        "top_orgs": top_orgs,
        "recent": recent[:60],
    }

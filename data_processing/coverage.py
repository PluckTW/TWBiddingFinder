# Cases whose tender notice our data source never showed us.
#
# g0v (pcc-api.openfun.app) does not carry tender notices of the procurement
# method 「公開取得電子報價單」 (electronic quotation, used for purchases under
# the 1.5M publication threshold), but it does carry their failed-bid and award
# notices. Example: 國立臺灣大學 1152B026「細胞成像系統1台」— both tender notices
# (the second published 115/11/13, closing 11/17) are missing from g0v, while the
# failed-bid notices of 11/12 and 11/18 are there. So such a case first reaches
# us as a 無法決標公告, scored as highly relevant, after its tender is closed.
#
# A failed bid is normally re-tendered within days with a short deadline, so a
# relevant failed-bid case with no tender notice on record is worth checking on
# the PCC site right away.
import pandas as pd

FAILED_TYPE = "無法決標公告"


def _case_keys(df):
    if df is None or df.empty or "job_number" not in df.columns:
        return set()
    org = df["機關名稱"] if "機關名稱" in df.columns else pd.Series("", index=df.index)
    return set(zip(org.fillna("").astype(str).str.strip(),
                   df["job_number"].fillna("").astype(str).str.strip()))


def retender_watch(awards_df, tender_frames):
    """Failed-bid rows of awards_df whose case has no tender notice in
    tender_frames (this run's tenders plus the sheet's Tenders_RAW)."""
    if awards_df is None or awards_df.empty or "type" not in awards_df.columns:
        return pd.DataFrame()
    seen = set()
    for df in tender_frames:
        seen |= _case_keys(df)
    failed = awards_df[awards_df["type"] == FAILED_TYPE]
    if failed.empty:
        return failed
    org = failed["機關名稱"] if "機關名稱" in failed.columns else pd.Series("", index=failed.index)
    keys = list(zip(org.fillna("").astype(str).str.strip(),
                    failed["job_number"].fillna("").astype(str).str.strip()))
    return failed[[k not in seen for k in keys]]

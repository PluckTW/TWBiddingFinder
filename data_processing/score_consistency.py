# Keep AI relevance scores consistent for the same procurement case.
#
# The LLM score for an identical title is not stable: it depends on which other
# titles share its batch and on run-to-run sampling. In the sheet, 21 titles were
# scored both below and above the 70 threshold (e.g. '400MHz核磁共振光譜儀壹套'
# scored 0 on both tender notices and 70 on its failed-award notice, and
# '光譜儀1台' scored 80 and 20 in the same run). So a case could be dropped at
# tender time and only surface once its award notice was scored higher.
#
# A case is the same case when the agency and job number match (re-tenders keep
# the job number), or the agency and the whitespace-normalised title match.
# Every notice of a case gets the highest score any of its notices got, in this
# run or in earlier runs stored in the sheet.
import re

import pandas as pd


def normalize_title(title):
    """Title without whitespace (g0v inserts spaces between words)."""
    return re.sub(r"\s+", "", str(title or ""))


def _key_parts(row):
    org = str(row.get("機關名稱") or "").strip()
    job = str(row.get("job_number") or "").strip()
    title = normalize_title(row.get("title"))
    keys = []
    if org and job:
        keys.append(("job", org, job))
    if org and title:
        keys.append(("title", org, title))
    return keys


def _valid_score(value):
    score = pd.to_numeric(value, errors="coerce")
    if pd.isna(score) or score < 0:
        return None
    return int(score)


def build_memory(frames):
    """{case key: highest score} over the rows of the given DataFrames."""
    memory = {}
    for df in frames:
        if df is None or df.empty or "score" not in df.columns:
            continue
        for _, row in df.iterrows():
            score = _valid_score(row.get("score"))
            if score is None:
                continue
            for key in _key_parts(row):
                if score > memory.get(key, -1):
                    memory[key] = score
    return memory


def apply_case_max(frames, history=None):
    """Raise each row's score to the highest score of its case.

    frames:  DataFrames of this run (tenders, awards) with a 'score' column;
             updated in place.
    history: DataFrames of earlier runs (sheet tabs), or None.
    Returns the number of rows whose score was raised (or filled in when the
    model gave none).
    """
    memory = build_memory(list(frames) + list(history or []))
    raised = 0
    for df in frames:
        if df is None or df.empty or "score" not in df.columns:
            continue
        for idx, row in df.iterrows():
            best = max((memory.get(k, -1) for k in _key_parts(row)), default=-1)
            current = _valid_score(row.get("score"))
            if best >= 0 and (current is None or best > current):
                df.at[idx, "score"] = best
                raised += 1
    return raised

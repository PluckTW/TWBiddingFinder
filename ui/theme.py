"""Look and feel: page CSS plus small HTML building blocks (cards, bars,
donut) rendered through st.markdown. Styled after bidscan.tw."""
from html import escape

GREEN = "#0a9b6c"
BAR_COLORS = [GREEN, "#2f6fab", "#c2611f", "#c2416b", "#9e9e98"]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap');
:root { --bg:#f6f6f2; --card:#fff; --line:#e7e7e1; --ink:#1c1c1e; --muted:#6e6e73;
        --green:#0a9b6c; --green-soft:#e6f5ee; }
html, body, .stApp, .stMarkdown, button, input, textarea {
  font-family:'Noto Sans TC',-apple-system,'PingFang TC','Microsoft JhengHei',sans-serif; }
.stApp { background:var(--bg); }
header[data-testid="stHeader"] { background:transparent; }
.block-container { max-width:1180px; padding-top:1.4rem; }
footer { visibility:hidden; }

/* tabs as nav pills */
.stTabs [data-baseweb="tab-list"] { gap:6px; border-bottom:1px solid var(--line); padding-bottom:10px; }
.stTabs [data-baseweb="tab"] { height:36px; padding:0 16px; border-radius:10px; font-weight:700; color:#3a3a3d; }
.stTabs [aria-selected="true"] { background:var(--green-soft); color:var(--green); }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }

/* controls */
.stButton > button, .stDownloadButton > button, .stLinkButton > a {
  border-radius:10px; font-weight:700; border:1px solid var(--line); background:#fff; }
[data-testid="stFormSubmitButton"] > button {
  background:var(--green); color:#fff; border:0; border-radius:10px; font-weight:700; height:42px; }
[data-testid="stFormSubmitButton"] > button:hover { background:#08845c; color:#fff; }
[data-testid="stForm"] { background:#fff; border:1px solid var(--line); border-radius:16px;
  box-shadow:0 2px 10px rgba(0,0,0,.04); padding:14px 18px; }
[data-testid="stExpander"] details { background:#fff; border:1px solid var(--line); border-radius:14px; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
[data-testid="stAlert"] { border-radius:12px; }

/* custom blocks */
.tw-nav { display:flex; align-items:center; justify-content:space-between; margin:0 0 6px; }
.tw-brand { display:flex; align-items:center; gap:10px; font-weight:900; font-size:19px; color:var(--ink); }
.tw-status { font-size:13px; color:var(--muted); }
.tw-status b { color:var(--ink); }
.tw-eyebrow { color:var(--green); font-weight:700; font-size:13px; letter-spacing:.06em; margin:18px 0 10px; }
.tw-hero-title { font-size:44px; line-height:1.18; font-weight:900; color:var(--ink); margin:0 0 14px; }
.tw-hero-title span { color:var(--green); }
.tw-hero-sub { color:#4a4a4f; font-size:16px; line-height:1.7; margin:0 0 16px; max-width:560px; }
.tw-chips { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 4px; }
.tw-chips .lbl { font-size:12px; color:var(--muted); margin-right:4px; min-width:56px; }
.tw-chip { border:1px solid #d9d9d3; background:#fff; border-radius:999px; padding:4px 12px; font-size:13px; color:#2c2c2e; }
.tw-chip.dealer { border-color:#bfe3d2; background:var(--green-soft); color:#086b4b; }
.tw-chip.more { border-style:dashed; color:var(--muted); }

.tw-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin:22px 0 8px; }
.tw-kpi { border-radius:16px; padding:18px 20px; color:#fff; }
.tw-kpi .k { font-size:13px; font-weight:700; opacity:.92; }
.tw-kpi .v { font-size:38px; font-weight:900; line-height:1.15; margin:6px 0 2px; letter-spacing:-.01em; }
.tw-kpi .s { font-size:12.5px; opacity:.82; }
.tw-kpi.dark { background:#1c1c1e; } .tw-kpi.green { background:var(--green); } .tw-kpi.gray { background:#3a3a3d; }

.tw-section { display:flex; flex-wrap:wrap; gap:4px 12px; align-items:baseline; justify-content:space-between; margin:34px 0 4px; }
.tw-section h3 { font-size:24px; font-weight:900; margin:0; color:var(--ink); }
.tw-section .meta { font-size:13px; color:var(--muted); }
.tw-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:12px; }
@media (max-width: 760px) { .tw-grid { grid-template-columns:1fr; } .tw-hero-title { font-size:32px; } }
.tw-card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:18px 20px; }
.tw-card .ttl { font-size:15px; font-weight:700; margin:0 0 14px; color:var(--ink); display:flex;
  justify-content:space-between; align-items:baseline; }
.tw-card .ttl small { font-size:11px; color:var(--muted); font-weight:500; letter-spacing:.05em; }
.tw-bar { display:grid; grid-template-columns:minmax(90px,1.1fr) 1fr 48px; gap:12px; align-items:center;
  font-size:13.5px; padding:6px 0; color:#2c2c2e; }
.tw-bar .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-bar .track { height:8px; background:#efefea; border-radius:99px; overflow:hidden; }
.tw-bar .fill { height:100%; border-radius:99px; }
.tw-bar .n { text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }
.tw-donut { display:flex; align-items:center; gap:22px; }
.tw-legend div { display:flex; align-items:center; gap:8px; font-size:13.5px; padding:4px 0; }
.tw-legend i { width:9px; height:9px; border-radius:50%; display:inline-block; }
.tw-legend b { margin-left:auto; padding-left:18px; font-variant-numeric:tabular-nums; }
.tw-empty { color:var(--muted); font-size:13px; padding:8px 0; }
</style>
"""

BRAND_ICON = (
    '<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">'
    '<circle cx="15" cy="15" r="14" fill="#1c1c1e"/>'
    '<circle cx="15" cy="15" r="9" fill="none" stroke="#0a9b6c" stroke-width="1.4" opacity=".7"/>'
    '<path d="M15 15 L15 3 A12 12 0 0 1 25.4 9 Z" fill="#0a9b6c" opacity=".85"/>'
    '<circle cx="15" cy="15" r="2" fill="#fff"/></svg>'
)


def _join(parts):
    # st.markdown treats indented lines as code, so emit flat HTML
    return "".join(parts)


def nav(status_html):
    return _join([
        '<div class="tw-nav">',
        f'<div class="tw-brand">{BRAND_ICON}Moldev 標案雷達</div>',
        f'<div class="tw-status">{status_html}</div>',
        '</div>',
    ])


def hero_text(n_title, n_dealer):
    return _join([
        '<div class="tw-eyebrow">MOLDEV 標案情報</div>',
        '<div class="tw-hero-title">政府每天發上千件標案，<br><span>跟我們有關的都在這裡。</span></div>',
        '<p class="tw-hero-sub">每次掃描都讀取政府電子採購網當期全部公告（透過 g0v），'
        f'比對 {n_title} 個產品關鍵字與 {n_dealer} 家經銷商的得標紀錄，'
        '再由 AI 評分相關度、同步到 Google Sheets。</p>',
    ])


def chips(label, items, dealer=False, limit=None):
    """Pill list; with limit, the rest collapses into a '+N' pill."""
    cls = "tw-chip dealer" if dealer else "tw-chip"
    shown = list(items)[:limit] if limit else list(items)
    body = "".join(f'<span class="{cls}">{escape(str(i))}</span>' for i in shown)
    if len(items) > len(shown):
        body += f'<span class="tw-chip more">+{len(items) - len(shown)}</span>'
    return f'<div class="tw-chips"><span class="lbl">{escape(label)}</span>{body}</div>'


def kpis(cards):
    """cards: [(style, title, value, subtitle)] with style dark/green/gray."""
    return '<div class="tw-kpis">' + "".join(
        f'<div class="tw-kpi {s}"><div class="k">{escape(t)}</div>'
        f'<div class="v">{escape(str(v))}</div><div class="s">{escape(sub)}</div></div>'
        for s, t, v, sub in cards) + '</div>'


def section(title, meta=""):
    return f'<div class="tw-section"><h3>{escape(title)}</h3><span class="meta">{escape(meta)}</span></div>'


def bars(rows, color=None, empty="尚無資料"):
    """rows: [(label, count)] -> horizontal bar list, scaled to the max."""
    if not rows or not any(n for _, n in rows):
        return f'<div class="tw-empty">{escape(empty)}</div>'
    top = max(n for _, n in rows) or 1
    out = []
    for i, (label, n) in enumerate(rows):
        c = color or BAR_COLORS[i % len(BAR_COLORS)]
        out.append(f'<div class="tw-bar"><span class="name" title="{escape(str(label))}">{escape(str(label))}</span>'
                   f'<span class="track"><span class="fill" style="display:block;width:{max(2, 100 * n / top):.1f}%;'
                   f'background:{c}"></span></span><span class="n">{n:,}</span></div>')
    return "".join(out)


def donut(segments, center_label):
    """segments: [(label, count, color)] -> SVG donut with legend."""
    total = sum(n for _, n, _ in segments)
    r, c = 52, 2 * 3.14159265 * 52
    arcs, offset = [], 0.0
    for _, n, color in segments:
        if total and n:
            length = c * n / total
            arcs.append(f'<circle r="{r}" cx="70" cy="70" fill="none" stroke="{color}" stroke-width="18" '
                        f'stroke-dasharray="{length:.2f} {c - length:.2f}" stroke-dashoffset="{-offset:.2f}" '
                        'transform="rotate(-90 70 70)"/>')
            offset += length
    if not arcs:
        arcs.append(f'<circle r="{r}" cx="70" cy="70" fill="none" stroke="#efefea" stroke-width="18"/>')
    svg = ('<svg width="140" height="140" viewBox="0 0 140 140" role="img">' + "".join(arcs) +
           f'<text x="70" y="68" text-anchor="middle" font-size="22" font-weight="900" fill="#1c1c1e">{total:,}</text>'
           f'<text x="70" y="88" text-anchor="middle" font-size="11" fill="#6e6e73">{escape(center_label)}</text></svg>')
    legend = "".join(f'<div><i style="background:{color}"></i>{escape(label)}<b>{n:,}</b></div>'
                     for label, n, color in segments)
    return f'<div class="tw-donut">{svg}<div class="tw-legend">{legend}</div></div>'


def card(title, body, note=""):
    small = f"<small>{escape(note)}</small>" if note else ""
    # a div, not <h4>: Streamlit injects an anchor link into markdown headings
    return f'<div class="tw-card"><div class="ttl"><span>{escape(title)}</span>{small}</div>{body}</div>'


def grid(cards):
    return '<div class="tw-grid">' + "".join(cards) + '</div>'


def money(amount):
    if not amount:
        return "—"
    if amount >= 1e8:
        return f"{amount / 1e8:.1f} 億"
    return f"{amount / 1e4:,.0f} 萬"

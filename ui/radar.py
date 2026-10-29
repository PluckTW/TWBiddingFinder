"""Animated radar for the landing page.

A sweep rotates clockwise; each blip is a real notice, placed at a stable
angle (hash of its job number) and at a distance from the centre set by its
AI score — the closer to the centre, the more relevant. Blips flash as the
sweep passes; high-score notices pulse in orange. Hover shows the title.
"""
import hashlib
import math
import random
from html import escape

PERIOD = 6.0          # seconds per sweep
R = 170               # radar radius in SVG units
HIT_SCORE = 70


def _angle(key):
    return int(hashlib.md5(str(key).encode("utf-8")).hexdigest()[:6], 16) % 360


def _blips(items):
    """items: [{title, job, score, kind}] -> [(angle, radius, hit, label)]."""
    blips = []
    for it in items:
        score = it.get("score")
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = None
        if score is not None and (math.isnan(score) or score < 0):
            score = None
        angle = _angle(it.get("job") or it.get("title"))
        # high score -> near the centre; unscored notices sit on the rim
        radius = 28 + (100 - score) / 100 * 132 if score is not None else 150
        label = f"{it.get('kind', '')}｜{it.get('title', '')}" + (f"｜AI {score:.0f}" if score is not None else "")
        blips.append((angle, radius, score is not None and score >= HIT_SCORE, label))
    return blips


def _demo_blips(n=26):
    rnd = random.Random(7)
    return [(rnd.uniform(0, 360), rnd.uniform(60, 165), i < 3, "") for i in range(n)]


def html(items=None, caption=""):
    blips = _blips(items) if items else _demo_blips()
    rings = "".join(f'<circle r="{R * k / 4:.1f}" class="ring"/>' for k in range(1, 5))
    spokes = "".join(
        f'<line x1="0" y1="0" x2="{R * math.sin(math.radians(a)):.1f}" y2="{-R * math.cos(math.radians(a)):.1f}" class="spoke"/>'
        for a in range(0, 360, 45))
    # trailing sweep: thin wedges fading out behind the leading edge
    wedges = []
    for i in range(16):
        a0, a1 = -3 * (i + 1), -3 * i
        x0, y0 = R * math.sin(math.radians(a0)), -R * math.cos(math.radians(a0))
        x1, y1 = R * math.sin(math.radians(a1)), -R * math.cos(math.radians(a1))
        wedges.append(f'<path d="M0 0 L{x0:.1f} {y0:.1f} A{R} {R} 0 0 1 {x1:.1f} {y1:.1f} Z" '
                      f'fill="#0a9b6c" opacity="{0.30 * (1 - i / 16):.3f}"/>')
    dots = []
    for angle, radius, hit, label in blips:
        x, y = radius * math.sin(math.radians(angle)), -radius * math.cos(math.radians(angle))
        delay = angle / 360 * PERIOD - PERIOD   # flash exactly when the sweep reaches it
        tip = f"<title>{escape(label)}</title>" if label else ""
        if hit:
            dots.append(f'<g transform="translate({x:.1f} {y:.1f})">{tip}'
                        f'<circle r="13" class="halo" style="animation-delay:{delay:.2f}s"/>'
                        f'<circle r="6" class="blip hit" style="animation-delay:{delay:.2f}s"/></g>')
        else:
            dots.append(f'<g transform="translate({x:.1f} {y:.1f})">{tip}'
                        f'<circle r="4.2" class="blip" style="animation-delay:{delay:.2f}s"/></g>')
    cap = f'<div class="cap">{escape(caption)}</div>' if caption else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;background:transparent;font-family:'Noto Sans TC',-apple-system,'PingFang TC',sans-serif;}}
.wrap{{display:flex;flex-direction:column;align-items:center;}}
svg{{width:100%;max-width:380px;height:auto;overflow:visible;}}
.disc{{fill:url(#bg);stroke:#d5e9de;stroke-width:1.2;}}
.ring{{fill:none;stroke:#cfe5d8;stroke-width:1;}}
.spoke{{stroke:#dcece3;stroke-width:1;}}
.sweep{{transform-box:view-box;transform-origin:0 0;animation:spin {PERIOD}s linear infinite;}}
.lead{{stroke:#0a9b6c;stroke-width:2;}}
.blip{{fill:#d4a373;opacity:.55;transform-box:fill-box;transform-origin:center;animation:flash {PERIOD}s linear infinite;}}
.blip.hit{{fill:#c8702a;opacity:.9;}}
.halo{{fill:#c8702a;opacity:0;transform-box:fill-box;transform-origin:center;animation:halo {PERIOD}s ease-out infinite;}}
.core{{fill:#0a9b6c;}}
@keyframes spin{{to{{transform:rotate(360deg);}}}}
@keyframes flash{{0%{{opacity:1;transform:scale(1.7);}}12%{{opacity:.95;transform:scale(1);}}100%{{opacity:.5;transform:scale(1);}}}}
@keyframes halo{{0%{{opacity:.45;transform:scale(.6);}}35%{{opacity:0;transform:scale(1.9);}}100%{{opacity:0;}}}}
@media (prefers-reduced-motion:reduce){{.sweep,.blip,.halo{{animation:none;}}}}
.cap{{font-size:12px;color:#6e6e73;margin-top:6px;text-align:center;}}
.cap i{{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 4px 0 10px;}}
</style></head><body><div class="wrap">
<svg viewBox="-190 -190 380 380" role="img" aria-label="標案雷達">
<defs><radialGradient id="bg"><stop offset="0" stop-color="#f3faf6"/><stop offset="1" stop-color="#e8f3ed"/></radialGradient></defs>
<circle r="{R}" class="disc"/>{rings}{spokes}
<g class="sweep">{''.join(wedges)}<line x1="0" y1="0" x2="0" y2="{-R}" class="lead"/></g>
{''.join(dots)}
<circle r="4" class="core"/>
</svg>{cap}
<div class="cap"><i style="background:#c8702a"></i>AI ≥ {HIT_SCORE}<i style="background:#d4a373"></i>其他　越靠中心越相關</div>
</div></body></html>"""

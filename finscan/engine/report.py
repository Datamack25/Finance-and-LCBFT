"""Rapport HTML autonome (un fichier, sans dépendance externe hormis les
polices Google) : une société, ou la comparaison d'un portefeuille."""
from __future__ import annotations

import datetime as dt
from html import escape

from .fields import CHARGES, FORMAT_NAMES, LABELS
from .fmt import growth, money, number, pct, ratio, symbol, variation

KEY_FIGURES = {
    "PCG": ["revenue", "ebit", "financial_income", "net_income", "equity", "total_assets", "financial_debt_total", "liquid"],
    "BANK": ["pnb", "fee_income", "general_expenses", "net_income", "equity", "total_assets", "client_funds", "safeguarded"],
    "US": ["revenue", "gross_profit", "ebit", "net_income", "cfo", "fcf", "equity", "total_assets", "net_debt"],
    "IFRS": ["revenue", "gross_profit", "ebit", "ebitda", "net_income", "cfo", "fcf", "equity", "total_assets", "net_debt"],
}
EXTRA_LABELS = {
    "revenue": "Chiffre d'affaires", "ebitda": "EBITDA / EBE", "liquid": "Trésorerie et placements",
    "financial_debt_total": "Dettes financières totales", "net_debt": "Dette nette (− = trésorerie nette)",
    "fcf": "Free cash-flow", "general_expenses": "Charges générales d'exploitation", "net_income_calc": "Résultat recalculé",
}
STATEMENT_GROUPS = [
    ("Bilan — actif", ["intangible", "tangible", "financial_assets", "lt_securities", "fixed_assets", "inventories", "receivables",
                       "other_receivables", "interbank_assets", "other_assets", "marketable_securities", "cash", "prepaid",
                       "current_assets", "total_assets"]),
    ("Bilan — passif", ["share_capital", "share_premium", "reserves", "retained_carry", "net_income_bs", "regulated_prov", "minority", "equity",
                        "provisions", "financial_debt", "commercial_paper", "interbank_debt", "client_funds", "customer_advances",
                        "payables", "tax_social_debts", "other_liabilities", "deferred_income", "current_liabilities",
                        "total_liabilities", "total_liabilities_equity"]),
    ("Compte de résultat", ["revenue", "operating_revenue_total", "interest_income", "interest_expense", "fee_income", "fee_expense",
                            "pnb", "cogs", "gross_profit", "purchases", "external_charges", "taxes", "wages", "social_charges",
                            "personnel", "rd", "sga", "other_opex", "d_and_a", "provisions_charge", "operating_expenses_total",
                            "general_expenses", "rbe", "cost_of_risk", "ebitda", "ebit", "financial_income", "financial_expense",
                            "other_income", "exceptional_income", "exceptional_expense", "pretax", "income_tax", "net_income",
                            "eps_basic", "eps_diluted"]),
    ("Flux de trésorerie", ["cfo", "d_and_a_cf", "sbc", "capex", "cfi", "dividends_paid", "buybacks", "debt_repaid", "cff", "fcf", "taxes_paid"]),
    ("Fonds de la clientèle (annexe)", ["safeguarded", "acquisition_accounts", "reserve_accounts"]),
]


LOWER_IS_BETTER = CHARGES | {"financial_debt", "financial_debt_total", "net_debt", "interbank_debt", "commercial_paper",
                              "general_expenses", "cost_of_risk", "income_tax"}


def label(key: str) -> str:
    return EXTRA_LABELS.get(key) or LABELS.get(key, key)


CSS = """
:root{--paper:#ffffff;--bg:#f3f5f8;--ink:#17202f;--muted:#5a6475;--rule:#d9dee6;--navy:#1f3a5f;
--good:#11765f;--warn:#a55b06;--bad:#b42318;--soft:#e8edf4}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#151b26;--bg:#0f141c;--ink:#e6eaf0;--muted:#9aa4b4;
--rule:#2b3445;--navy:#8fb3e0;--good:#4cc3a2;--warn:#e3a14a;--bad:#f2786b;--soft:#1d2533}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "IBM Plex Sans",system-ui,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1040px;margin:0 auto;padding:40px 24px 80px}
h1,h2,h3{font-family:"Source Serif 4",Georgia,serif;font-weight:600;letter-spacing:-.01em;margin:0}
h1{font-size:34px;line-height:1.15}
h2{font-size:22px;margin:44px 0 14px;padding-top:18px;border-top:2px solid var(--ink)}
h3{font-size:17px;margin:22px 0 8px}
.meta{color:var(--muted);margin:8px 0 0}
.meta span{margin-right:18px;white-space:nowrap}
.verdict{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:28px 0 8px;background:var(--paper);border:1px solid var(--rule)}
.verdict>div{padding:22px 24px}
.verdict>div+div{border-left:1px solid var(--rule)}
.v-title{color:var(--muted);font-size:14px}
.v-score{font-family:"Source Serif 4",Georgia,serif;font-size:52px;line-height:1;margin:6px 0 2px}
.v-score small{font-size:20px;color:var(--muted)}
.v-label{font-weight:600;font-size:17px}
.scale{position:relative;height:8px;margin:16px 0 4px;border-radius:4px}
.scale.h{background:linear-gradient(90deg,var(--bad),var(--warn) 45%,var(--good) 75%)}
.scale.r{background:linear-gradient(90deg,var(--good),var(--warn) 45%,var(--bad) 80%)}
.scale i{position:absolute;top:-6px;width:4px;height:20px;background:var(--ink);border-radius:2px;transform:translateX(-2px)}
.scale-legend{display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}
ul.insights{padding-left:20px;margin:8px 0}
ul.insights li{margin:4px 0}
table{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--rule);font-size:14px}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule)}
th{font-weight:600;background:var(--soft)}
td.num,th.num{text-align:right;white-space:nowrap}
tr.total td{font-weight:600}
.chip{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12.5px;font-weight:600;white-space:nowrap}
.c-bon,.c-ok,.c-faible-r,.c-atténuant{background:color-mix(in srgb,var(--good) 15%,transparent);color:var(--good)}
.c-moyen,.c-modéré,.c-corrigé,.c-incomplet{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn)}
.c-faible,.c-élevé,.c-alerte{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}
.c-info,.c-n\\/d{background:var(--soft);color:var(--muted)}
.signal{background:var(--paper);border:1px solid var(--rule);border-left:4px solid var(--muted);padding:14px 18px;margin:10px 0}
.signal.élevé{border-left-color:var(--bad)}.signal.modéré{border-left-color:var(--warn)}.signal.faible{border-left-color:#c9a227}
.signal.atténuant{border-left-color:var(--good)}
.signal h4{margin:0 0 6px;font-size:15.5px}
.signal p{margin:4px 0;max-width:78ch}
.signal .k{color:var(--muted)}
.pillars{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.pillar{background:var(--paper);border:1px solid var(--rule);padding:14px 16px}
.pillar b{display:block;font-size:22px;font-family:"Source Serif 4",Georgia,serif}
.bar{height:6px;background:var(--soft);margin-top:8px}.bar>span{display:block;height:6px;background:var(--navy)}
.note{color:var(--muted);font-size:13.5px;max-width:80ch}
.g{display:block;font-size:12px;font-weight:600}.g.up{color:var(--good)}.g.down{color:var(--bad)}.g.flat{color:var(--muted)}
td.spark{width:96px;padding:6px 8px}td.spark svg{display:block}
.sources td{font-size:13.5px}
.evo-wrap{background:var(--paper);border:1px solid var(--rule);border-top:0;padding:18px 22px 10px;margin:0 0 8px}
.evo-wrap h3{margin:0 0 6px}
svg.evo{width:100%;height:auto;display:block;font-family:"IBM Plex Sans",system-ui,sans-serif}
svg.evo .grid{stroke:var(--rule);stroke-width:1}
svg.evo .zero{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
svg.evo .ax{fill:var(--muted);font-size:13px}
svg.evo .ax.ni{fill:var(--good)}
svg.evo .yr{fill:var(--ink);font-size:15px;font-weight:600}
svg.evo .cbar{fill:color-mix(in srgb,var(--navy) 55%,var(--paper))}
svg.evo .val{fill:var(--ink);font-size:14px;font-weight:600}
svg.evo .gr{font-size:12.5px;font-weight:600}
svg.evo .gr.up{fill:var(--good)}svg.evo .gr.down{fill:var(--bad)}svg.evo .gr.flat{fill:var(--muted)}
svg.evo .line{fill:none;stroke:var(--good);stroke-width:3}
svg.evo .pt{fill:var(--good);stroke:var(--paper);stroke-width:2}
svg.evo .pt.neg{fill:var(--bad)}
svg.evo .nival{fill:var(--good);font-size:13px;font-weight:600}
svg.evo .nival.negt{fill:var(--bad)}
svg.evo .lg{fill:var(--muted);font-size:13px}
.footer{margin-top:48px;color:var(--muted);font-size:13px;border-top:1px solid var(--rule);padding-top:14px}
@media (max-width:700px){main{padding:24px 16px}.verdict{grid-template-columns:1fr}.verdict>div+div{border-left:0;border-top:1px solid var(--rule)}
table{display:block;overflow-x:auto}h1{font-size:27px}}
@media print{body{background:#fff}.signal,table,.verdict{break-inside:avoid}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Sans:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,600&display=swap" rel="stylesheet">')


def _chip(text: str, cls: str | None = None) -> str:
    return f'<span class="chip c-{escape(cls or text)}">{escape(text)}</span>' if text else ""


def _scale(value: float, kind: str) -> str:
    return f'<div class="scale {kind}"><i style="left:{max(0, min(100, value)):.0f}%"></i></div>'


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    import math
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def _short(v: float, sym: str) -> str:
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} Md"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} M"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f} k"
    else:
        s = f"{v:.0f} "
    return (s.replace(".", ",") + sym).replace("-", "−")


def evolution_svg(f, ex) -> str:
    """Grand graphique : chiffre d'affaires (barres, axe gauche) et résultat net
    (courbe, axe droit) pour toutes les années disponibles."""
    rev_key = "pnb" if ex.fmt == "BANK" else "revenue"
    periods = list(reversed(f.periods))
    rev = [f.get(rev_key, p) for p in periods]
    ni = [f.get("net_income", p) for p in periods]
    if not any(v is not None for v in rev + ni):
        return ""
    sym = symbol(ex.currency)
    W, H = 960, 400
    ml, mr, mt, mb = 70, 70, 56, 64
    pw, ph = W - ml - mr, H - mt - mb
    n = len(periods)
    slot = pw / max(n, 1)
    bw = min(96, slot * 0.46)

    rv = [v for v in rev if v is not None]
    lt = _nice_ticks(min(0, min(rv, default=0)), max(rv, default=1) or 1)
    nv = [v for v in ni if v is not None]
    rt = _nice_ticks(min(0, min(nv, default=0)), max(max(nv, default=1), 0) or 1)

    def yl(v):
        return mt + ph - (v - lt[0]) / (lt[-1] - lt[0]) * ph

    def yr(v):
        return mt + ph - (v - rt[0]) / (rt[-1] - rt[0]) * ph

    o = [f'<svg class="evo" viewBox="0 0 {W} {H}" role="img" aria-label="Évolution du chiffre d\'affaires et du résultat net">']
    # grille et axes
    for t in lt:
        y = yl(t)
        o.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        o.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" class="ax">{escape(_short(t, sym))}</text>')
    for t in rt:
        o.append(f'<text x="{W - mr + 10}" y="{yr(t) + 4:.1f}" class="ax ni">{escape(_short(t, sym))}</text>')
    if rt[0] < 0:
        o.append(f'<line x1="{ml}" x2="{W - mr}" y1="{yr(0):.1f}" y2="{yr(0):.1f}" class="zero"/>')
    # barres de CA + croissance
    for i, p in enumerate(periods):
        cx = ml + slot * (i + 0.5)
        o.append(f'<text x="{cx:.1f}" y="{H - mb + 24}" text-anchor="middle" class="yr">{escape(p)}</text>')
        v = rev[i]
        if v is None:
            continue
        y0, y1 = yl(max(0, lt[0])), yl(v)
        top, hgt = min(y0, y1), abs(y1 - y0)
        o.append(f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(hgt, 1):.1f}" rx="3" class="cbar"/>')
        o.append(f'<text x="{cx:.1f}" y="{top - 22:.1f}" text-anchor="middle" class="val">{escape(_short(v, sym))}</text>')
        q = f.prev(p)
        g_ = growth(v, f.get(rev_key, q)) if q else None
        if g_ is not None:
            cls = "up" if g_ > 0.005 else "down" if g_ < -0.005 else "flat"
            o.append(f'<text x="{cx:.1f}" y="{top - 7:.1f}" text-anchor="middle" class="gr {cls}">{escape(pct(g_))}</text>')
    # courbe du résultat net
    pts = [(ml + slot * (i + 0.5), yr(v), v) for i, v in enumerate(ni) if v is not None]
    if len(pts) > 1:
        o.append('<polyline class="line" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts) + '"/>')
    for i, v in enumerate(ni):
        if v is None:
            continue
        x, y = ml + slot * (i + 0.5), yr(v)
        cls = "pt neg" if v < 0 else "pt"
        q = f.prev(periods[i])
        g_ = growth(v, f.get("net_income", q)) if q else None
        lab = _short(v, sym) + (f" ({pct(g_)})" if g_ is not None else "")
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" class="{cls}"/>')
        o.append(f'<text x="{x + 10:.1f}" y="{y + 18:.1f}" class="nival{" negt" if v < 0 else ""}">{escape(lab)}</text>')
    # légende
    what = "PNB" if ex.fmt == "BANK" else "Chiffre d'affaires"
    o.append(f'<rect x="{ml}" y="14" width="14" height="14" rx="2" class="cbar"/><text x="{ml + 22}" y="26" class="lg">{what} (axe de gauche)</text>')
    o.append(f'<line x1="{ml + 250}" x2="{ml + 278}" y1="21" y2="21" class="line"/><circle cx="{ml + 264}" cy="21" r="5" class="pt"/>'
             f'<text x="{ml + 286}" y="26" class="lg">Résultat net (axe de droite)</text>')
    o.append("</svg>")
    return "".join(o)


def _verdict(res: dict) -> str:
    h, a = res["health"], res["aml"]
    hs = h["score"]
    return f"""
<section class="verdict" aria-label="Synthèse">
 <div><div class="v-title">Santé financière</div>
  <div class="v-score">{'—' if hs is None else int(hs)}<small> / 100</small></div>
  <div class="v-label">{escape(h['label'] or 'Données insuffisantes')}</div>
  {_scale(hs or 0, 'h')}<div class="scale-legend"><span>Critique</span><span>Fragile</span><span>Correcte</span><span>Solide</span></div></div>
 <div><div class="v-title">Risque LCB-FT indicatif</div>
  <div class="v-score">{a['score']}<small> / 100</small></div>
  <div class="v-label">{escape(a['level'])}</div>
  {_scale(a['score'], 'r')}<div class="scale-legend"><span>Faible</span><span>Modéré</span><span>Élevé</span></div></div>
</section>"""


def _table(headers: list[str], rows: list[list[str]], num_cols: set[int] = frozenset(), total_rows: set[int] = frozenset(),
           widths: list[int] | None = None) -> str:
    th = "".join(f'<th class="{"num" if i in num_cols else ""}">{escape(h)}</th>' for i, h in enumerate(headers))
    cg = ""
    if widths:
        cg = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
    body = []
    for r_i, r in enumerate(rows):
        tds = "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(r))
        body.append(f'<tr class="{"total" if r_i in total_rows else ""}">{tds}</tr>')
    fixed = ' style="table-layout:fixed"' if widths else ""
    return f"<table{fixed}>{cg}<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def dossier_sections(d, res: dict) -> str:
    ex, k, f = d.ex, d.kyc, res["fin"]
    cur = ex.currency
    parts = []
    parts.append(_verdict(res))
    evo = evolution_svg(f, ex)
    if evo:
        what = "du PNB" if ex.fmt == "BANK" else "du chiffre d'affaires"
        parts.append(f"<section class='evo-wrap'><h3>Évolution {what} et du résultat net</h3>{evo}"
                     f"<p class='note'>Exercices présents dans les documents : {escape(', '.join(reversed(f.periods)))}. "
                     "Au-dessus de chaque barre : montant et variation par rapport à l'exercice précédent.</p></section>")

    # Profil : activité, pays, vigilance
    from .summary import describe_activity, geography, vigilance_level
    geo = geography(d)
    vig, vig_why = vigilance_level(res, d)
    geo_txt = " | ".join(f"<b>{escape(g_['pays'])}</b> ({escape(g_['rôle'])})" +
                         (f" {_chip(g_['risque'], 'élevé')}" if g_["risque"] != "standard" else "") for g_ in geo) or "non déterminés"
    parts.append(f"<h2>Profil de la société</h2><p><b>Activité.</b> {escape(describe_activity(d, res))}</p>"
                 f"<p><b>Pays d'opération.</b> {geo_txt}</p>"
                 f"<p><b>Vigilance LCB-FT suggérée :</b> {escape(vig)} — {escape(vig_why)}</p>")

    # Synthèse
    top = [s for s in res["aml"]["signals"] if s["niveau"] in ("élevé", "modéré")][:4]
    parts.append("<h2>Ce qu'il faut retenir</h2>")
    parts.append("<h3>Situation financière</h3><ul class='insights'>" +
                 "".join(f"<li>{escape(x)}</li>" for x in res["health"]["insights"]) + "</ul>")
    if top:
        parts.append("<h3>Points de vigilance LCB-FT</h3><ul class='insights'>" +
                     "".join(f"<li>{_chip(s['niveau'])} {escape(s['signal'])} — {escape(s['constat'])}</li>" for s in top) + "</ul>")

    periods = list(reversed(f.periods))  # ordre chronologique
    sym = symbol(cur)

    def gcell(v_txt: str, gval: float | None, inverse: bool = False) -> str:
        if gval is None:
            return v_txt
        good = gval < -0.005 if inverse else gval > 0.005
        bad = gval > 0.005 if inverse else gval < -0.005
        cls = "up" if good else "down" if bad else "flat"
        return f"{v_txt}<span class='g {cls}'>{pct(gval)}</span>"

    def series_cells(key: str, fmtv) -> list[str]:
        cells = []
        inverse = key in LOWER_IS_BETTER
        for p in periods:
            v = f.get(key, p)
            q = f.prev(p)
            cells.append(gcell(fmtv(v), growth(v, f.get(key, q)) if q else None, inverse))
        return cells

    def cagr_cell(key: str) -> str:
        annual = [p for p in f.periods if f.months.get(p, 12) == 12 and f.get(key, p) is not None]
        if len(annual) < 3:
            return "—"
        a, b = f.get(key, annual[0]), f.get(key, annual[-1])
        yrs = int(annual[0][:4]) - int(annual[-1][:4])
        if yrs <= 0 or not b or b <= 0 or a <= 0:
            return "—"
        return pct((a / b) ** (1 / yrs) - 1)

    def spark(key: str) -> str:
        pts = [(i, f.get(key, p)) for i, p in enumerate(periods) if f.get(key, p) is not None]
        if len(pts) < 2:
            return ""
        lo, hi = min(v for _, v in pts), max(v for _, v in pts)
        span = (hi - lo) or 1
        w, h = 84, 24
        n = max(len(periods) - 1, 1)
        coords = " ".join(f"{2 + i * (w - 4) / n:.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}" for i, v in pts)
        last = pts[-1]
        lx, ly = 2 + last[0] * (w - 4) / n, h - 3 - (last[1] - lo) / span * (h - 6)
        return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' aria-hidden='true'><polyline points='{coords}' fill='none' "
                f"stroke='var(--navy)' stroke-width='1.6'/><circle cx='{lx:.1f}' cy='{ly:.1f}' r='2.4' fill='var(--navy)'/></svg>")

    # Chiffres clés
    rows = []
    for key in KEY_FIGURES[ex.fmt]:
        if all(f.get(key, p) is None for p in periods):
            continue
        rows.append([escape(label(key))] + series_cells(key, lambda v: money(v, cur)) + [cagr_cell(key), spark(key)])
    parts.append("<h2>Chiffres clés et croissance</h2>")
    parts.append(f"<p class='note'>{len(periods)} période(s) : {escape(', '.join(periods))}. Sous chaque montant, la variation par rapport "
                 f"à l'exercice précédent. TCAM : taux de croissance annuel moyen sur la période disponible (3 exercices minimum). "
                 f"Durée des flux du dernier exercice : {escape(ex.period_label)}. Montants en {sym}.</p>")
    hdrs = ["Poste"] + periods + ["TCAM", "Tendance"]
    tbl = _table(hdrs, rows, set(range(1, len(periods) + 2)))
    parts.append(tbl.replace("<td class=\"\"><svg", "<td class=\"spark\"><svg"))

    # Ratios
    parts.append("<h2>Ratios d'analyse</h2>")
    groups: dict[str, list] = {}
    for r in res["ratios"]:
        groups.setdefault(r["groupe"], []).append(r)
    for gname, items in groups.items():
        rows = []
        for r in items:
            vals = r.get("values", {})
            if all(vals.get(p) is None for p in periods):
                continue
            rows.append([escape(r["ratio"]) + (f"<div class='note'>{escape(r['note'])}</div>" if r["note"] else "")] +
                        [ratio(vals.get(p), r["format"]) for p in periods] + [_chip(r["appréciation"])])
        if rows:
            parts.append(f"<h3>{escape(gname)}</h3>" + _table(["Ratio"] + periods + ["Appréciation (dernier exercice)"], rows,
                                                               set(range(1, len(periods) + 1))))

    # Santé
    h = res["health"]
    parts.append("<h2>Santé financière</h2><div class='pillars'>")
    for name, sc in h["pillars"].items():
        parts.append(f"<div class='pillar'>{escape(name)}<b>{number(sc, 1)} / 25</b><div class='bar'><span style='width:{sc * 4:.0f}%'></span></div></div>")
    parts.append("</div>")
    if h["altman"]:
        al = h["altman"]
        parts.append(f"<p class='note'>Z-score d'Altman (variante Z'' pour sociétés non industrielles) : <b>{number(al['z'], 2)}</b> — zone "
                     f"{escape(al['zone'])}. Seuils : &gt; 2,6 sûre, 1,1 à 2,6 grise, &lt; 1,1 détresse. Peu discriminant pour une holding "
                     "dont l'actif est surtout financier.</p>")

    # LCB-FT
    parts.append("<h2>Analyse LCB-FT</h2>")
    parts.append("<p class='note'>Signaux d'attention tirés des comptes et des actes joints. Ils orientent les diligences ; "
                 "ils ne valent ni soupçon ni conclusion. Listes de pays : mise à jour du "
                 f"{escape(res['aml'].get('lists_date') or '—')}.</p>")
    for s in res["aml"]["signals"]:
        parts.append(f"""<div class="signal {escape(s['niveau'])}"><h4>{_chip(s['niveau'])} {escape(s['signal'])}</h4>
<p>{escape(s['constat'])}</p><p><span class="k">Pourquoi c'est pertinent :</span> {escape(s['pourquoi'])}</p>
<p><span class="k">Diligence suggérée :</span> {escape(s['diligence'])}</p><p class="note">{escape(s['catégorie'])}</p></div>""")

    # KYC
    parts.append("<h2>Fiche d'identification</h2>")
    ident = [("Dénomination", k.name), ("SIREN", f"{k.siren}{' (clé valide)' if k.siren_valid else ' (à vérifier)' if k.siren else ''}"),
             ("Forme juridique", k.legal_form), ("Capital", money(k.capital, cur, compact=False) if k.capital else ""),
             ("Siège", k.address), ("Code APE", k.ape), ("Activité déclarée", k.activity or ", ".join(k.sector_flags)),
             ("Greffe", k.registry), ("Clôture", k.closing),
             ("Commissaires aux comptes", ", ".join(k.auditors) or "—"), ("Opinion d'audit", k.audit_opinion),
             ("Statut réglementé", ", ".join(k.regulated) or "—"), ("Effectif", number(k.headcount) if k.headcount else "—")]
    parts.append(_table(["Élément", "Valeur lue"], [[escape(a), escape(str(b or "—"))] for a, b in ident]))
    if k.associates:
        divmap = {p.name: p for p in k.dividends_by_person}
        rows = [[escape(p.name), number(p.parts), ratio((p.pct or 0) / 100, "%") if p.pct is not None else "—"] for p in k.associates]
        parts.append("<h3>Associés</h3>" + _table(["Associé", "Parts", "% du capital"], rows, {1, 2}))
    if k.dividends_by_person:
        rows = [[escape(p.name), money(p.dividend, cur, compact=False), ratio((p.pct or 0) / 100, "%") if p.pct is not None else "—"]
                for p in k.dividends_by_person]
        parts.append("<h3>Dividendes décidés par bénéficiaire</h3>" + _table(["Bénéficiaire", "Montant", "% de la distribution"], rows, {1, 2}))
    if k.managers:
        parts.append("<h3>Dirigeants</h3>" + _table(["Nom", "Fonction"], [[escape(p.name), escape(p.role)] for p in k.managers]))
    if k.subsidiaries:
        rows = [[escape(s.name), escape(s.form), escape(s.siren), ratio((s.pct or 0) / 100, "%") if s.pct is not None else "—",
                 escape(f"{s.city} ({s.country})")] for s in k.subsidiaries]
        parts.append("<h3>Filiales et participations</h3>" + _table(["Entité", "Forme", "SIREN", "Détention", "Localisation"], rows, {3}))
    if geo:
        parts.append("<h3>Pays d'opération et classement</h3>" +
                     _table(["Pays / zone", "Rôle", "Classement"], [[escape(g_["pays"]), escape(g_["rôle"]),
                                                                    _chip(g_["risque"], "ok" if g_["risque"] == "standard" else "élevé")] for g_ in geo]))
    scr = res["aml"]["screening"]
    if scr:
        parts.append("<h3>Noms à filtrer (gel des avoirs, sanctions, PPE)</h3>" +
                     _table(["Nom", "Qualité"], [[escape(r["nom"]), escape(r["qualité"])] for r in scr]))

    # États
    parts.append("<h2>États financiers retenus</h2>")
    parts.append("<p class='note'>Sous chaque montant : variation par rapport à l'exercice précédent.</p>")
    for title, keys in STATEMENT_GROUPS:
        rows = []
        for key in keys:
            if key not in f.v:
                continue
            if all(f.get(key, p) is None for p in periods):
                continue
            is_eps = key.startswith("eps")
            fmtv = (lambda v: number(v, 2)) if is_eps else (lambda v: money(v, cur, compact=False))
            rows.append([escape(label(key))] + series_cells(key, fmtv) + [_chip(f.origin.get(key, ""), "info")])
        if rows:
            parts.append(f"<h3>{escape(title)}</h3>" + _table(["Poste"] + periods + ["Origine"], rows, set(range(1, len(periods) + 1))))
    if ex.breakdowns:
        for title, items in ex.breakdowns.items():
            tot = sum(v for _, v in items) or 1
            rows = [[escape(n), money(v * ex.unit, cur), ratio(v / tot, "%")] for n, v in items]
            parts.append(f"<h3>{escape(title)} (dernier exercice)</h3>" + _table(["Segment", "Montant", "Part"], rows, {1, 2}))

    # Contrôles
    parts.append("<h2>Contrôles et traçabilité</h2>")
    rows = [[escape(c["contrôle"]), _chip(c["statut"]), escape(c["détail"])] for c in res["controls"]]
    parts.append(_table(["Contrôle", "Statut", "Détail"], rows))
    if f.notes:
        parts.append("<h3>Corrections automatiques</h3><ul class='insights'>" + "".join(f"<li>{escape(n)}</li>" for n in f.notes) + "</ul>")
    srcs = getattr(d, "sources", None)
    if srcs:
        parts.append("<h3>Documents utilisés</h3>" + _table(["Fichier", "Périodes lues", "Format"],
                     [[escape(x["fichier"]), escape(x["périodes"]), escape(FORMAT_NAMES.get(x["format"], x["format"]))] for x in srcs]))
        parts.append("<p class='note'>Quand une année figure dans plusieurs documents, le plus récent l'emporte "
                     "(comparatifs éventuellement retraités).</p>")
    src = f"{d.n_pages} pages lues"
    if d.ocr_pages:
        src += f", dont {len(d.ocr_pages)} par OCR"
    parts.append(f"<p class='note'>{src}. Format retenu : {escape(FORMAT_NAMES[ex.fmt])}.</p>")
    return "\n".join(parts)


DISCLAIMER = ("Analyse produite automatiquement à partir des documents fournis, après validation de l'analyste. "
              "Les signaux LCB-FT sont des indicateurs d'orientation des diligences au sens de l'approche par les risques "
              "(art. L.561-4-1 CMF) ; ils ne constituent ni une qualification de soupçon ni un conseil en investissement.")


def render_dossier(d, res: dict, author: str = "") -> str:
    k, ex = d.kyc, d.ex
    meta = [f"<span>{escape(FORMAT_NAMES[ex.fmt])}</span>"]
    if k.siren:
        meta.append(f"<span>SIREN {escape(k.siren)}</span>")
    if k.closing:
        meta.append(f"<span>Exercice clos le {escape(k.closing)}</span>")
    body = dossier_sections(d, res)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(d.name)} – analyse</title>{FONTS}<style>{CSS}</style></head><body><main>
<h1>{escape(d.name)}</h1><p class="meta">{''.join(meta)}</p>
{body}
<p class="footer">{escape(DISCLAIMER)}<br>Généré le {dt.date.today().strftime('%d/%m/%Y')}{(' par ' + escape(author)) if author else ''}.</p>
</main></body></html>"""


def render_portfolio(items: list[tuple]) -> str:
    """items : liste de (dossier, résultats)."""
    rows = []
    for d, res in items:
        f, h, a = res["fin"], res["health"], res["aml"]
        cur = d.ex.currency
        high = sum(1 for s in a["signals"] if s["niveau"] == "élevé")
        rows.append([escape(d.name), escape(d.ex.fmt), escape(", ".join(reversed(f.periods))), money(f.get("revenue"), cur),
                     money(f.get("net_income"), cur), money(f.get("equity"), cur),
                     f"{'—' if h['score'] is None else int(h['score'])} {_chip(h['label'] or '', {'Solide': 'bon', 'Correcte': 'moyen'}.get(h['label'] or '', 'faible'))}",
                     f"{a['score']} {_chip(a['level'], {'Faible': 'ok', 'Modéré': 'modéré', 'Élevé': 'élevé'}[a['level']])}", str(high)])
    table = _table(["Société", "Format", "Périodes", "CA / PNB", "Résultat net", "Capitaux propres", "Santé", "LCB-FT", "Signaux élevés"],
                   rows, {3, 4, 5})
    details = "".join(f"<h2>{escape(d.name)}</h2>" + "<ul class='insights'>" +
                      "".join(f"<li>{escape(x)}</li>" for x in res["health"]["insights"]) +
                      "".join(f"<li>{_chip(s['niveau'])} {escape(s['signal'])}</li>" for s in res["aml"]["signals"]
                              if s["niveau"] in ("élevé", "modéré")) + "</ul>" for d, res in items)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comparaison du portefeuille</title>{FONTS}<style>{CSS}</style></head><body><main>
<h1>Comparaison de {len(items)} société{'s' if len(items) > 1 else ''}</h1>
<p class="meta"><span>Généré le {dt.date.today().strftime('%d/%m/%Y')}</span></p>
<h2>Vue d'ensemble</h2>{table}{details}
<p class="footer">{escape(DISCLAIMER)}</p></main></body></html>"""

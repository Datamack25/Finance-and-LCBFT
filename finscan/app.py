"""FinScan LCB-FT — analyse financière pluriannuelle et lecture LCB-FT de sociétés.

Lancer en local :  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from engine.company import Company, View, company_from_json, company_key, company_to_json, merge, new_company, period_sort_key
from engine.dossier import Dossier, build_dossier
from engine.export_docx import build_docx
from engine.export_xlsx import build_xlsx
from engine.fields import FORMAT_NAMES, LABELS, SPECS
from engine.fmt import growth, money, pct, ratio, symbol
from engine.ingest import OCR_AVAILABLE
from engine.kyc import Person
from engine.report import KEY_FIGURES, LOWER_IS_BETTER, label, render_dossier, render_portfolio

st.set_page_config(page_title="FinScan LCB-FT", page_icon="🔎", layout="wide")

st.markdown("""
<style>
h1, h2, h3 {font-family: "Source Serif 4", Georgia, serif; letter-spacing: -.01em}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums}
.sig {border-left: 4px solid #8a94a6; padding: 10px 14px; margin: 8px 0; background: rgba(127,127,127,.06)}
.sig.élevé {border-color: #b42318} .sig.modéré {border-color: #a55b06} .sig.faible {border-color: #c9a227}
.sig.atténuant {border-color: #11765f}
.sig p {margin: 4px 0} .sig .k {opacity: .7}
</style>""", unsafe_allow_html=True)

LEVEL_ICON = {"élevé": "🔴", "modéré": "🟠", "faible": "🟡", "info": "⚪", "atténuant": "🟢"}
STATUS_ICON = {"ok": "✅", "corrigé": "🛠️", "alerte": "⚠️", "incomplet": "➖"}
NAVY, SKY = "#1f3a5f", "#9fb3cc"


# ---------------------------------------------------------------------------
# Accès protégé (facultatif) : définir APP_PASSWORD dans les secrets
# ---------------------------------------------------------------------------
def _password() -> str | None:
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


pwd = _password()
if pwd and not st.session_state.get("auth"):
    st.title("FinScan LCB-FT")
    entered = st.text_input("Mot de passe", type="password")
    if entered and entered == pwd:
        st.session_state["auth"] = True
        st.rerun()
    elif entered:
        st.error("Mot de passe incorrect.")
    st.stop()

ss = st.session_state
ss.setdefault("docs", {})       # id document -> Dossier
ss.setdefault("pdf", {})        # id document -> octets du PDF (aperçu des pages)
ss.setdefault("companies", {})  # id société -> Company


def attach(d: Dossier) -> None:
    """Range un document dans la société correspondante (même SIREN ou même nom)."""
    ss.docs[d.id] = d
    if any(d.id in c.doc_ids for c in ss.companies.values()):
        return
    key = company_key(d)
    for c in ss.companies.values():
        if c.key == key:
            c.doc_ids.append(d.id)
            return
    c = new_company(d)
    while c.id in ss.companies:
        c.id += "x"
    ss.companies[c.id] = c


@st.cache_data(show_spinner=False, max_entries=60)
def _read_pdf(data: bytes, name: str, fmt: str | None, ocr: bool, dpi: int) -> str:
    """Lecture + extraction mises en cache : relire le même PDF est instantané.
    Renvoie le JSON du document ; chaque session en reçoit une copie modifiable."""
    return build_dossier(data, name, fmt=fmt, ocr=ocr, dpi=dpi).to_json()


# ---------------------------------------------------------------------------
# Barre latérale : import
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Documents")
    files = st.file_uploader("États financiers, liasses, rapports annuels, PV d'AG (PDF) ou dossiers enregistrés (JSON)",
                             type=["pdf", "json"], accept_multiple_files=True)
    with st.expander("Options de lecture"):
        ocr = st.toggle("OCR des pages scannées", value=True, disabled=not OCR_AVAILABLE,
                        help="Tesseract lit les pages sans texte (scans). Compter quelques secondes par page.")
        dpi = st.select_slider("Résolution OCR", options=[200, 250, 300], value=300)
        fmt_choice = st.selectbox("Format des comptes", ["Détection automatique"] + list(FORMAT_NAMES.values()))
    if not OCR_AVAILABLE:
        st.caption("OCR indisponible : installez Tesseract (voir README).")
    run = st.button("Analyser", type="primary", use_container_width=True, disabled=not files)
    st.divider()
    st.caption("Pour couvrir 3 exercices ou plus, déposez les comptes de plusieurs années d'une même société : "
               "ils sont regroupés automatiquement (même SIREN ou même dénomination). "
               "Enregistrez la société (onglet Export) pour retrouver vos corrections.")

if run and files:
    forced = None if fmt_choice == "Détection automatique" else next(k for k, v in FORMAT_NAMES.items() if v == fmt_choice)
    for up in files:
        data = up.getvalue()
        if up.name.lower().endswith(".json"):
            try:
                comp, docs = company_from_json(data.decode("utf-8"))
                for d in docs:
                    ss.docs[d.id] = d
                if comp:
                    ss.companies[comp.id] = comp
                else:
                    for d in docs:
                        attach(d)
            except Exception as e:  # noqa: BLE001
                st.sidebar.error(f"{up.name} : dossier illisible ({e}).")
            continue
        with st.sidebar.status(f"Lecture de {up.name}…", expanded=False) as status:
            try:
                d = Dossier.from_json(_read_pdf(data, up.name, forced, ocr, dpi))
                ss.pdf[d.id] = data
                attach(d)
                status.update(label=f"{up.name} : {', '.join(d.ex.periods) or 'aucune année lue'}", state="complete")
            except Exception as e:  # noqa: BLE001
                status.update(label=f"{up.name} : lecture impossible ({e})", state="error")


# ---------------------------------------------------------------------------
# Écran d'accueil
# ---------------------------------------------------------------------------
st.title("FinScan LCB-FT")
if not ss.companies:
    st.markdown(
        "Déposez dans la barre latérale les comptes d'une ou plusieurs sociétés : liasses fiscales (2033 / 2050), comptes "
        "sociaux, comptes consolidés **IFRS** (français ou anglais), états **US GAAP** (10-K, 10-Q), comptes d'établissements "
        "de paiement, procès-verbaux d'assemblée. Les PDF scannés sont lus par OCR.\n\n"
        "Pour chaque société, vous obtenez :\n"
        "- les états financiers **sur tous les exercices disponibles**, avec la **croissance annuelle** de chaque poste et le TCAM ;\n"
        "- les ratios d'un investisseur, année par année ;\n"
        "- un score de santé financière sur 100 et le Z-score d'Altman ;\n"
        "- une lecture LCB-FT : actionnariat et bénéficiaires effectifs, distributions, structure, géographie, secteur, audit — "
        "avec les diligences à mener ;\n"
        "- un rapport HTML autonome à archiver ou partager.\n\n"
        "Un rapport annuel présente en général 2 ou 3 exercices. Pour aller au-delà, ajoutez les comptes des années précédentes : "
        "ils sont fusionnés en une seule série.")
    st.info("Les documents restent dans la session : rien n'est stocké côté serveur après fermeture.")
    st.stop()


# ---------------------------------------------------------------------------
# Analyse de chaque société
# ---------------------------------------------------------------------------
views: dict[str, View] = {}
results: dict[str, dict] = {}
for cid, c in list(ss.companies.items()):
    if not any(i in ss.docs for i in c.doc_ids):
        ss.companies.pop(cid)
        continue
    try:
        views[cid] = merge(c, ss.docs)
        results[cid] = views[cid].analyse()
    except Exception as e:  # noqa: BLE001
        st.error(f"{c.name} : analyse impossible ({e}).")
ids = [i for i in ss.companies if i in results]


def scale_for(values: list[float | None]) -> tuple[float, str]:
    m = max((abs(v) for v in values if v is not None), default=0)
    if m >= 1e9:
        return 1e6, "millions"
    if m >= 1e7:
        return 1e3, "milliers"
    return 1.0, "unités"


def growth_frame(f, keys: list[str]) -> pd.DataFrame:
    periods = list(reversed(f.periods))
    rows = []
    for k in keys:
        if all(f.get(k, p) is None for p in periods):
            continue
        row = {"Poste": label(k)}
        for p in periods[1:]:
            q = f.prev(p)
            row[f"Δ {p}"] = growth(f.get(k, p), f.get(k, q)) if q else None
        annual = [p for p in f.periods if f.months.get(p, 12) == 12 and f.get(k, p) is not None]
        if len(annual) >= 3:
            a, b = f.get(k, annual[0]), f.get(k, annual[-1])
            yrs = int(annual[0][:4]) - int(annual[-1][:4])
            row["TCAM"] = (a / b) ** (1 / yrs) - 1 if yrs > 0 and b and b > 0 and a > 0 else None
        rows.append(row)
    return pd.DataFrame(rows)


def show_growth(df: pd.DataFrame) -> None:
    if df.empty or len(df.columns) <= 1:
        st.caption("Une seule période : la croissance apparaîtra dès que deux exercices seront disponibles.")
        return
    num_cols = [c for c in df.columns if c != "Poste"]
    st.dataframe(df.style.format({c: (lambda v: pct(v) if pd.notna(v) else "—") for c in num_cols})
                 .map(lambda v: "color:#11765f" if isinstance(v, float) and v > 0.005 else
                      ("color:#b42318" if isinstance(v, float) and v < -0.005 else ""), subset=num_cols),
                 hide_index=True, use_container_width=True)


def evolution_chart(f, keys: list[str], cur: str, title: str) -> go.Figure:
    """Premier poste en barres (avec sa croissance annuelle), les autres en courbes.
    Un poste beaucoup plus petit que le premier passe sur un axe secondaire."""
    periods = list(reversed(f.periods))
    fig = go.Figure()
    palette = ["#11765f", "#a55b06", "#b42318", "#6b7fa0"]
    series = [(k, [f.get(k, p) for p in periods]) for k in keys]
    series = [(k, ys) for k, ys in series if any(y is not None for y in ys)]
    if not series:
        return fig
    k0, y0 = series[0]
    texts = []
    for p in periods:
        q = f.prev(p)
        g_ = growth(f.get(k0, p), f.get(k0, q)) if q else None
        texts.append(pct(g_) if g_ is not None else "")
    sym_ = symbol(cur)

    def short(x):
        if x is None:
            return ""
        ax = abs(x)
        t = f"{x / 1e9:.1f} Md" if ax >= 1e9 else f"{x / 1e6:.1f} M" if ax >= 1e6 else f"{x / 1e3:.0f} k" if ax >= 1e3 else f"{x:.0f} "
        return (t + sym_).replace(".", ",")

    bar_txt = [f"<b>{short(y)}</b>" + (f"<br>{t}" if t else "") for y, t in zip(y0, texts)]
    fig.add_trace(go.Bar(x=periods, y=y0, name=label(k0), marker_color=SKY, text=bar_txt, textposition="outside",
                         textfont=dict(size=13, color=NAVY), cliponaxis=False))
    ref = max((abs(y) for y in y0 if y is not None), default=1) or 1
    use_y2 = False
    for i, (k, ys) in enumerate(series[1:]):
        small = max((abs(y) for y in ys if y is not None), default=0) < 0.25 * ref
        use_y2 = use_y2 or small
        hov = []
        for p in periods:
            q = f.prev(p)
            g_ = growth(f.get(k, p), f.get(k, q)) if q else None
            hov.append(short(f.get(k, p)) + (f" ({pct(g_)})" if g_ is not None else ""))
        fig.add_trace(go.Scatter(x=periods, y=ys, name=label(k), mode="lines+markers+text" if i == 0 else "lines+markers",
                                 yaxis="y2" if small else "y", text=hov if i == 0 else None,
                                 textposition="bottom center", textfont=dict(color=palette[i % len(palette)], size=12),
                                 line=dict(color=palette[i % len(palette)], width=3), marker=dict(size=9),
                                 customdata=hov, hovertemplate="%{x} : %{customdata}<extra>" + label(k) + "</extra>"))
    layout = dict(height=380, margin=dict(t=40, b=20, l=10, r=10), title=dict(text=title, font=dict(size=14)),
                  legend=dict(orientation="h", y=-0.15), yaxis=dict(title=symbol(cur)), xaxis=dict(type="category"), bargap=0.45)
    vals0 = [y for y in y0 if y is not None]
    if vals0:  # marge au-dessus des barres pour les étiquettes
        layout["yaxis"]["range"] = [min(0, min(vals0)) * 1.15, max(max(vals0), 0) * 1.25 or 1]
    if use_y2:
        others = [y for _, ys in series[1:] for y in ys if y is not None]
        lo, hi = min(0, min(others)), max(0, max(others))
        # courbe placée dans la moitié basse du graphique pour ne pas recouvrir les étiquettes des barres
        layout["yaxis2"] = dict(overlaying="y", side="right", showgrid=False, title=symbol(cur),
                                range=[lo - (hi - lo) * 0.15 if lo < 0 else 0, hi + (hi - lo) * 0.9 or 1])
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Vue portefeuille
# ---------------------------------------------------------------------------
view_mode = st.radio("Vue", ["Société", "Portefeuille"] if len(ids) > 1 else ["Société"], horizontal=True, label_visibility="collapsed")

if view_mode == "Portefeuille":
    rows = []
    for i in ids:
        v, r = views[i], results[i]
        f = r["fin"]
        tcam = next((x["N"] for x in r["ratios"] if "— TCAM" in x["ratio"] and x["ratio"].startswith(("Chiffre", "PNB"))), None)
        rows.append({"Société": v.name, "Format": v.ex.fmt, "Exercices": ", ".join(reversed(f.periods)),
                     "CA / PNB (dernier)": money(f.get("revenue"), v.ex.currency),
                     "Croissance dernier exercice": pct(growth(f.get("revenue"), f.get("revenue", "n1"))),
                     "TCAM CA": pct(tcam), "Résultat net": money(f.get("net_income"), v.ex.currency),
                     "Score santé": r["health"]["score"], "Santé": r["health"]["label"],
                     "Score LCB-FT": r["aml"]["score"], "Risque LCB-FT": r["aml"]["level"],
                     "Signaux élevés": sum(1 for s in r["aml"]["signals"] if s["niveau"] == "élevé")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={"Score santé": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                                "Score LCB-FT": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})
    fig = go.Figure()
    for r_ in rows:
        fig.add_trace(go.Scatter(x=[r_["Score santé"]], y=[r_["Score LCB-FT"]], mode="markers+text", text=[r_["Société"]],
                                 textposition="top center", name=r_["Société"],
                                 marker=dict(size=16, color={"Faible": "#11765f", "Modéré": "#a55b06", "Élevé": "#b42318"}[r_["Risque LCB-FT"]])))
    fig.add_shape(type="rect", x0=0, x1=50, y0=55, y1=100, fillcolor="rgba(180,35,24,.08)", line_width=0)
    fig.update_layout(height=430, showlegend=False, xaxis=dict(title="Santé financière (0-100)", range=[0, 105]),
                      yaxis=dict(title="Risque LCB-FT indicatif (0-100)", range=[0, 105]), margin=dict(t=20, b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("La zone teintée en haut à gauche réunit les sociétés fragiles financièrement et à risque LCB-FT élevé.")
    st.download_button("Télécharger la comparaison (HTML)", render_portfolio([(views[i], results[i]) for i in ids]),
                       file_name="comparaison_portefeuille.html", mime="text/html")
    st.stop()


# ---------------------------------------------------------------------------
# Vue société
# ---------------------------------------------------------------------------
sel = st.selectbox("Société", ids, format_func=lambda i: f"{views[i].name}  ·  {', '.join(reversed(results[i]['fin'].periods))}")
c: Company = ss.companies[sel]
v: View = views[sel]
res = results[sel]
f, h, a = res["fin"], res["health"], res["aml"]
cur = v.ex.currency
periods = list(reversed(f.periods))

st.caption(f"{FORMAT_NAMES[v.ex.fmt]} · {len(periods)} période(s) : {', '.join(periods)} · {len(c.doc_ids)} document(s) · "
           f"{v.n_pages} pages ({len(v.ocr_pages)} par OCR)")
if len(periods) < 3:
    st.info(f"{len(periods)} exercice(s) disponible(s). Pour une tendance sur 3 ans ou plus, déposez les comptes d'années "
            "antérieures de cette société : ils s'ajouteront automatiquement à la série.")

tabs = st.tabs(["Synthèse", "États financiers", "Ratios", "Santé financière", "LCB-FT", "Identification", "Documents et contrôles", "Export"])

# ----------------------------------------------------------------- Synthèse
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)

    def metric(col, lab, value, delta=None, neutral=False):
        try:
            col.metric(lab, value, delta, delta_color="off" if neutral else "normal", delta_arrow="off" if neutral else "auto")
        except TypeError:  # anciennes versions de Streamlit
            col.metric(lab, value, delta, delta_color="off" if neutral else "normal")

    metric(c1, "Santé financière", f"{h['score'] if h['score'] is not None else '—'} / 100", h["label"] or None, neutral=True)
    metric(c2, "Risque LCB-FT indicatif", f"{a['score']} / 100", a["level"], neutral=True)
    gr, gn = growth(f.get("revenue"), f.get("revenue", "n1")), growth(f.get("net_income"), f.get("net_income", "n1"))
    metric(c3, f"CA / PNB {f.periods[0] if f.periods else ''}", money(f.get("revenue"), cur), pct(gr) if gr is not None else None)
    metric(c4, f"Résultat net {f.periods[0] if f.periods else ''}", money(f.get("net_income"), cur), pct(gn) if gn is not None else None)
    from engine.summary import describe_activity, geography, vigilance_level
    geo = geography(v)
    vig, vig_why = vigilance_level(res, v)
    st.markdown(f"**Activité.** {describe_activity(v, res)}")
    st.markdown("**Pays d'opération.** " + (" · ".join(f"{g_['pays']} ({g_['rôle']})" + (f" — :red[{g_['risque']}]" if g_["risque"] != "standard" else "")
                                                       for g_ in geo) or "non déterminés"))
    st.markdown(f"**Vigilance LCB-FT suggérée : {vig}** — {vig_why}")
    # Grand graphique : chiffre d'affaires et résultat net sur toutes les années des documents
    main = ["pnb", "net_income"] if v.ex.fmt == "BANK" else ["revenue", "net_income"]
    what = "du PNB" if v.ex.fmt == "BANK" else "du chiffre d'affaires"
    big = evolution_chart(f, main, cur, f"Évolution {what} et du résultat net — {', '.join(periods)}")
    big.update_layout(height=480, font=dict(size=14))
    st.plotly_chart(big, use_container_width=True)
    st.caption("Barres : chiffre d'affaires, avec sa variation annuelle au-dessus. Courbe : résultat net (axe de droite s'il est "
               "beaucoup plus petit). Ajoutez les comptes d'autres années de la société pour allonger la série.")
    left, right = st.columns([1, 1.15])
    with left:
        st.subheader("Situation financière")
        for x in h["insights"]:
            st.markdown(f"- {x}")
        st.subheader("Points de vigilance LCB-FT")
        top = [s for s in a["signals"] if s["niveau"] in ("élevé", "modéré")]
        if not top:
            st.markdown("Aucun signal élevé ou modéré.")
        for s in top[:5]:
            st.markdown(f"{LEVEL_ICON[s['niveau']]} **{s['signal']}** — {s['constat']}")
    with right:
        st.plotly_chart(evolution_chart(f, ["equity", "financial_debt_total", "liquid"], cur, "Structure financière"),
                        use_container_width=True)

# ----------------------------------------------------------------- États financiers
with tabs[1]:
    all_vals = [x for key in v.ex.values for x in v.ex.values[key].vals.values()]
    scale, scale_lab = scale_for(all_vals)
    st.markdown(f"Montants **en {scale_lab} de {symbol(cur)}**, un exercice par colonne. Corrigez une cellule puis cliquez sur "
                "« Appliquer » : croissances, ratios, score et lecture LCB-FT sont recalculés. Les postes calculés (totaux, EBITDA…) "
                "se mettent à jour seuls.")
    spec_keys = []
    for sp in SPECS[v.ex.fmt]:
        if sp.key not in spec_keys:
            spec_keys.append(sp.key)
    spec_keys += [k for k in v.ex.values if k not in spec_keys]
    rows = []
    for k in spec_keys:
        val = v.ex.values.get(k)
        row = {"clé": k, "Poste": LABELS.get(k, k)}
        for p in periods:
            x = val.vals.get(p) if val else None
            row[p] = None if x is None else (x if k in {"eps_basic", "eps_diluted", "headcount", "shares_diluted"} else x / scale)
        row["Source"] = val.source if val else ""
        row["Origine"] = ("saisi" if not val.auto else "lu") if val else ""
        rows.append(row)
    df = pd.DataFrame(rows)
    for p in periods:
        df[p] = pd.to_numeric(df[p], errors="coerce")
    cfg = {"clé": None, "Poste": st.column_config.TextColumn(disabled=True, width="medium"),
           "Source": st.column_config.TextColumn(disabled=True), "Origine": st.column_config.TextColumn(disabled=True, width="small")}
    for p in periods:
        cfg[p] = st.column_config.NumberColumn(format="localized")
    edited = st.data_editor(df, hide_index=True, use_container_width=True, height=520, key=f"ed_{sel}_{len(periods)}", column_config=cfg)
    b1, b2, b3 = st.columns([1, 1, 2])
    if b1.button("Appliquer les corrections", key=f"apply_{sel}", type="primary"):
        changed = 0
        for (_, row), (_, orig) in zip(edited.iterrows(), df.iterrows()):
            k = row["clé"]
            for p in periods:
                new, old = row[p], orig[p]
                if (pd.isna(new) and pd.isna(old)) or (not pd.isna(new) and not pd.isna(old) and abs(new - old) < 1e-9):
                    continue
                mult = 1 if k in {"eps_basic", "eps_diluted", "headcount", "shares_diluted"} else scale
                c.overrides.setdefault(k, {})[p] = None if pd.isna(new) else float(new) * mult
                changed += 1
        st.toast(f"{changed} cellule(s) mise(s) à jour.")
        st.rerun()
    new_year = b2.number_input("Ajouter un exercice", min_value=1990, max_value=2100, value=int(periods[-1][:4]) - 1 if periods else 2024,
                               step=1, key=f"ny_{sel}", label_visibility="collapsed")
    if b3.button(f"Ajouter la colonne {new_year} (saisie manuelle)", key=f"addy_{sel}"):
        if str(new_year) not in c.extra_periods and str(new_year) not in periods:
            c.extra_periods.append(str(new_year))
        st.rerun()

    st.subheader("Croissance annuelle des postes")
    keys_shown = [k for k in KEY_FIGURES[v.ex.fmt]] + [k for k in spec_keys if k not in KEY_FIGURES[v.ex.fmt]]
    show_growth(growth_frame(f, keys_shown))

    if v.ex.unmatched:
        st.subheader("Lignes chiffrées non reconnues")
        st.caption("Lignes d'états financiers que le moteur n'a pas rattachées à un poste. Choisissez un poste pour les intégrer.")
        options = [""] + [f"{LABELS.get(k, k)} [{k}]" for k in spec_keys]
        um_rows = []
        for u in v.ex.unmatched:
            r_ = {"Document": u.get("doc", ""), "Page": u["page"], "Libellé": u["libellé"]}
            for p in periods:
                x = u["vals"].get(p)
                r_[p] = None if x is None else x / scale
            r_["Affecter à"] = ""
            um_rows.append(r_)
        um = pd.DataFrame(um_rows)
        um_ed = st.data_editor(um, hide_index=True, use_container_width=True, key=f"um_{sel}",
                               column_config={"Affecter à": st.column_config.SelectboxColumn(options=options),
                                              "Document": st.column_config.TextColumn(disabled=True),
                                              "Page": st.column_config.NumberColumn(disabled=True),
                                              "Libellé": st.column_config.TextColumn(disabled=True)})
        if st.button("Intégrer les lignes affectées", key=f"um_apply_{sel}"):
            for (_, row), u in zip(um_ed.iterrows(), list(v.ex.unmatched)):
                target = row["Affecter à"]
                if target:
                    k = target.split("[")[-1].rstrip("]")
                    for p in periods:
                        if not pd.isna(row[p]):
                            c.overrides.setdefault(k, {})[p] = float(row[p]) * scale
                    c.consumed.append(u["id"])
            st.rerun()

    pdf_docs = [i for i in c.doc_ids if i in ss.pdf]
    if pdf_docs:
        st.subheader("Page source")
        import pdfplumber
        dsel = st.selectbox("Document", pdf_docs, format_func=lambda i: ss.docs[i].file_name, key=f"src_{sel}")
        with pdfplumber.open(io.BytesIO(ss.pdf[dsel])) as pdf:
            first = next((x.page for x in ss.docs[dsel].ex.values.values() if x.page), 1)
            pno = st.number_input("Page", 1, len(pdf.pages), value=min(len(pdf.pages), first), key=f"pg_{sel}_{dsel}")
            st.image(pdf.pages[pno - 1].to_image(resolution=110).original, use_container_width=True)

# ----------------------------------------------------------------- Ratios
with tabs[2]:
    groups: dict[str, list] = {}
    for r in res["ratios"]:
        groups.setdefault(r["groupe"], []).append(r)
    for gname, items in groups.items():
        rows = []
        for r in items:
            vals = r.get("values", {})
            if all(vals.get(p) is None for p in periods):
                continue
            row = {"Ratio": r["ratio"]}
            for p in periods:
                row[p] = ratio(vals.get(p), r["format"])
            row["Appréciation"] = {"bon": "🟢 bon", "moyen": "🟠 moyen", "faible": "🔴 faible"}.get(r["appréciation"], "")
            row["Note"] = r["note"]
            rows.append(row)
        if rows:
            st.subheader(gname)
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    margin_names = [r for r in res["ratios"] if r["groupe"] == "Rentabilité" and r["format"] == "%"]
    if margin_names and len(periods) > 1:
        fig = go.Figure()
        for r in margin_names:
            ys = [(r["values"].get(p) * 100) if r["values"].get(p) is not None else None for p in periods]
            if any(y is not None for y in ys):
                fig.add_trace(go.Scatter(x=periods, y=ys, name=r["ratio"], mode="lines+markers"))
        fig.update_layout(height=380, yaxis_title="%", title="Rentabilité par exercice", xaxis=dict(type="category"),
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=40))
        st.plotly_chart(fig, use_container_width=True)

# ----------------------------------------------------------------- Santé
with tabs[3]:
    c1, c2 = st.columns([1, 1.4])
    with c1:
        fig = go.Figure(go.Indicator(mode="gauge+number", value=h["score"] or 0, number=dict(suffix=" / 100"),
                                     gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=NAVY),
                                                steps=[dict(range=[0, 30], color="#f3d0cc"), dict(range=[30, 50], color="#f6e2c4"),
                                                       dict(range=[50, 70], color="#e6eef7"), dict(range=[70, 100], color="#d3ece4")])))
        fig.update_layout(height=260, margin=dict(t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(f"**{h['label'] or 'Données insuffisantes'}** — calculé sur le dernier exercice ({f.periods[0] if f.periods else '—'}).")
        if h["altman"]:
            al = h["altman"]
            st.metric("Z-score d'Altman (Z'')", f"{al['z']:.2f}".replace(".", ","), f"zone {al['zone']}", delta_color="off")
            st.caption("Z'' = 6,56·X1 + 3,26·X2 + 6,72·X3 + 1,05·X4 (BFR, réserves, EBIT, capitaux propres / dettes rapportés à l'actif). "
                       "Peu discriminant pour une holding.")
    with c2:
        fig = go.Figure(go.Bar(x=list(h["pillars"].values()), y=list(h["pillars"].keys()), orientation="h", marker_color=NAVY,
                               text=[f"{x:.1f} / 25" for x in h["pillars"].values()], textposition="outside"))
        fig.update_layout(height=260, xaxis=dict(range=[0, 28]), margin=dict(t=30, l=10), title="Piliers (sur 25)")
        st.plotly_chart(fig, use_container_width=True)
        for x in h["insights"]:
            st.markdown(f"- {x}")

# ----------------------------------------------------------------- LCB-FT
with tabs[4]:
    c1, c2 = st.columns([1, 2])
    c1.metric("Risque LCB-FT indicatif", f"{a['score']} / 100", a["level"], delta_color="off")
    c2.caption("Signaux d'attention tirés des comptes (sur tous les exercices disponibles) et des actes joints. Ils orientent les "
               "diligences et ne valent pas soupçon. "
               f"Listes GAFI à jour au {a.get('lists_date') or '—'} (fichier data/risk_lists.json).")
    levels = st.multiselect("Niveaux affichés", list(LEVEL_ICON), default=list(LEVEL_ICON))
    for s in a["signals"]:
        if s["niveau"] not in levels:
            continue
        st.markdown(f"""<div class="sig {s['niveau']}"><b>{LEVEL_ICON[s['niveau']]} {s['signal']}</b> <span class="k">· {s['catégorie']}</span>
<p>{s['constat']}</p><p><span class="k">Pourquoi :</span> {s['pourquoi']}</p><p><span class="k">Diligence :</span> {s['diligence']}</p></div>""",
                    unsafe_allow_html=True)
    st.subheader("Noms à filtrer")
    st.caption("Gel des avoirs (DG Trésor), sanctions UE/ONU/OFAC, personnes politiquement exposées. Le filtrage se fait dans votre outil de screening.")
    scr = pd.DataFrame(a["screening"])
    st.dataframe(scr, hide_index=True, use_container_width=True)
    if not scr.empty:
        st.download_button("Exporter la liste (CSV)", scr.to_csv(index=False).encode("utf-8-sig"), file_name=f"screening_{c.id}.csv", mime="text/csv")
    for title, items in v.ex.breakdowns.items():
        fig = go.Figure(go.Pie(labels=[n for n, _ in items], values=[x for _, x in items], hole=.55))
        fig.update_layout(height=320, title=title, margin=dict(t=40))
        st.plotly_chart(fig, use_container_width=True)

# ----------------------------------------------------------------- Identification
with tabs[5]:
    k = v.kyc
    st.markdown("Informations lues dans les documents (le plus récent prime). Corrigez-les si l'OCR s'est trompé : "
                "la lecture LCB-FT est recalculée.")
    with st.form(f"kyc_{sel}"):
        c1_, c2_, c3_ = st.columns(3)
        name = c1_.text_input("Dénomination", k.name)
        siren = c2_.text_input("SIREN", k.siren)
        form = c3_.text_input("Forme juridique", k.legal_form)
        addr = c1_.text_input("Siège", k.address)
        ape = c2_.text_input("Code APE", k.ape)
        closing = c3_.text_input("Clôture", k.closing)
        st.markdown("**Associés**")
        assoc = st.data_editor(pd.DataFrame([{"Nom": p.name, "Parts": p.parts} for p in k.associates] or [{"Nom": "", "Parts": None}]),
                               num_rows="dynamic", hide_index=True, use_container_width=True, key=f"as_{sel}")
        st.markdown("**Dividendes décidés par bénéficiaire**")
        divs = st.data_editor(pd.DataFrame([{"Nom": p.name, "Montant": p.dividend} for p in k.dividends_by_person] or [{"Nom": "", "Montant": None}]),
                              num_rows="dynamic", hide_index=True, use_container_width=True, key=f"dv_{sel}")
        if st.form_submit_button("Enregistrer"):
            k.name, k.siren, k.legal_form, k.address, k.ape, k.closing = name, siren, form, addr, ape, closing
            k.associates = [Person(r["Nom"], float(r["Parts"])) for _, r in assoc.iterrows() if r["Nom"] and not pd.isna(r["Parts"])]
            tot = sum(p.parts or 0 for p in k.associates)
            k.total_parts = tot or None
            for p in k.associates:
                p.pct = round(100 * p.parts / tot, 2) if tot else None
            k.dividends_by_person = [Person(r["Nom"], dividend=float(r["Montant"])) for _, r in divs.iterrows()
                                     if r["Nom"] and not pd.isna(r["Montant"])]
            c.kyc = k.to_dict()
            st.rerun()
    st.subheader("Autres éléments lus")
    info = {"Capital": money(k.capital, cur, compact=False) if k.capital else "—", "Greffe": k.registry or "—",
            "SIREN (clé de contrôle)": "valide" if k.siren_valid else "non vérifiée",
            "Dirigeants": ", ".join(f"{p.name} ({p.role})" for p in k.managers) or "—",
            "Commissaires aux comptes": ", ".join(k.auditors) or "—", "Opinion d'audit": k.audit_opinion,
            "Statut réglementé": ", ".join(k.regulated) or "—", "Secteur(s) identifié(s)": ", ".join(k.sector_flags) or "—",
            "Pays cités": ", ".join(f"{cc} ({n})" for cc, n in k.countries.items()) or "—",
            "Dividendes décidés (total)": money(k.dividends_decided, cur, compact=False) if k.dividends_decided is not None else "—",
            "Effectif": f"{k.headcount:.0f}" if k.headcount else "—"}
    st.dataframe(pd.DataFrame(info.items(), columns=["Élément", "Valeur"]), hide_index=True, use_container_width=True)
    from engine.summary import geography as _geo
    gl = _geo(v)
    if gl:
        st.subheader("Pays d'opération")
        st.dataframe(pd.DataFrame([{"Pays / zone": g_["pays"], "Rôle": g_["rôle"], "Classement": g_["risque"]} for g_ in gl]),
                     hide_index=True, use_container_width=True)
    if k.subsidiaries:
        st.subheader("Filiales et participations")
        st.dataframe(pd.DataFrame([{"Entité": s.name, "Forme": s.form, "SIREN": s.siren, "Détention %": s.pct, "Commune": s.city,
                                    "Pays": s.country} for s in k.subsidiaries]), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------- Documents et contrôles
with tabs[6]:
    st.subheader("Documents de la société")
    st.dataframe(pd.DataFrame(v.sources), hide_index=True, use_container_width=True,
                 column_config={"doc_id": None})
    st.caption("Quand une année figure dans plusieurs documents, le plus récent l'emporte (comparatifs éventuellement retraités).")
    others = {i: views[i].name for i in ids if i != sel}
    col1, col2, col3 = st.columns([2, 2, 1])
    dmove = col1.selectbox("Document", c.doc_ids, format_func=lambda i: ss.docs[i].file_name if i in ss.docs else i, key=f"mv_{sel}")
    target = col2.selectbox("Rattacher à", ["(nouvelle société)"] + list(others), format_func=lambda i: others.get(i, i), key=f"tg_{sel}")
    if col3.button("Déplacer", key=f"mvb_{sel}"):
        c.doc_ids.remove(dmove)
        if target == "(nouvelle société)":
            nc = new_company(ss.docs[dmove])
            nc.id = hashlib.sha1((nc.id + dmove).encode()).hexdigest()[:10]
            nc.key = "manual:" + nc.id
            ss.companies[nc.id] = nc
        else:
            ss.companies[target].doc_ids.append(dmove)
        st.rerun()
    st.subheader("Contrôles de cohérence")
    for ctl in res["controls"]:
        st.markdown(f"{STATUS_ICON.get(ctl['statut'], '•')} **{ctl['contrôle']}** — {ctl['détail']}")
    if f.notes:
        st.subheader("Corrections automatiques et avertissements")
        for n in f.notes:
            st.markdown(f"- {n}")

# ----------------------------------------------------------------- Export
with tabs[7]:
    author = st.text_input("Analyste (affiché dans le rapport)", "")
    html = render_dossier(v, res, author)
    safe = "".join(ch if ch.isalnum() else "_" for ch in v.name)[:40]
    st.markdown("**Documents à télécharger**")
    c1_, c2_ = st.columns(2)
    try:
        c1_.download_button("Note de synthèse d'une page (Word)", build_docx(v, res, author), file_name=f"synthese_{safe}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            type="primary", use_container_width=True,
                            help="Identité, secteur, activité, chiffres clés avec croissance, graphique, santé financière, "
                                 "lecture LCB-FT, actionnariat — sur une page.")
    except Exception as e:  # noqa: BLE001
        c1_.error(f"Note Word indisponible : {e}")
    try:
        c2_.download_button("Classeur complet (Excel)", build_xlsx(v, res, ss.docs), file_name=f"analyse_{safe}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary", use_container_width=True,
                            help="Bilan, compte de résultat, flux (publiés ou reconstitués), toutes les lignes lues par document, "
                                 "ratios en formules, actionnaires et graphiques, LCB-FT.")
    except Exception as e:  # noqa: BLE001
        c2_.error(f"Classeur Excel indisponible : {e}")
    c3_, c4_ = st.columns(2)
    c3_.download_button("Rapport détaillé (HTML)", html, file_name=f"rapport_{safe}.html", mime="text/html",
                        use_container_width=True)
    c4_.download_button("Enregistrer la société (JSON)", company_to_json(c, ss.docs), file_name=f"societe_{safe}.json",
                        mime="application/json", use_container_width=True,
                        help="Rechargez ce fichier plus tard dans la barre latérale pour retrouver documents et corrections.")
    new_name = st.text_input("Nom affiché", c.name)
    if new_name != c.name:
        c.name = new_name
        st.rerun()
    if st.button("Retirer cette société de la session"):
        for i in c.doc_ids:
            ss.docs.pop(i, None)
            ss.pdf.pop(i, None)
        ss.companies.pop(sel, None)
        st.rerun()
    st.subheader("Aperçu du rapport")
    components.html(html, height=900, scrolling=True)

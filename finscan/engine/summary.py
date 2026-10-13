"""Éléments de synthèse rédigés : activité principale et pays d'opération."""
from __future__ import annotations

import re

from .fmt import symbol
from .kyc import APE_RISK, load_risk_lists

# zones géographiques de segments (rapports US / IFRS) -> libellé français
ZONES = {
    "americas": "Amériques", "europe": "Europe", "greater china": "Chine (Grande Chine)", "china": "Chine", "japan": "Japon",
    "rest of asia pacific": "reste de l'Asie-Pacifique", "asia pacific": "Asie-Pacifique", "emea": "EMEA",
    "north america": "Amérique du Nord", "latin america": "Amérique latine", "africa": "Afrique", "middle east": "Moyen-Orient",
    "united states": "États-Unis", "france": "France", "international": "International",
}
COUNTRY_FROM_CODE = {"FR": "France", "BE": "Belgique", "IT": "Italie", "PT": "Portugal", "ES": "Espagne", "DE": "Allemagne",
                     "LU": "Luxembourg", "CH": "Suisse", "GB": "Royaume-Uni", "NL": "Pays-Bas", "IE": "Irlande", "MA": "Maroc",
                     "TN": "Tunisie", "SN": "Sénégal", "CI": "Côte d'Ivoire", "CM": "Cameroun", "US": "États-Unis"}
HQ_HINT = {"PCG": "France", "BANK": "France"}


def _short(v: float | None, cur: str) -> str:
    if v is None:
        return "n/d"
    a = abs(v)
    s = f"{v / 1e9:.1f} Md" if a >= 1e9 else f"{v / 1e6:.1f} M" if a >= 1e6 else f"{v / 1e3:.0f} k" if a >= 1e3 else f"{v:.0f} "
    return (s + symbol(cur)).replace(".", ",")


def risk_class(country: str, lists: dict | None = None) -> str:
    lists = lists or load_risk_lists()
    if country in lists["fatf_black"]:
        return "liste noire GAFI"
    if country in lists["fatf_grey"] or country in lists.get("eu_high_risk", []):
        return "liste grise GAFI"
    if country in lists["sanctions_regimes"]:
        return "régime de sanctions"
    if country in lists["offshore"]:
        return "centre offshore"
    return "standard"


def geography(view) -> list[dict]:
    """Pays et zones où la société opère, avec leur rôle et leur classement de risque."""
    k, ex = view.kyc, view.ex
    lists = load_risk_lists()
    out: dict[str, dict] = {}

    def add(country: str, role: str):
        if not country:
            return
        row = out.setdefault(country, {"pays": country, "rôles": [], "risque": risk_class(country, lists)})
        if role not in row["rôles"]:
            row["rôles"].append(role)

    # siège
    hq = None
    if k.address and re.search(r"\b\d{5}\b", k.address):
        hq = "France"
    elif ex.fmt in HQ_HINT and (k.siren or k.address):
        hq = HQ_HINT[ex.fmt]
    if hq:
        add(hq, "siège")
    for e in k.establishments:
        m = re.search(r"\(([^,]+),", e)
        if m:
            add(m.group(1).strip(), "établissement")
    for s in k.subsidiaries:
        add(COUNTRY_FROM_CODE.get(s.country, s.country), "filiale / participation")
    for title, items in ex.breakdowns.items():
        if "géograph" in title.lower():
            for name, _ in items:
                add(ZONES.get(name.lower().strip(), name), "zone de ventes")
    for c in k.countries:
        if c not in out and not any(c.lower() in key.lower() for key in out):
            add(c, "cité dans les documents")
    order = {"siège": 0, "établissement": 1, "filiale / participation": 2, "zone de ventes": 3, "cité dans les documents": 4}
    rows = sorted(out.values(), key=lambda r: min(order.get(x, 9) for x in r["rôles"]))
    for r in rows:
        r["rôle"] = ", ".join(r["rôles"])
    return rows


def describe_activity(view, res: dict) -> str:
    """Une à deux phrases sur l'activité principale, construites à partir des documents."""
    k, ex = view.kyc, view.ex
    f = res["fin"]
    cur = ex.currency
    parts: list[str] = []
    if k.activity_desc:
        parts.append(k.activity_desc.rstrip(". ") + ".")
    else:
        what = []
        if k.ape in APE_RISK:
            what.append(APE_RISK[k.ape].lower())
        elif k.activity:
            what.append(k.activity.lower())
        holding = "Holding / gestion de participations" in k.sector_flags or k.ape in {"7010Z", "6420Z"}
        if holding:
            subs = k.subsidiaries
            n_sci = sum(1 for s in subs if s.form.upper() == "SCI")
            n_op = len(subs) - n_sci
            desc = "Société holding" + (f" (APE {k.ape} — {what[0]})" if what and k.ape else f" ({what[0]})" if what else "")
            if subs:
                det = []
                if n_op:
                    det.append(f"{n_op} société{'s' if n_op > 1 else ''} ({', '.join(s.name.title() for s in subs if s.form.upper() != 'SCI')[:90]})")
                if n_sci:
                    det.append(f"{n_sci} SCI immobilière{'s' if n_sci > 1 else ''} ({', '.join(s.name.title() for s in subs if s.form.upper() == 'SCI')[:60]})")
                desc += " détenant des participations dans " + " et ".join(det)
            parts.append(desc + ".")
        elif what:
            parts.append(f"Activité : {what[0]}" + (f" (APE {k.ape})." if k.ape else "."))
        elif k.ape:
            parts.append(f"Activité référencée sous le code APE {k.ape} (libellé à confirmer sur l'avis de situation INSEE).")
        sectors = [s for s in k.sector_flags if s != "Holding / gestion de participations"]
        if sectors and not holding:
            parts.append("Secteur : " + ", ".join(s.lower() for s in sectors) + ".")
    # composition des revenus
    rev = f.get("pnb") if ex.fmt == "BANK" else f.get("revenue")
    src = view.ex.values.get("revenue_parts") or view.ex.values.get("revenue_direct")
    rev_txt = []
    if rev is not None:
        nature = ""
        if src and "services" in src.source.lower() and "marchandises" not in src.source.lower():
            nature = " de prestations de services"
        elif src and "marchandises" in src.source.lower():
            nature = " de ventes de marchandises"
        lab = "PNB" if ex.fmt == "BANK" else "chiffre d'affaires"
        rev_txt.append(f"{lab}{nature} de {_short(rev, cur)} en {f.periods[0]}")
    fi = f.get("financial_income")
    if fi and rev and fi > 0.5 * rev:
        rev_txt.append(f"produits financiers de {_short(fi, cur)} (dividendes, intérêts, placements)")
    if ex.fmt == "BANK" and f.get("fee_income"):
        rev_txt.append(f"commissions perçues de {_short(f.get('fee_income'), cur)}")
    for title, items in ex.breakdowns.items():
        if "activit" in title.lower() and items:
            tot = sum(v for _, v in items) or 1
            top = sorted(items, key=lambda t: -t[1])[:3]
            rev_txt.append("principales activités : " + ", ".join(f"{n} ({v / tot * 100:.0f} %)" for n, v in top))
            break
    if rev_txt:
        parts.append("Revenus : " + " ; ".join(rev_txt) + ".")
    if k.regulated:
        parts.append(f"Statut : {k.regulated[0][0].lower() + k.regulated[0][1:]}.")
    return " ".join(parts)


def vigilance_level(res: dict, view) -> tuple[str, str]:
    """Niveau de vigilance suggéré (à confirmer par la classification des risques de l'établissement)."""
    a = res["aml"]
    high = [s for s in a["signals"] if s["niveau"] == "élevé"]
    mit = [s for s in a["signals"] if s["niveau"] == "atténuant"]
    if a["score"] >= 55 or high:
        return "renforcée", (f"{len(high)} signal(aux) élevé(s)" if high else "score élevé") + \
            " : justificatifs et origine des fonds à documenter avant ou pendant la relation (art. L.561-10-2 CMF)."
    if a["score"] >= 30:
        return "standard, avec diligences ciblées", "signaux modérés à documenter, sans facteur de risque élevé."
    if view.kyc.listed or any("agréée" in s["signal"] for s in mit):
        return "standard (allégée envisageable)", "entité cotée ou agréée et supervisée ; vérifier les conditions de l'art. R.561-15 CMF."
    return "standard", "aucun signal significatif dans les documents analysés."

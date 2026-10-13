"""Consolidation des postes, contrôles de cohérence, ratios et score de santé."""
from __future__ import annotations

from dataclasses import dataclass, field

from .extract import Extraction, Value
from .fields import LABELS
from .kyc import KYC

@dataclass
class Fin:
    """Postes consolidés par période (montants en unité monétaire, pas en milliers).
    `periods` va du plus récent au plus ancien ; « n » et « n1 » désignent les deux premières."""
    periods: list[str] = field(default_factory=list)
    months: dict[str, int] = field(default_factory=dict)
    v: dict[str, dict[str, float | None]] = field(default_factory=dict)
    origin: dict[str, str] = field(default_factory=dict)  # "lu", "calculé", "corrigé", "saisi"
    notes: list[str] = field(default_factory=list)

    def _p(self, p: str) -> str | None:
        if p == "n":
            return self.periods[0] if self.periods else None
        if p == "n1":
            return self.periods[1] if len(self.periods) > 1 else None
        return p

    def get(self, key: str, p: str = "n") -> float | None:
        pp = self._p(p)
        return self.v.get(key, {}).get(pp) if pp else None

    def set(self, key: str, p: str, val: float | None, origin: str) -> None:
        pp = self._p(p)
        if pp is None:
            return
        self.v.setdefault(key, {})[pp] = val
        if val is not None:
            self.origin.setdefault(key, origin)

    def prev(self, p: str) -> str | None:
        """Période précédente (plus ancienne) de même durée."""
        pp = self._p(p)
        if pp not in self.periods:
            return None
        i = self.periods.index(pp)
        for q in self.periods[i + 1:]:
            if self.months.get(q, 12) == self.months.get(pp, 12):
                return q
        return None

    def ann(self, p: str) -> float:
        m = self.months.get(self._p(p) or "", 12) or 12
        return 12 / m

    def series(self, key: str) -> list[tuple[str, float | None]]:
        """Valeurs dans l'ordre chronologique (ancien -> récent)."""
        return [(p, self.get(key, p)) for p in reversed(self.periods)]


def _s(*vals) -> float | None:
    """Somme en ignorant les vides ; None si tout est vide."""
    xs = [x for x in vals if x is not None]
    return sum(xs) if xs else None


def _close(a, b, tol=0.005, abs_tol=2.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, tol * max(abs(a), abs(b)))


def consolidate(ex: Extraction, kyc: KYC | None = None, _retry: bool = True) -> tuple[Fin, list[dict]]:
    f, controls = _consolidate(ex, kyc)
    # Bilan déséquilibré : l'écart correspond-il exactement à une ligne non reconnue ?
    if _retry and ex.fmt == "PCG":
        ta, tle = f.get("total_assets"), f.get("total_liabilities_equity")
        if ta is not None and tle is not None and not _close(ta, tle):
            gap = tle - ta
            side = "A" if gap > 0 else "P"
            p0 = f.periods[0]
            for u in ex.unmatched:
                un = u.get("vals", {}).get(p0)
                if u.get("section") == side and un is not None and _close(abs(gap), un * ex.unit, 0.0005, 2.0 * ex.unit):
                    lab = u["libellé"].lower()
                    key = ("other_receivables" if "cr" in lab and "ance" in lab else "other_assets") if side == "A" else "other_liabilities"
                    old = ex.values.get(key)
                    merged = dict(old.vals) if old else {}
                    for k, x in u["vals"].items():
                        merged[k] = _s(merged.get(k), x)
                    ex.values[key] = Value(merged, u["page"], f"{u['libellé']} (rattaché : égale l'écart du bilan)")
                    ex.unmatched.remove(u)
                    f, controls = _consolidate(ex, kyc)
                    f.notes.append(f"Ligne « {u['libellé']} » (p. {u['page']}) rattachée à « {LABELS[key]} » : son montant "
                                   f"égale exactement l'écart actif/passif.")
                    break
    return f, controls


def _consolidate(ex: Extraction, kyc: KYC | None = None) -> tuple[Fin, list[dict]]:
    f = Fin(list(ex.periods), dict(ex.months))
    u = ex.unit
    for key, val in ex.values.items():
        for p, raw in val.vals.items():
            if raw is None or p not in f.periods:
                continue
            mult = 1 if key in {"eps_basic", "eps_diluted", "headcount", "shares_diluted"} else u
            f.set(key, p, raw * mult, "lu" if val.auto else "saisi")
    controls: list[dict] = []
    g = f.get
    newest = f.periods[0] if f.periods else None

    for p in f.periods:
        # --- Compte de résultat ------------------------------------------------
        if g("revenue", p) is None:
            rev = g("revenue_direct", p) or g("revenue_parts", p)
            if ex.fmt == "BANK":
                rev = g("pnb", p)
            if rev is not None:
                f.set("revenue", p, rev, "calculé")
        if g("personnel", p) is None and (g("wages", p) is not None or g("social_charges", p) is not None):
            f.set("personnel", p, _s(g("wages", p), g("social_charges", p)), "calculé")
        if ex.fmt == "PCG":
            op_charges = _s(g("purchases", p), g("external_charges", p), g("taxes", p), g("personnel", p),
                            g("d_and_a", p), g("provisions_charge", p))
            if g("operating_expenses_total", p) is None and op_charges is not None:
                f.set("operating_expenses_total", p, op_charges, "calculé")
            op_rev = g("operating_revenue_total", p) or g("revenue", p)
            if g("ebit", p) is None and op_rev is not None and g("operating_expenses_total", p) is not None:
                f.set("ebit", p, op_rev - g("operating_expenses_total", p), "calculé")
            if g("ebit", p) is not None:
                computed_ni = g("ebit", p) + (g("financial_income", p) or 0) - (g("financial_expense", p) or 0) \
                    + (g("exceptional_income", p) or 0) - (g("exceptional_expense", p) or 0) - (g("income_tax", p) or 0)
                f.set("net_income_calc", p, computed_ni, "calculé")
        if ex.fmt == "BANK":
            if g("income_tax", p) is not None and g("pretax", p) is not None and g("net_income", p) is not None:
                f.set("income_tax", p, g("pretax", p) - g("net_income", p), "calculé")
            gen = _s(g("external_charges", p), g("personnel", p), g("taxes", p), g("other_opex", p))
            if gen is not None:
                f.set("general_expenses", p, gen, "calculé")
        if ex.fmt in ("IFRS", "US") and g("income_tax", p) is not None and g("income_tax", p) < 0 and g("pretax", p) is not None:
            # charges présentées en négatif : l'impôt négatif est une charge
            if g("net_income", p) is None or _close(g("pretax", p) + g("income_tax", p), g("net_income", p), 0.001, 2.0):
                f.v["income_tax"][p] = -g("income_tax", p)
        if ex.fmt == "IFRS" and g("ebit", p) is not None:
            if g("pretax", p) is not None:
                f.set("net_income_calc", p, g("pretax", p) - (g("income_tax", p) or 0), "calculé")
        if ex.fmt in ("US", "IFRS") and g("gross_profit", p) is None and g("revenue", p) is not None and g("cogs", p) is not None:
            f.set("gross_profit", p, g("revenue", p) - g("cogs", p), "calculé")
        if g("ebit", p) is not None and g("d_and_a", p) is not None:
            f.set("ebitda", p, g("ebit", p) + g("d_and_a", p) + (g("provisions_charge", p) or 0), "calculé")

        # --- Résultat net : rapprochement des sources ------------------------
        cands = {
            "compte de résultat": g("net_income", p),
            "bilan": g("net_income_bs", p),
            "recalcul des composantes": g("net_income_calc", p),
        }
        if p == newest and kyc and kyc.result_in_minutes is not None:
            cands["procès-verbal d'AG"] = kyc.result_in_minutes
        present = {k: v for k, v in cands.items() if v is not None}
        if present:
            # valeur confirmée par le plus grand nombre de sources
            best, support = None, 0
            for k, v in present.items():
                sup = sum(1 for w in present.values() if _close(v, w, 0.001, 2.0))
                if sup > support or (sup == support and k in ("compte de résultat", "procès-verbal d'AG")):
                    best, support = v, sup
            if g("net_income", p) is None:
                f.set("net_income", p, best, "calculé")
            elif not _close(g("net_income", p), best, 0.001, 2.0) and support >= 2:
                f.notes.append(f"Résultat net {p} : lecture {g('net_income', p):,.0f} remplacée par {best:,.0f} "
                               f"(confirmé par {support} sources)")
                f.v["net_income"][p] = best
                f.origin["net_income"] = "corrigé"
            if g("net_income_bs", p) is not None and not _close(g("net_income_bs", p), g("net_income", p), 0.001, 2.0) and support >= 2:
                f.notes.append(f"Résultat au bilan {p} : lecture {g('net_income_bs', p):,.0f} corrigée en {g('net_income', p):,.0f}")
                f.v["net_income_bs"][p] = g("net_income", p)
                f.origin["net_income_bs"] = "corrigé"
            if p == newest:
                disagree = [k for k, v in present.items() if not _close(v, g("net_income", p), 0.001, 2.0)]
                ok = not disagree
                controls.append({
                    "contrôle": "Résultat net cohérent entre sources",
                    "statut": "ok" if ok else ("corrigé" if support >= 2 else "alerte"),
                    "détail": " ; ".join(f"{k} : {v:,.0f}" for k, v in present.items()).replace(",", " "),
                })

        # --- Bilan -----------------------------------------------------------------
        if g("fixed_assets", p) is None:
            fa = _s(g("intangible", p), g("tangible", p), g("financial_assets", p), g("lt_securities", p))
            if ex.fmt in ("US", "IFRS") and g("total_assets", p) is not None and g("current_assets", p) is not None:
                fa = g("total_assets", p) - g("current_assets", p)
            if fa is not None:
                f.set("fixed_assets", p, fa, "calculé")
        if g("current_assets", p) is None and ex.fmt == "PCG":
            ca = _s(g("inventories", p), g("receivables", p), g("other_receivables", p), g("marketable_securities", p),
                    g("cash", p), g("prepaid", p))
            if ca is not None:
                f.set("current_assets", p, ca, "calculé")
        if ex.fmt == "PCG":
            eq_calc = _s(g("share_capital", p), g("share_premium", p), g("reserves", p), g("retained_carry", p),
                         g("net_income_bs", p), g("regulated_prov", p))
            if g("equity", p) is None and eq_calc is not None:
                f.set("equity", p, eq_calc, "calculé")
            debts = _s(g("financial_debt", p), g("customer_advances", p), g("payables", p), g("tax_social_debts", p),
                       g("other_liabilities", p), g("deferred_income", p))
            if g("total_liabilities", p) is None and debts is not None:
                f.set("total_liabilities", p, debts, "calculé")
            cl = _s(g("customer_advances", p), g("payables", p), g("tax_social_debts", p), g("other_liabilities", p),
                    g("deferred_income", p))
            if g("current_liabilities", p) is None and cl is not None:
                f.set("current_liabilities", p, cl, "calculé")
            if g("total_liabilities_equity", p) is None and g("equity", p) is not None:
                f.set("total_liabilities_equity", p, _s(g("equity", p), g("provisions", p), g("total_liabilities", p)), "calculé")
        if ex.fmt == "BANK":
            if g("total_liabilities", p) is None and g("total_liabilities_equity", p) is not None and g("equity", p) is not None:
                f.set("total_liabilities", p, g("total_liabilities_equity", p) - g("equity", p) - (g("provisions", p) or 0), "calculé")
        if ex.fmt in ("US", "IFRS") and g("total_liabilities_equity", p) is None and g("equity", p) is not None and g("total_liabilities", p) is not None:
            f.set("total_liabilities_equity", p, g("equity", p) + g("total_liabilities", p), "calculé")
        if ex.fmt == "IFRS":
            if g("total_liabilities", p) is None and g("total_liabilities_equity", p) is not None and g("equity", p) is not None:
                f.set("total_liabilities", p, g("total_liabilities_equity", p) - g("equity", p), "calculé")
            if g("total_liabilities_equity", p) is None and g("total_assets", p) is not None:
                f.set("total_liabilities_equity", p, g("total_assets", p), "calculé")
            if g("current_assets", p) is None and g("total_assets", p) is not None and g("fixed_assets", p) is not None:
                f.set("current_assets", p, g("total_assets", p) - g("fixed_assets", p), "calculé")
        if g("total_assets", p) is None:
            ta = _s(g("fixed_assets", p), g("current_assets", p))
            if ex.fmt in ("PCG",) and ta is not None:
                f.set("total_assets", p, ta, "calculé")
        if ex.fmt == "US" and g("financial_debt", p) is not None:
            f.set("financial_debt_total", p, g("financial_debt", p) + (g("commercial_paper", p) or 0), "calculé")
        elif g("financial_debt", p) is not None or g("interbank_debt", p) is not None:
            f.set("financial_debt_total", p, _s(g("financial_debt", p), g("interbank_debt", p)), "calculé")
        liquid = _s(g("cash", p), g("marketable_securities", p))
        if ex.fmt == "BANK":
            liquid = _s(g("cash", p), g("interbank_assets", p))
        if liquid is not None:
            f.set("liquid", p, liquid, "calculé")
        if g("financial_debt_total", p) is not None or liquid is not None:
            f.set("net_debt", p, (g("financial_debt_total", p) or 0) - (liquid or 0), "calculé")
        if g("cfo", p) is not None and g("capex", p) is not None:
            f.set("fcf", p, g("cfo", p) - g("capex", p), "calculé")

    # --- Contrôles de cohérence --------------------------------------------------
    ta, tle = g("total_assets"), g("total_liabilities_equity")
    if ta is not None and tle is not None:
        controls.append({"contrôle": "Bilan équilibré (actif = passif)", "statut": "ok" if _close(ta, tle) else "alerte",
                         "détail": f"Actif {ta:,.0f} / Passif {tle:,.0f}".replace(",", " ")})
    else:
        controls.append({"contrôle": "Bilan équilibré (actif = passif)", "statut": "incomplet",
                         "détail": "Total actif ou total passif non lu"})
    if ex.fmt == "PCG" and f.origin.get("total_assets") == "calculé":
        controls[-1]["détail"] += " — total actif recalculé par somme des postes"
    if len(f.periods) < 3:
        controls.append({"contrôle": "Profondeur d'historique (3 exercices conseillés)", "statut": "incomplet",
                         "détail": f"{len(f.periods)} période(s) : " + ", ".join(f.periods) +
                                   ". Ajoutez les comptes d'années antérieures de la même société pour allonger la série."})
    else:
        controls.append({"contrôle": "Profondeur d'historique (3 exercices conseillés)", "statut": "ok",
                         "détail": f"{len(f.periods)} périodes : " + ", ".join(reversed(f.periods))})
    if ex.fmt != "BANK" and g("current_assets") is not None and g("fixed_assets") is not None and ta is not None:
        if not _close(g("current_assets") + g("fixed_assets"), ta):
            controls.append({"contrôle": "Actif immobilisé + actif circulant = total actif", "statut": "alerte",
                             "détail": f"{g('fixed_assets') + g('current_assets'):,.0f} vs {ta:,.0f}".replace(",", " ")})
    if ex.fmt == "BANK":
        eq_parts = _s(g("share_capital"), g("share_premium"), g("reserves"), g("retained_carry"), g("net_income_bs"))
        if eq_parts is not None and g("equity") is not None:
            controls.append({"contrôle": "Capitaux propres = somme des composantes", "statut": "ok" if _close(eq_parts, g("equity")) else "alerte",
                             "détail": f"{eq_parts:,.0f} vs {g('equity'):,.0f}".replace(",", " ")})
    if ex.fmt in ("US", "IFRS") and g("revenue") is not None and g("cogs") is not None and g("gross_profit") is not None:
        controls.append({"contrôle": "Marge brute = ventes − coût des ventes",
                         "statut": "ok" if _close(g("revenue") - g("cogs"), g("gross_profit")) else "alerte",
                         "détail": f"{g('revenue') - g('cogs'):,.0f} vs {g('gross_profit'):,.0f}".replace(",", " ")})
    essentials = {"PCG": ["revenue", "net_income", "equity", "total_assets", "cash"],
                  "BANK": ["pnb", "net_income", "equity", "total_assets", "client_funds"],
                  "US": ["revenue", "net_income", "equity", "total_assets", "cash", "cfo"],
                  "IFRS": ["revenue", "net_income", "equity", "total_assets", "cash"]}[ex.fmt]
    missing = [LABELS.get(k, k) for k in essentials if g(k) is None]
    controls.append({"contrôle": "Postes essentiels présents", "statut": "ok" if not missing else "incomplet",
                     "détail": "Manquants : " + ", ".join(missing) if missing else "Tous lus"})
    return f, controls


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------

def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _grade(val, good, bad, higher_better=True):
    if val is None:
        return "n/d"
    if higher_better:
        return "bon" if val >= good else ("faible" if val <= bad else "moyen")
    return "bon" if val <= good else ("faible" if val >= bad else "moyen")


def ratios(f: Fin, ex: Extraction) -> list[dict]:
    """Chaque ratio est calculé pour toutes les périodes. Les flux d'une période
    infra-annuelle sont annualisés quand ils sont rapportés à un stock."""
    g = f.get
    out: list[dict] = []

    class _Ann:  # `ann` dépend de la période en cours de calcul
        p = "n"

        def __float__(self):
            return f.ann(self.p)

        def __rmul__(self, other):
            return other * f.ann(self.p)

        __mul__ = __rmul__

    ann = _Ann()

    def add(group, name, fn, fmt, good=None, bad=None, higher=True, note=""):
        vals = {}
        for p in f.periods:
            ann.p = p
            try:
                vals[p] = fn(p)
            except (TypeError, ZeroDivisionError):
                vals[p] = None
        n = vals.get(f.periods[0]) if f.periods else None
        n1 = vals.get(f.periods[1]) if len(f.periods) > 1 else None
        out.append({"groupe": group, "ratio": name, "values": vals, "N": n, "N-1": n1, "format": fmt,
                    "appréciation": _grade(n, good, bad, higher) if good is not None else "", "note": note})

    def growth(key):
        def fn(p):
            q = f.prev(p)
            a, b = g(key, p), (g(key, q) if q else None)
            if a is None or b in (None, 0):
                return None
            return (a - b) / abs(b)
        return fn

    def cagr(key, label, group="Croissance"):
        """Taux de croissance annuel moyen entre la plus ancienne et la plus récente période annuelle."""
        annual = [p for p in f.periods if f.months.get(p, 12) == 12 and g(key, p) is not None]
        if len(annual) >= 3:
            last, first = annual[0], annual[-1]
            years = int(last[:4]) - int(first[:4])
            a, b = g(key, last), g(key, first)
            val = (a / b) ** (1 / years) - 1 if years > 0 and b and b > 0 and a > 0 else None
            out.append({"groupe": group, "ratio": f"{label} — TCAM {first[:4]}-{last[:4]}", "values": {last: val}, "N": val,
                        "N-1": None, "format": "%", "appréciation": _grade(val, 0.05, -0.02) if val is not None else "",
                        "note": f"Taux de croissance annuel moyen sur {years} ans."})

    if ex.fmt == "BANK":
        add("Activité", "Croissance du PNB", growth("pnb"), "%", 0.05, -0.05)
        add("Activité", "Croissance du résultat net", growth("net_income"), "%", 0.05, -0.10)
        cagr("pnb", "PNB")
        add("Activité", "Commissions nettes / commissions perçues",
            lambda p: _div(_s(g("fee_income", p), -(g("fee_expense", p) or 0)), g("fee_income", p)), "%", 0.5, 0.3,
            note="Part conservée des commissions facturées après rétrocessions (schémas, acquéreurs).")
        add("Rentabilité", "Coefficient d'exploitation", lambda p: _div(_s(g("general_expenses", p), g("d_and_a", p)), g("pnb", p)),
            "%", 0.70, 0.90, higher=False, note="Charges générales + amortissements / PNB. Plus bas = plus efficace.")
        add("Rentabilité", "Marge nette (résultat / PNB)", lambda p: _div(g("net_income", p), g("pnb", p)), "%", 0.15, 0.03)
        add("Rentabilité", "ROE", lambda p: _div(g("net_income", p) and g("net_income", p) * ann, g("equity", p)), "%", 0.10, 0.03)
        add("Rentabilité", "ROA", lambda p: _div(g("net_income", p) and g("net_income", p) * ann, g("total_assets", p)), "%", 0.01, 0.002)
        add("Solvabilité", "Capitaux propres / total bilan", lambda p: _div(g("equity", p), g("total_assets", p)), "%", 0.15, 0.05)
        add("Solvabilité", "Dettes bancaires / capitaux propres", lambda p: _div(g("interbank_debt", p), g("equity", p)), "x", 0.3, 1.0, higher=False)
        add("Fonds clients", "Fonds cantonnés / fonds de la clientèle", lambda p: _div(g("safeguarded", p), g("client_funds", p)), "%", 1.0, 0.8,
            note="Lecture prudente : les fonds en transit (comptes d'acquisition) et les réserves peuvent compléter la protection.")
        add("Fonds clients", "Comptes dédiés (cantonnement + acquisition + réserves) / fonds clientèle",
            lambda p: _div(_s(g("safeguarded", p), g("acquisition_accounts", p), g("reserve_accounts", p)), g("client_funds", p)), "%", 1.0, 0.9)
        add("Liquidité", "Liquidités / total bilan", lambda p: _div(g("liquid", p), g("total_assets", p)), "%", 0.5, 0.2)
        return out

    add("Croissance", "Croissance du chiffre d'affaires", growth("revenue"), "%", 0.05, -0.05)
    add("Croissance", "Croissance du résultat net", growth("net_income"), "%", 0.05, -0.10)
    add("Croissance", "Croissance des capitaux propres", growth("equity"), "%", 0.03, -0.05)
    add("Croissance", "Croissance du total de bilan", growth("total_assets"), "%")
    cagr("revenue", "Chiffre d'affaires")
    cagr("net_income", "Résultat net")
    if ex.fmt in ("US", "IFRS"):
        add("Rentabilité", "Marge brute", lambda p: _div(g("gross_profit", p), g("revenue", p)), "%", 0.40, 0.20)
    add("Rentabilité", "Marge d'exploitation (EBIT / CA)", lambda p: _div(g("ebit", p), g("revenue", p)), "%", 0.10, 0.02)
    add("Rentabilité", "Marge d'EBITDA / EBE", lambda p: _div(g("ebitda", p), g("revenue", p)), "%", 0.15, 0.05)
    add("Rentabilité", "Marge nette", lambda p: _div(g("net_income", p), g("revenue", p)), "%", 0.08, 0.01)
    add("Rentabilité", "ROE (rentabilité des capitaux propres)",
        lambda p: _div(g("net_income", p) and g("net_income", p) * ann, g("equity", p)), "%", 0.12, 0.04,
        note="Annualisé si la période est infra-annuelle.")
    add("Rentabilité", "ROA (rentabilité de l'actif)", lambda p: _div(g("net_income", p) and g("net_income", p) * ann, g("total_assets", p)), "%", 0.06, 0.01)
    add("Liquidité", "Liquidité générale (actif circulant / passif courant)",
        lambda p: _div(g("current_assets", p), g("current_liabilities", p)), "x", 1.5, 1.0,
        note="Pour une liasse simplifiée, le passif courant exclut les emprunts (échéance non détaillée).")
    add("Liquidité", "Liquidité immédiate (trésorerie + VMP / passif courant)",
        lambda p: _div(g("liquid", p), g("current_liabilities", p)), "x", 0.5, 0.2)
    add("Solvabilité", "Autonomie financière (capitaux propres / total bilan)",
        lambda p: _div(g("equity", p), g("total_assets", p)), "%", 0.35, 0.15)
    add("Solvabilité", "Gearing (dettes financières / capitaux propres)",
        lambda p: _div(g("financial_debt_total", p), g("equity", p)), "x", 0.5, 1.5, higher=False)
    add("Solvabilité", "Dette nette / EBITDA",
        lambda p: _div(g("net_debt", p), g("ebitda", p) and g("ebitda", p) * ann) if (g("ebitda", p) or 0) > 0 else None,
        "x", 2.0, 4.0, higher=False, note="Négatif = trésorerie nette positive.")
    add("Solvabilité", "Couverture des charges financières (EBIT / charges financières)",
        lambda p: _div(g("ebit", p), g("interest_expense", p) or g("financial_expense", p)), "x", 5, 1.5)
    add("Activité", "Rotation de l'actif (CA / total actif)",
        lambda p: _div(g("revenue", p) and g("revenue", p) * ann, g("total_assets", p)), "x", 0.8, 0.2)
    add("Activité", "Délai clients (jours de CA)",
        lambda p: _div(g("receivables", p), g("revenue", p) and g("revenue", p) * ann / 365), "j", 45, 90, higher=False)
    add("Activité", "Délai fournisseurs (jours d'achats)",
        lambda p: _div(g("payables", p), (_s(g("purchases", p), g("external_charges", p), g("cogs", p)) or 0) * ann / 365 or None), "j")
    if ex.fmt in ("US", "IFRS"):
        add("Trésorerie", "Free cash-flow / CA", lambda p: _div(g("fcf", p), g("revenue", p)), "%", 0.10, 0.02)
        add("Trésorerie", "Conversion du résultat en cash (CFO / résultat net)", lambda p: _div(g("cfo", p), g("net_income", p)), "x", 1.0, 0.7)
        add("Retour actionnaire", "Dividendes + rachats / FCF",
            lambda p: _div(_s(g("dividends_paid", p), g("buybacks", p)), g("fcf", p)), "%", 1.0, 1.5, higher=False,
            note="Au-delà de 100 % : la rémunération des actionnaires excède le cash généré.")
        add("Marché", "BPA dilué", lambda p: g("eps_diluted", p), "num")
        add("Marché", "Croissance du BPA dilué", growth("eps_diluted"), "%", 0.05, -0.05)
    if ex.fmt == "PCG":
        add("Structure", "Poids des produits financiers (produits financiers / CA)",
            lambda p: _div(g("financial_income", p), g("revenue", p)), "%",
            note="Au-delà de 100 % : le revenu provient surtout des participations et placements (profil holding).")
        add("Structure", "Poids du résultat exceptionnel (|exceptionnel| / CA)",
            lambda p: _div(abs((g("exceptional_income", p) or 0) - (g("exceptional_expense", p) or 0)), g("revenue", p))
            if g("exceptional_income", p) is not None or g("exceptional_expense", p) is not None else None, "%", 0.1, 0.5, higher=False)
    return out


# ---------------------------------------------------------------------------
# Score de santé financière
# ---------------------------------------------------------------------------

def _band(val, lo, hi):
    """Score 0..1 : 0 à `lo`, 1 à `hi` (lo > hi pour un ratio « plus bas = mieux »)."""
    if val is None:
        return None
    t = (val - lo) / (hi - lo)
    return max(0.0, min(1.0, t))


def health(f: Fin, ex: Extraction, rlist: list[dict]) -> dict:
    """Score 0-100 en quatre piliers ; chaque pilier est noté sur les
    composantes disponibles (une donnée manquante ne pénalise pas)."""
    g = f.get
    r = {x["ratio"]: x["N"] for x in rlist}
    profit = 1.0 if (g("net_income") or 0) > 0 else 0.0 if g("net_income") is not None else None
    if ex.fmt == "BANK":
        pillars = {
            "Rentabilité": [_band(r.get("ROE"), 0.0, 0.15), _band(r.get("Coefficient d'exploitation"), 0.95, 0.65)],
            "Solvabilité": [_band(r.get("Capitaux propres / total bilan"), 0.03, 0.25)],
            "Liquidité & fonds clients": [_band(r.get("Comptes dédiés (cantonnement + acquisition + réserves) / fonds clientèle"), 0.85, 1.10),
                                          _band(r.get("Liquidités / total bilan"), 0.2, 0.6)],
            "Dynamique": [_band(r.get("Croissance du PNB"), -0.15, 0.10), profit],
        }
    else:
        pillars = {
            "Rentabilité": [_band(r.get("Marge nette"), -0.05, 0.12), _band(r.get("ROE (rentabilité des capitaux propres)"), -0.05, 0.15)],
            "Liquidité": [_band(r.get("Liquidité générale (actif circulant / passif courant)"), 0.6, 2.0),
                          _band(r.get("Liquidité immédiate (trésorerie + VMP / passif courant)"), 0.05, 1.0)],
            "Solvabilité": [_band(r.get("Autonomie financière (capitaux propres / total bilan)"), 0.05, 0.5),
                            _band(r.get("Gearing (dettes financières / capitaux propres)"), 2.0, 0.2)],
            "Dynamique": [_band(r.get("Croissance du chiffre d'affaires"), -0.20, 0.15), profit],
        }
    scores = {}
    for name, parts in pillars.items():
        vals = [x for x in parts if x is not None]
        if vals:
            scores[name] = round(25 * sum(vals) / len(vals), 1)
    total = round(sum(scores.values()) * 4 / len(scores)) if scores else None
    label = None
    if total is not None:
        label = "Solide" if total >= 70 else "Correcte" if total >= 50 else "Fragile" if total >= 30 else "Critique"

    altman = None
    if ex.fmt != "BANK":
        ta = g("total_assets")
        tl = g("total_liabilities")
        if tl is None and g("total_liabilities_equity") is not None and g("equity") is not None:
            tl = g("total_liabilities_equity") - g("equity")
        ca, cl = g("current_assets"), g("current_liabilities")
        re_ = _s(g("reserves"), g("retained_carry"))
        ebit = g("ebit")
        if all(x is not None for x in (ta, ca, cl, re_, ebit, g("equity"))) and ta and tl:
            ann = f.ann("n")
            x1, x2, x3, x4 = (ca - cl) / ta, re_ / ta, ebit * ann / ta, g("equity") / tl
            z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
            altman = {"z": round(z, 2), "zone": "sûre" if z > 2.6 else "grise" if z > 1.1 else "détresse",
                      "x": [round(x1, 3), round(x2, 3), round(x3, 3), round(x4, 3)]}
    return {"score": total, "label": label, "pillars": scores, "altman": altman,
            "insights": narrative(f, ex, r, altman)}


def _pct(x):
    return f"{x * 100:.1f} %".replace(".", ",")


def narrative(f: Fin, ex: Extraction, r: dict, altman) -> list[str]:
    """Phrases de synthèse factuelles (forces / faiblesses)."""
    g = f.get
    out = []
    rev, rev1 = g("revenue"), g("revenue", "n1")
    ni, ni1 = g("net_income"), g("net_income", "n1")
    what = "PNB" if ex.fmt == "BANK" else "Chiffre d’affaires"
    if rev is not None and rev1:
        out.append(f"{what} {'en hausse' if rev >= rev1 else 'en baisse'} de {_pct(abs(rev / rev1 - 1))} sur le dernier exercice ({f.periods[1]} → {f.periods[0]}).")
    tc = next((v for k, v in r.items() if k.startswith(("Chiffre d'affaires — TCAM", "PNB — TCAM")) and v is not None), None)
    tc_name = next((k for k, v in r.items() if k.startswith(("Chiffre d'affaires — TCAM", "PNB — TCAM")) and v is not None), "")
    if tc is not None:
        out.append(f"Sur la durée ({tc_name.split('TCAM ')[-1]}) : croissance annuelle moyenne de {_pct(tc)}.")
    losses = [p for p in f.periods if (f.get("net_income", p) or 0) < 0]
    if len(f.periods) >= 3 and losses:
        out.append(f"Exercice(s) déficitaire(s) dans l'historique : {', '.join(sorted(losses))}.")
    if ni is not None:
        if ni1 is not None and ni1 < 0 <= ni:
            out.append("Retour au bénéfice après un exercice déficitaire.")
        elif ni < 0:
            out.append("Exercice déficitaire.")
        elif ni1:
            out.append(f"Résultat net {'en progression' if ni >= ni1 else 'en recul'} de {_pct(abs(ni / ni1 - 1))}.")
    if ex.fmt == "BANK":
        ce = r.get("Coefficient d'exploitation")
        if ce is not None:
            out.append(f"Coefficient d'exploitation de {_pct(ce)} : {'marge de manœuvre réduite' if ce > 0.85 else 'efficacité correcte'}.")
        cov = r.get("Fonds cantonnés / fonds de la clientèle")
        if cov is not None:
            out.append(f"Comptes de cantonnement = {_pct(cov)} des fonds de la clientèle ; avec comptes d'acquisition et de réserves : "
                       f"{_pct(r.get('Comptes dédiés (cantonnement + acquisition + réserves) / fonds clientèle') or 0)}.")
    else:
        af = r.get("Autonomie financière (capitaux propres / total bilan)")
        if af is not None:
            out.append(f"Autonomie financière de {_pct(af)} ({'structure très capitalisée' if af > 0.5 else 'endettement significatif' if af < 0.2 else 'structure équilibrée'}).")
        nd = g("net_debt")
        if nd is not None and nd < 0:
            out.append("Trésorerie nette positive (liquidités supérieures aux dettes financières).")
        pf = r.get("Poids des produits financiers (produits financiers / CA)")
        if pf is not None and pf > 1:
            out.append(f"Les produits financiers représentent {_pct(pf)} du chiffre d’affaires : la performance dépend des participations et placements.")
        if ex.fmt == "US":
            sr = r.get("Dividendes + rachats / FCF")
            if sr is not None:
                out.append(f"Dividendes et rachats d'actions = {_pct(sr)} du free cash-flow.")
    if altman:
        out.append(f"Z-score d'Altman (Z'') = {altman['z']:.2f} : zone {altman['zone']}.".replace(".", ",", 1))
    return out

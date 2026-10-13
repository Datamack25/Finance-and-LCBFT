"""Extraction des postes financiers d'un Document, sur toutes les années présentes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .fields import CHARGES, SPECS, FieldSpec
from .ingest import Document, Page
from .numbers import Num, ParsedLine, normalize, parse_line, year_of


@dataclass
class Value:
    vals: dict[str, float | None] = field(default_factory=dict)  # période -> montant (unité du document)
    page: int | None = None
    source: str = ""  # libellé source tel que lu
    auto: bool = True  # False si saisi / corrigé à la main


@dataclass
class Extraction:
    fmt: str
    unit: float  # multiplicateur vers l'unité monétaire (1, 1000, 1e6)
    unit_label: str
    currency: str
    period_months: int  # durée des flux (P&L, cash-flow) du document
    period_label: str
    periods: list[str] = field(default_factory=list)  # du plus récent au plus ancien
    months: dict[str, int] = field(default_factory=dict)  # durée des flux par période
    values: dict[str, Value] = field(default_factory=dict)
    unmatched: list[dict] = field(default_factory=list)  # lignes chiffrées non reconnues
    breakdowns: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Détection du format, de l'unité, de la devise et de la période
# ---------------------------------------------------------------------------

IFRS_MARKERS = ("ifrs", "international financial reporting standards", "etat de la situation financiere",
                "actifs non courants", "passifs courants", "passifs non courants", "resultat operationnel",
                "statement of financial position", "profit or loss", "non-controlling interests",
                "participations ne donnant pas le controle", "interets minoritaires", "produits des activites ordinaires",
                "total equity and liabilities", "comptes consolides")


def detect_format(text: str) -> str:
    t = normalize(text)
    if "produit net bancaire" in t or "creances sur les etablissements de credit" in t:
        return "BANK"
    ifrs_hits = sum(k in t for k in IFRS_MARKERS)
    if ifrs_hits >= 2:
        return "IFRS"
    us_hits = sum(k in t for k in ("statements of operations", "balance sheets", "total liabilities and",
                                    "shareholders' equity", "stockholders' equity", "earnings per share",
                                    "cash flows", "in millions", "in thousands", "10-k", "10-q", "us gaap"))
    fr_hits = sum(k in t for k in ("capitaux propres", "report a nouveau", "compte de resultat", "bilan",
                                    "chiffre d'affaires", "resultat de l'exercice", "liasse"))
    return "US" if us_hits > fr_hits else "PCG"


def detect_currency(text: str, fmt: str) -> str:
    t = normalize(text)
    low = text.lower()
    scores = {
        "EUR": low.count("€") + len(re.findall(r"\beuros?\b|\beur\b|k€|m€", t)),
        "USD": low.count("$") + len(re.findall(r"\busd\b|\bdollars?\b|us\$", t)),
        "GBP": low.count("£") + len(re.findall(r"\bgbp\b|\bpounds? sterling\b", t)),
        "CHF": len(re.findall(r"\bchf\b|francs suisses", t)),
        "XOF": len(re.findall(r"\bfcfa\b|\bxof\b|francs cfa", t)),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "USD" if fmt == "US" else "EUR"
    return best


def detect_unit(text: str, fmt: str) -> tuple[float, str]:
    """Unité des montants : la première mention trouvée dans le document l'emporte."""
    t = normalize(text) + " " + text.lower()
    pats = [(1000.0, "milliers", r"en milliers|in thousands|\(k€\)|k€|keur|'000|en k ?eur|thousands of|"
                                 r"(?:£|€|\$|eur|gbp|usd|chf) ?thousands?\b|milliers d'euros"),
            (1e6, "millions", r"en millions|in millions|millions of|\(m€\)|m€|€m\b|\$m\b|£m\b|meur|"
                              r"(?:£|€|\$|eur|gbp|usd|chf) ?millions?\b|millions? d'euros|millions? de dollars")]
    found = []
    for mult, lab, p in pats:
        m = re.search(p, t)
        if m:
            found.append((m.start(), mult, lab))
    if found:
        _, mult, lab = min(found)
        return mult, lab
    return 1.0, "unités"


def detect_period(text: str, fmt: str) -> tuple[int, str]:
    t = normalize(text)
    for k, m in (("nine months ended", 9), ("six months ended", 6), ("three months ended", 3), ("comptes semestriels", 6),
                 ("rapport financier semestriel", 6), ("etats financiers intermediaires", 6), ("comptes intermediaires", 6),
                 ("interim financial statements", 6), ("half-year financial", 6), ("periode de six mois", 6)):
        if k in t:
            return m, f"{m} mois (cumul depuis l'ouverture de l'exercice)"
    m = re.search(r"duree de l'exercice[^0-9]{0,40}(\d{1,2})", t) or re.search(r"duree n ?: ?(\d{1,2})", t)
    if m and 1 <= int(m.group(1)) <= 24:
        return int(m.group(1)), f"{m.group(1)} mois"
    return 12, "12 mois"


def _closing_year(text: str) -> int | None:
    for p in (r"clos(?:e)? le\s*:?\s*\d{1,2}[/ .-]\s*\w+[/ .-]\s*((?:19|20)\d{2})",
              r"clos(?:e)? le\s*:?\s*\d{1,2} \w+ ((?:19|20)\d{2})",
              r"exercice n clos le\s*(\d{2}/\d{2}/((?:19|20)\d{2}))",
              r"(?:year|years|months) ended \w+ \d{1,2},\s*((?:19|20)\d{2})",
              r"cl[oô]ture au\s*:?\s*\d{2}/\d{2}/((?:19|20)\d{2})",
              r"au 3[01][/ ]\w+[/ ]((?:19|20)\d{2})"):
        m = re.search(p, text, re.I)
        if m:
            return int(m.group(m.lastindex)[-4:])
    return None


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _section_trigger(norm: str, fmt: str) -> str | None:
    if fmt in ("US", "IFRS"):
        if re.search(r"statements? of (operations|income|earnings)|income statements?|statement of profit or loss|"
                     r"compte de resultat|profit and loss", norm) and "comprehensive" not in norm and "global" not in norm:
            return "R"
        if re.search(r"resultat global|comprehensive income|variation des capitaux propres|changes in equity", norm):
            return "X"
        if re.search(r"tableau des flux|statements? of cash flows|cash flow statement|flux de tresorerie consolides", norm):
            return "F"
        if re.search(r"balance sheets?|situation financiere|financial position|bilan consolide", norm) or \
                re.match(r"^(assets|actifs?)( |:|$)", norm):
            return "A"
        if re.match(r"^(liabilities and|liabilities:|equity and liabilities|passifs?( |:|$)|capitaux propres et passifs|"
                     r"passif et capitaux propres|total capitaux propres et passif)", norm) and not re.search(r"\d", norm):
            return "P"
        if "net sales by" in norm or "supplemental" in norm or norm.startswith(("notes ", "note ", "annexe")):
            return "X"
        return None
    if re.match(r"^(bilan )?actif\b", norm) and "passif" not in norm:
        return "A"
    if re.match(r"^(bilan )?passif\b", norm) or norm.startswith("capitaux propres:") or norm in {"capitaux propres", "capitaux propres:"}:
        return "P"
    if "compte de resultat" in norm or norm.startswith("resultat comptable"):
        return "R"
    if norm.startswith(("resultat fiscal", "hors bilan", "renvois", "note ", "annexe", "sommaire", "divers a reintegrer")):
        return "X"
    return None


_SUB = (("non-current assets", "NCA"), ("actifs non courants", "NCA"), ("current assets", "CA"), ("actifs courants", "CA"),
        ("non-current liabilities", "NCL"), ("passifs non courants", "NCL"), ("current liabilities", "CL"),
        ("passifs courants", "CL"), ("shareholders' equity", "EQ"), ("shareholders equity", "EQ"), ("equity", "EQ"),
        ("capitaux propres", "EQ"))


def _sub(norm: str) -> str | None:
    for k, v in _SUB:
        if norm.startswith(k):
            return v
    return None


# ---------------------------------------------------------------------------
# Colonnes
# ---------------------------------------------------------------------------

_REL = re.compile(r"^(?:exercice\s+)?n(?:\s*-\s*([1-9]))?$", re.I)


def _col_key(token: str) -> str | None:
    """Clé de colonne : année (« 2021 ») ou rang relatif (« N », « N-1 »)."""
    y = year_of(token)
    if y:
        return str(y)
    t = token.strip("[]|():*").replace("–", "-")
    m = _REL.match(t)
    if m:
        return "N" if not m.group(1) else f"N-{m.group(1)}"
    return None


def _cluster(xs: list[float], tol: float) -> list[float]:
    xs = sorted(xs)
    groups: list[list[float]] = []
    for x in xs:
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups if len(g) >= 3]


@dataclass
class PageColumns:
    centers: list[float]
    keys: dict[int, str]  # index de colonne -> période (« N », « N-1 » à défaut d'année)
    n_idx: int | None
    tol: float


def _header_tokens(pl: ParsedLine) -> list[tuple[float, str]]:
    out = []
    words = pl.line.words
    for i, w in enumerate(words):
        k = _col_key(w.text)
        # « N - 1 » écrit en trois mots
        if k == "N" and i + 2 < len(words) and words[i + 1].text in {"-", "–"} and words[i + 2].text.isdigit():
            k = f"N-{words[i + 2].text}"
            out.append((words[i + 2].x1, k))
            continue
        if k:
            out.append((w.x1, k))
    return out


def _is_header(pl: ParsedLine) -> bool:
    toks = _header_tokens(pl)
    years = [k for _, k in toks if k[0].isdigit()]
    rel = [k for _, k in toks if k.startswith("N")]
    return len(years) >= 2 or len(rel) >= 2


def _columns(page: Page, plines: list[ParsedLine]) -> PageColumns:
    tol = 0.015 * page.width
    xs = [n.x1 for pl in plines if pl.label and not _is_header(pl) for n in pl.nums if not n.note]
    centers = _cluster(xs, tol)
    if not centers:
        return PageColumns([], {}, None, tol)
    if len(centers) >= 2:
        # repli sans en-tête lisible : les deux colonnes de droite = N et N-1
        return PageColumns(centers, {len(centers) - 2: "N", len(centers) - 1: "N-1"}, len(centers) - 2, tol)
    return PageColumns(centers, {0: "N"}, 0, tol)


def _fix_signs(pl: ParsedLine, cols: PageColumns) -> list[Num]:
    """Un tiret qui ne tombe sur aucune colonne est le signe du nombre suivant."""
    out: list[Num] = []
    nums = pl.nums
    i = 0
    while i < len(nums):
        n = nums[i]
        if n.value is None and n.raw == "-" and i + 1 < len(nums) and nums[i + 1].value is not None:
            on_col = any(abs(c - n.x1) <= cols.tol for c in cols.centers)
            if not on_col:
                nxt = nums[i + 1]
                out.append(Num(-abs(nxt.value), n.x0, nxt.x1, "-" + nxt.raw))
                i += 2
                continue
        out.append(n)
        i += 1
    return out


def _pick_header(nums: list[Num], hdr: list[tuple[float, str]], width: float) -> dict[str, float | None] | None:
    """Affecte chaque nombre à la colonne d'en-tête la plus proche. Une même année
    présente deux fois (trimestre puis cumul) : la colonne la plus à droite l'emporte."""
    tol = 0.045 * width
    keep: dict[str, int] = {}
    for i, (_, k) in enumerate(hdr):
        keep[k] = i  # dernière (la plus à droite) occurrence
    best: dict[int, tuple[float, float | None]] = {}
    for num in nums:
        x = num.x1
        if num.raw.endswith(")") and len(num.raw) > 1:  # la parenthèse fermante déborde de la colonne
            x -= (num.x1 - num.x0) / len(num.raw)
        j = min(range(len(hdr)), key=lambda k: abs(hdr[k][0] - x))
        d = abs(hdr[j][0] - x)
        if d > tol or num.raw.endswith("%"):
            continue
        if j not in best or d < best[j][0]:
            best[j] = (d, num.value)
    if not best:
        return None  # aucun nombre sous une colonne datée : en-tête non applicable
    return {k: best[i][1] for k, i in keep.items() if i in best}


def _pick(nums: list[Num], cols: PageColumns, brut_check: bool = False) -> dict[str, float | None]:
    if not cols.centers:
        vals = [n.value for n in nums if not n.note]
        if len(vals) >= 2:
            return {"N": vals[-2], "N-1": vals[-1]}
        return {"N": vals[0]} if vals else {}
    out: dict[str, float | None] = {}
    by_col: dict[int, float | None] = {}
    for num in nums:
        if num.note:
            continue
        j = min(range(len(cols.centers)), key=lambda k: abs(cols.centers[k] - num.x1))
        if abs(cols.centers[j] - num.x1) > 2.5 * cols.tol:
            continue
        by_col[j] = num.value
        if j in cols.keys:
            out[cols.keys[j]] = num.value
    # Présentation Brut / Amort. / Net / N-1 : le net doit valoir brut - amort.
    # Garde-fou contre une erreur d'OCR sur une seule des colonnes.
    ni = cols.n_idx
    if brut_check and ni is not None and ni >= 2 and len(cols.centers) >= 4:
        brut = by_col.get(ni - 2)
        amort = by_col.get(ni - 1) or 0.0
        if brut is not None and brut > 0:
            expected = brut - amort
            n = out.get("N")
            if n is None or abs(expected - n) > max(2.0, 0.0005 * abs(expected)):
                out["N"] = expected
    return out


# ---------------------------------------------------------------------------
# Correspondance libellé -> poste
# ---------------------------------------------------------------------------

def _score(norm: str, canon: str) -> float:
    if not norm:
        return 0
    if norm == canon:
        return 101
    if norm.startswith(canon + " ") or norm.startswith(canon + ":"):
        return 100 if len(canon) > 6 else 0
    head = norm[: len(canon) + 2]
    s = fuzz.ratio(norm, canon)
    if len(canon) >= 10:
        s = max(s, fuzz.ratio(head, canon) - 3)
    return s


def _match(norm: str, specs: list[FieldSpec], section: str, sub: str | None,
           occ: dict[str, int] | None = None, threshold: float = 87) -> tuple[FieldSpec | None, float]:
    scored: list[tuple[float, int, FieldSpec]] = []
    for i, sp in enumerate(specs):
        if section not in sp.sections:
            continue
        if sp.sub and sub not in sp.sub:
            continue
        s = 0.0
        for c in sp.labels:
            sc = _score(norm, c)
            # les libellés très courts (« total », « basic ») exigent l'égalité
            if len(c) <= 8 and sc < 100:
                continue
            s = max(s, sc)
        if s >= threshold:
            scored.append((s, i, sp))
    if not scored:
        return None, 0.0
    top = max(s for s, _, _ in scored)
    tied = [sp for s, _, sp in sorted(scored, key=lambda t: t[1]) if s == top]
    if occ is not None and len(tied) > 1:
        # même libellé pour plusieurs postes (« Diluted ») : la n-ième occurrence
        nxt = occ.get("~" + norm, 0) + 1
        occ["~" + norm] = nxt
        for sp in tied:
            if sp.occurrence == nxt:
                return sp, top
    return tied[0], top


def _secondary_specs(fmt: str) -> list[FieldSpec]:
    """Libellés des autres formats, utilisés en repli (présentations hybrides)."""
    order = {"PCG": ["IFRS", "US"], "IFRS": ["PCG", "US"], "US": ["IFRS"], "BANK": []}[fmt]
    out = []
    for f in order:
        out += [sp for sp in SPECS[f] if sp.key not in {"total_assets", "total_liabilities_equity", "net_income_bs"}]
    return out


# ---------------------------------------------------------------------------
# Extraction principale
# ---------------------------------------------------------------------------

MONTHS = r"^(january|february|march|april|may|june|july|august|september|october|november|december|janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)$"


def extract(doc: Document, fmt: str | None = None) -> Extraction:
    text = doc.text
    fmt = fmt or detect_format(text)
    unit, unit_label = detect_unit(text, fmt)
    currency = detect_currency(text, fmt)
    months, plabel = detect_period(text, fmt)
    specs = SPECS[fmt]
    secondary = _secondary_specs(fmt)
    ex = Extraction(fmt, unit, unit_label, currency, months, plabel)
    multi_sub = fmt in ("US", "IFRS")

    candidates: dict[str, list[dict]] = {}
    header_years: list[int] = []
    for page in doc.pages:
        gap = 1.6 if page.source == "ocr" else 0.9
        plines = [parse_line(l, gap) for l in page.lines]
        cols = _columns(page, plines)
        section, sub = None, None
        occ: dict[str, int] = {}
        page_found: dict[str, dict] = {}
        breakdown_key = None
        hdr: list[tuple[float, str]] = []
        for pl in plines:
            if _is_header(pl):
                hdr = _header_tokens(pl)
                header_years += [int(k) for _, k in hdr if k[0].isdigit()]
            trig = _section_trigger(pl.norm, fmt) if (len(pl.nums) <= 1 or multi_sub) else None
            hdr_line = _is_header(pl)
            if trig and (not pl.nums or len(pl.norm) > 3) and (hdr_line or not (pl.nums and trig in ("A", "P") and multi_sub and len(pl.nums) > 1)):
                old_section, section = section, trig
                sub = None
                if not hdr_line and trig != old_section and trig in ("A", "R", "F"):
                    hdr = []  # nouvel état : l'en-tête de colonnes du précédent ne s'applique plus
                if fmt == "US" and "net sales by" in pl.norm:
                    breakdown_key = "Répartition géographique" if "segment" in pl.norm else "Répartition par activité"
                    ex.breakdowns.setdefault(breakdown_key, [])
                continue
            if multi_sub:
                s2 = _sub(pl.norm)
                if s2 and not pl.nums:
                    sub = s2
                    continue
            if not pl.nums or not pl.label or _is_header(pl):
                continue
            nums = _fix_signs(pl, cols)
            vals = _pick_header([x for x in nums if x.value is not None] or nums, hdr, page.width) if hdr else None
            if vals is None:
                vals = _pick(nums, cols, brut_check=(fmt == "PCG" and section == "A"))
            if not vals:
                continue
            if breakdown_key and section == "X":
                if pl.norm.startswith("total"):
                    breakdown_key = None
                else:
                    first = next((v for v in vals.values() if v is not None), None)
                    newest = vals.get(max(vals, key=lambda k: (k[0].isdigit(), k)), None) if vals else None
                    if (newest if newest is not None else first) is not None:
                        ex.breakdowns[breakdown_key].append((pl.label.strip(" :"), newest if newest is not None else first))
                        continue
            sec = section or ("X" if not multi_sub else None)
            if sec is None:
                continue
            sp, sc = _match(pl.norm, specs, sec, sub, occ)
            if sp is None and secondary:
                sp, sc = _match(pl.norm, secondary, sec, sub, None, threshold=95)
                if sp is not None and sp.key in page_found:
                    sp = None
            if sp is None:
                if sec in ("A", "P", "R", "F") and any(v is not None for v in vals.values()) and not re.match(MONTHS, pl.norm):
                    ex.unmatched.append({"page": page.number, "section": sec, "libellé": pl.label, "vals": dict(vals)})
                continue
            if sp.charge or sp.key in CHARGES:
                vals = {k: (abs(v) if v is not None else None) for k, v in vals.items()}
            cur = page_found.get(sp.key)
            if cur and sp.agg == "sum":
                for k, v in vals.items():
                    if v is not None or cur["vals"].get(k) is not None:
                        cur["vals"][k] = (cur["vals"].get(k) or 0) + (v or 0)
                cur["source"] += " + " + pl.label.strip()
                cur["score"] = min(cur["score"], sc)
            elif not cur or (sp.agg == "first" and ((all(v is None for v in cur["vals"].values()) and any(v is not None for v in vals.values()))
                                                     or sc > cur["score"])):
                page_found[sp.key] = {"page": page.number, "vals": dict(vals), "source": pl.label.strip(), "score": sc}
        for k, v in page_found.items():
            v["hits"] = len(page_found)
            candidates.setdefault(k, []).append(v)

    for k, cands in candidates.items():
        best = max(cands, key=lambda c: (c["hits"], sum(v is not None for v in c["vals"].values()), c["score"], -c["page"]))
        ex.values[k] = Value(dict(best["vals"]), best["page"], best["source"])

    _resolve_periods(ex, text, header_years)
    return ex


def _resolve_periods(ex: Extraction, text: str, header_years: list[int]) -> None:
    """Remplace les rangs relatifs (N, N-1…) par des années et fixe l'ordre des périodes."""
    anchor = _closing_year(text) or (max(header_years) if header_years else None)
    if anchor is None:
        years = [int(k) for v in ex.values.values() for k in v.vals if k.isdigit()]
        anchor = max(years) if years else 0

    def conv(k: str) -> str:
        if k.isdigit():
            return k
        m = re.match(r"N(?:-(\d))?$", k)
        return str(anchor - int(m.group(1) or 0)) if m and anchor else k

    def remap(vals: dict) -> dict:
        out: dict[str, float | None] = {}
        for k, v in vals.items():
            ck = conv(k)
            if out.get(ck) is None:
                out[ck] = v
        return out

    for v in ex.values.values():
        v.vals = remap(v.vals)
    for u in ex.unmatched:
        u["vals"] = remap(u["vals"])
    keys = {k for v in ex.values.values() for k, x in v.vals.items() if x is not None}
    # n'ajouter une année que si elle porte assez de postes (évite une colonne parasite)
    counts = {k: sum(1 for v in ex.values.values() if v.vals.get(k) is not None) for k in keys}
    top = max(counts.values()) if counts else 0
    periods = sorted([k for k, c in counts.items() if c >= max(2, 0.15 * top)], key=lambda k: (k.isdigit(), k), reverse=True)
    suffix = f" ({ex.period_months} m)" if ex.period_months < 12 else ""
    if suffix:
        rename = {p: p + suffix for p in periods}
        for v in ex.values.values():
            v.vals = {rename.get(k, k): x for k, x in v.vals.items()}
        for u in ex.unmatched:
            u["vals"] = {rename.get(k, k): x for k, x in u["vals"].items()}
        periods = [rename[p] for p in periods]
    ex.periods = periods
    ex.months = {p: ex.period_months for p in periods}
    # on ne garde que les périodes retenues
    for v in ex.values.values():
        v.vals = {k: x for k, x in v.vals.items() if k in periods}

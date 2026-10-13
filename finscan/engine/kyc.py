"""Lecture « KYC » du texte : identité, associés, dirigeants, filiales,
distributions, opinion d'audit, statut réglementé, pays cités.

Tout ce qui est extrait ici est une proposition de lecture : l'analyste
valide et complète dans l'interface.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

DATA = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

def _strip(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _num(s: str) -> float | None:
    s = s.strip().replace(" ", " ").replace(" ", " ")
    s = re.sub(r"[€$\s]", "", s)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def name_tokens(name: str) -> set[str]:
    stop = {"madame", "monsieur", "mademoiselle", "m", "mme", "mlle", "mr", "epouse", "nee", "veuve", "a"}
    toks = re.findall(r"[a-z]+", _strip(name).lower())
    return {t for t in toks if t not in stop and len(t) > 1}


_LEGAL_TOKENS = r"\b(SAS|SASU|SA|SARL|EURL|SCI|SNC|SCA|SCS|SE|GIE|SELARL|HOLDING|GROUP|GROUPE|INC|LTD|LLC|LLP|PLC|GMBH|AG|BV|NV|" \
                r"SPA|SRL|LDA|FUND|FONDS|TRUST|FOUNDATION|FONDATION|CAPITAL|PARTNERS|INVEST|INVESTMENTS|LIMITED|CORP|" \
                r"CORPORATION|COMPANY|SOCIETE|SOCIÉTÉ|ASSOCIATION|FCPR|FPCI|SICAV|SCPI)\b"


def is_legal_entity(name: str) -> bool:
    """Associé personne morale (société, fonds, trust…) plutôt que personne physique."""
    if not name:
        return False
    if re.search(r"^(Madame|Monsieur|Mademoiselle|M\.|Mme|Mlle)\b", name.strip()):
        return False
    return bool(re.search(_LEGAL_TOKENS, _strip(name).upper()))


def same_person(a: str, b: str) -> tuple[bool, bool]:
    """(même personne ?, orthographe différente ?) — rapprochement prudent."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False, False
    exact = ta & tb
    fuzzy_pairs = [(x, y) for x in ta - exact for y in tb - exact if fuzz.ratio(x, y) >= 80 and x[0] == y[0]]
    hits = len(exact) + len(fuzzy_pairs)
    if hits >= 2 or (hits >= 1 and min(len(ta), len(tb)) == 1):
        return True, bool(fuzzy_pairs)
    return False, False


# ---------------------------------------------------------------------------
# Modèle
# ---------------------------------------------------------------------------

@dataclass
class Person:
    name: str
    parts: float | None = None
    pct: float | None = None
    role: str = ""
    dividend: float | None = None


@dataclass
class Subsidiary:
    name: str
    form: str = ""
    siren: str = ""
    pct: float | None = None
    city: str = ""
    country: str = ""


@dataclass
class KYC:
    name: str = ""
    siren: str = ""
    siren_valid: bool = False
    legal_form: str = ""
    capital: float | None = None
    address: str = ""
    ape: str = ""
    activity: str = ""
    closing: str = ""
    registry: str = ""
    associates: list[Person] = field(default_factory=list)
    total_parts: float | None = None
    declared_10pct: list[str] = field(default_factory=list)  # noms déclarés au 2033-F / 2059-F
    managers: list[Person] = field(default_factory=list)
    subsidiaries: list[Subsidiary] = field(default_factory=list)
    establishments: list[str] = field(default_factory=list)
    dividends_decided: float | None = None
    dividends_by_person: list[Person] = field(default_factory=list)
    distributions_paid_2065: float | None = None
    result_in_minutes: float | None = None
    auditors: list[str] = field(default_factory=list)
    audit_opinion: str = ""  # sans réserve / avec réserve / refus / impossibilité / absent
    audit_observation: bool = False
    going_concern_doubt: bool = False
    regulated: list[str] = field(default_factory=list)
    listed: bool = False
    countries: dict[str, int] = field(default_factory=dict)
    fines: list[str] = field(default_factory=list)
    restructuring: list[str] = field(default_factory=list)
    governance_changes: list[str] = field(default_factory=list)
    tax_losses_carried: float | None = None
    headcount: float | None = None
    related_party_cc: float | None = None
    sector_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    activity_desc: str = ""  # phrase des documents décrivant l'activité

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "KYC":
        k = KYC(**{x: y for x, y in d.items() if x not in {"associates", "managers", "subsidiaries", "dividends_by_person"}})
        k.associates = [Person(**p) for p in d.get("associates", [])]
        k.managers = [Person(**p) for p in d.get("managers", [])]
        k.dividends_by_person = [Person(**p) for p in d.get("dividends_by_person", [])]
        k.subsidiaries = [Subsidiary(**s) for s in d.get("subsidiaries", [])]
        return k


# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------

def load_countries() -> dict:
    return json.loads((DATA / "countries.json").read_text(encoding="utf-8"))


def load_risk_lists() -> dict:
    return json.loads((DATA / "risk_lists.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_TITLE = r"(?:Madame|Monsieur|Mademoiselle|M\.|Mme|Mlle|MME|MLE)"
_NAME = r"[A-ZÀ-Ý][\wÀ-ÿ'\-]+(?:\s+(?:[A-ZÀ-Ý][\wÀ-ÿ'\-]+|épouse|epouse|née|nee))*"

SECTOR_KEYWORDS = {
    "Services de paiement / monnaie électronique": r"etablissement de (services de )?paiement|monnaie electronique|services? de paiement|psp\b|acquisition monetique",
    "Crypto-actifs": r"crypto|actifs numeriques|psan|casp\b|blockchain|bitcoin",
    "Change / transfert de fonds": r"bureau de change|transfert de fonds|money transfer|remittance",
    "Immobilier": r"\bsci\b|marchand de biens|promotion immobiliere|location de terrains|activites immobilieres|real estate",
    "Jeux d'argent": r"jeux d'argent|casino|paris sportifs|gambling",
    "Biens de luxe / métaux précieux / art": r"metaux precieux|bijouterie|joaillerie|oeuvres d'art|antiquites|horlogerie de luxe",
    "Holding / gestion de participations": r"\bholding\b|activites des sieges sociaux|gestion de participations|activites des societes holding",
    "Négoce international": r"negoce international|import-export|trading de matieres premieres",
}

APE_RISK = {
    "7010Z": "Activités des sièges sociaux, holding animatrice",
    "6420Z": "Activités des sociétés holding",
    "6430Z": "Fonds de placement et entités financières similaires",
    "6820A": "Location de logements",
    "6820B": "Location de terrains et d'autres biens immobiliers",
    "6810Z": "Activités des marchands de biens immobiliers",
    "6619B": "Autres activités auxiliaires de services financiers",
    "6612Z": "Courtage de valeurs mobilières et de marchandises",
    "9200Z": "Organisation de jeux de hasard et d'argent",
    "4777Z": "Commerce de détail d'articles d'horlogerie et de bijouterie",
}


def _first(patterns: list[str], text: str, flags=re.I) -> re.Match | None:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m
    return None


def extract_kyc(text: str, fmt: str) -> KYC:
    k = KYC()
    flat = re.sub(r"[ \t]+", " ", text)
    low = _strip(flat).lower()

    # --- Identité -----------------------------------------------------------
    m = _first([r"Nom ou d[ée]nomination\s*:\s*([^\n]+)",
                r"D[ée]signation de l.entreprise\s*:?\s*([A-Z0-9][A-Z0-9 &'\.\-]{2,60})",
                r"D[ÉE]NOMINATION DE L.ENTREPRISE\s*\|?\s*([A-Z0-9][A-Z0-9 &'\.\-]{2,60})"], flat)
    if m:
        k.name = re.sub(r"\s+(Po|\||Néant).*$", "", m.group(1)).strip(" |[]")
    if not k.name:
        for line in flat.splitlines()[:8]:
            line = line.strip()
            if re.match(r"^[A-Z][A-Za-z0-9&\.\- ]{2,40}(Inc\.|SAS|SA|SARL|SE|plc|Ltd)?$", line) and not re.search(r"\d{3}", line):
                k.name = line
                break
    # SIREN de la société : première occurrence valide hors contexte d'un tiers (commissaire aux comptes,
    # actionnaire, filiale), la clé de Luhn écartant les erreurs d'OCR
    third = re.compile(r"commissa|compagnie r[ée]gionale|deloitte|kpmg|mazars|pwc|pricewaterhouse|ernst|grant thornton|"
                       r"\bexco\b|bdo|rsm|associ[ée] unique|soussign|filiale|d[ée]nomination\s+\w|% de d[ée]tention|"
                       r"soci[ée]t[ée] m[èe]re|actionnaire", re.I)
    cands: list[tuple[int, str, bool]] = []
    for mm in re.finditer(r"(?<!\d)(\d{3})\s?(\d{3})\s?(\d{3})(?:\s?(\d{5}))?(?!\d)", flat):
        ctx = flat[max(0, mm.start() - 40): mm.start()].lower()
        if any(w in ctx for w in ("siren", "siret", "r.c.s", "rcs", "registre", "immatricul")) or mm.group(4) \
                or re.match(r"\s*R\.?C\.?S", flat[mm.end(): mm.end() + 8]):
            wide = flat[max(0, mm.start() - 160): mm.end() + 60]
            cands.append((mm.start(), mm.group(1) + mm.group(2) + mm.group(3), bool(third.search(wide))))
    for mm in re.finditer(r"SIRET\D{0,15}(\d{14})", flat, re.I):
        cands.append((mm.start(), mm.group(1)[:9], False))
    cands.sort()
    valid = [c for c in cands if luhn_ok(c[1])]
    own = [c for c in valid if not c[2]]
    pick = own or valid
    if pick:
        # première occurrence, sauf si un autre numéro est nettement plus fréquent hors tiers
        counts = {c[1]: sum(1 for x in pick if x[1] == c[1]) for c in pick}
        k.siren = max(pick, key=lambda c: (counts[c[1]], -c[0]))[1] if max(counts.values()) >= 3 else pick[0][1]
        k.siren_valid = True
    elif cands:
        k.siren = cands[0][1]
    forms = re.findall(r"\b(SASU|SAS|SARL|EURL|SCI|SNC|SCA|SELARL|SA|Inc\.|Ltd|LLC|plc|GmbH)(?=[\s,.]|$)", flat)
    if forms:
        k.legal_form = max(set(forms), key=lambda f: (forms.count(f), len(f)))
    m = re.search(r"(?:Soci[ée]t[ée] par actions simplifi[ée]e|soci[ée]t[ée] anonyme|soci[ée]t[ée] [àa] responsabilit[ée] limit[ée]e)", flat, re.I)
    if m and not k.legal_form:
        k.legal_form = {"par actions": "SAS", "anonyme": "SA", "responsabilit": "SARL"}[
            next(x for x in ("par actions", "anonyme", "responsabilit") if x in m.group(0).lower())]
    m = re.search(r"capital (?:social )?de\s*([\d][\d . ]*[\d])\s*(?:€|euros)", flat, re.I)
    if m:
        k.capital = _num(m.group(1))
    addrs = [m.group(1).strip(" ,(“”\"") for m in re.finditer(r"Si[eè]ge social\s*:?\s*\n?\s*([^\n]{8,90})", flat, re.I)]
    addrs = [a for a in addrs if re.search(r"\d{5}", a)] or addrs
    if addrs:
        k.address = addrs[0]
    m = re.search(r"\bAPE\s*:?\s*(\d{2})\.?(\d{2})\s?([A-Z])\b", flat) or re.search(r"\bAPE\s*:?\s*(\d{2})(\d{2})\s?([A-Z])", flat)
    if m:
        k.ape = m.group(1) + m.group(2) + m.group(3)
    m = re.search(r"Activit[ée]s exerc[ée]es\s*:?[\s\S]{0,60}?\b([A-Z][A-Z \-]{3,40})\b", flat)
    if m and m.group(1).strip() not in {"N", "SI"}:
        k.activity = m.group(1).strip()
    m = _first([r"(?:exercice|ann[ée]e) clos(?:e)? (?:le|au)\s*:?\s*(\d{1,2}[/ ]\w+[/ ]\d{4})",
                r"Cl[ôo]ture au\s*:?\s*(\d{2}/\d{2}/\d{4})", r"(?:Three|Six|Nine) Months Ended\s+(\w+ \d{1,2},\s*\d{4})",
                r"Exercice N clos le\s*(\d{2}/\d{2}/\d{4})"], flat)
    if m:
        k.closing = m.group(1)
    elif fmt == "US":
        m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}),"
                      r"(?:\s*(\d{4})|[^\n]*\n\s*(\d{4}))", flat)
        if m:
            k.closing = f"{m.group(1)}, {m.group(2) or m.group(3)}"
    m = re.search(r"R\.?C\.?S\.?\s*:?\s*([A-Z][a-zé\-]+)", flat) or re.search(r"(\d{3} \d{3} \d{3})\s*R\.?C\.?S\.?\s*([A-Z][a-zé\-]+)", flat)
    if m:
        k.registry = m.group(m.lastindex)

    # --- Associés (procès-verbaux) ----------------------------------------
    for mm in re.finditer(_TITLE + r"\s+(" + _NAME + r")\s*:?\s*\n?\s*(?:[àa]\s+)?concurrence de\s+([\d .]+?)\s*(parts|actions)",
                          flat):
        nm = re.sub(r"\s+", " ", mm.group(1)).strip()
        k.associates.append(Person(nm, _num(mm.group(2))))
    # associé unique / actionnaire à 100 % (« … détenant l'intégralité du capital »)
    if not k.associates:
        m = re.search(r"(?:soussign[ée]e?|associ[ée] unique)\s*,?\s*([A-Z][A-Za-z0-9&'\- ]{2,60}?)\s*,\s*soci[ée]t[ée][\s\S]{0,400}?"
                      r"d[ée]tenant l.int[ée]gralit[ée] du capital", flat)
        if m:
            k.associates.append(Person(m.group(1).strip(), pct=100.0, role="Associé unique"))
    m = re.search(r"divis[ée] en\s*([\d .]+?)\s*(parts|actions)", flat, re.I)
    if m:
        k.total_parts = _num(m.group(1))
    if not k.total_parts and k.associates:
        k.total_parts = sum(p.parts or 0 for p in k.associates) or None
    if k.total_parts:
        for p in k.associates:
            if p.parts and p.pct is None:
                p.pct = round(100 * p.parts / k.total_parts, 2)
    # 2033-F / 2059-F : personnes physiques détenant au moins 10 %
    for mm in re.finditer(r"Nom patronymique[^A-Za-z]{0,8}([A-Z][A-Z\-]{1,30})", flat):
        first = re.search(r"Pr[ée]?n?[oi]?n?oms?\)?\W{0,4}([A-Z]{2,30})", flat[mm.end(): mm.end() + 80], re.I)
        nm = mm.group(1) + (" " + first.group(1).rstrip("L") if first else "")
        k.declared_10pct.append(nm.strip())

    # --- Dirigeants ----------------------------------------------------------
    for mm in re.finditer(_TITLE + r"\s+(" + _NAME + r"),?\s+en sa qualit[ée] de\s+(G[ée]rant|Pr[ée]sident|Directeur G[ée]n[ée]ral)", flat):
        k.managers.append(Person(re.sub(r"\s+", " ", mm.group(1)), role=mm.group(2)))
    for mm in re.finditer(r"Repr[ée]sent[ée]e? par\s+" + _TITLE + r"\s+(" + _NAME + r"),?\s*\n?\s*(Pr[ée]sident|G[ée]rant|Directeur G[ée]n[ée]ral)", flat):
        k.managers.append(Person(re.sub(r"\s+", " ", mm.group(1)), role=mm.group(2)))
    for mm in re.finditer(r"Nom du signataire\s*:?\s*([A-Z][A-Z \-]{3,40}?)\s+Qualit[ée] du signataire\s*:?\s*([A-Z]+)", flat):
        k.managers.append(Person(mm.group(1).strip().title(), role=mm.group(2).title()))
    uniq: list[Person] = []
    for p in k.managers:
        if not any(same_person(p.name, q.name)[0] for q in uniq):
            uniq.append(p)
    k.managers = uniq

    # --- Filiales (tableau des filiales et participations) -------------------
    for mm in re.finditer(r"Forme juridique\s+(\S+)\s+D[ée]nomination\s+([^\n]+)\n(?:[^\n]*\n){0,1}?[^\n]*?SIREN\s+(\d{9})?\s*%? ?de d[ée]tention\s+([\d.,]+)?"
                          r"(?:[^\n]*\n){1,3}?[^\n]*?Commune\s+([A-Z][A-Z \-]+?)\s+Pays\s+([A-Z]{2})", flat):
        name = mm.group(2).strip(" |")
        if not name or name.lower().startswith(("n°", "forme")):
            continue
        k.subsidiaries.append(Subsidiary(name, mm.group(1), mm.group(3) or "", _num(mm.group(4)) if mm.group(4) else None,
                                         mm.group(5).strip(), mm.group(6)))
    for mm in re.finditer(r"^(.{3,60}?)\s+(Portugal|Belgique|Italie|Espagne|Allemagne|Luxembourg|Royaume-Uni|Suisse|Pays-Bas|Irlande|Maroc|Tunisie|S[ée]n[ée]gal|C[ôo]te d.Ivoire)\s+[\d.,]+\s?%\s+([ÉE]tablissement|Filiale|Succursale)",
                          flat, re.M):
        k.establishments.append(f"{mm.group(1).strip()} ({mm.group(2)}, {mm.group(3).lower()})")

    # --- Distributions -----------------------------------------------------
    m = re.search(r"distribution de dividendes? (?:[àa] hauteur de|d.un montant de|de)\s*([\d .,]+?)\s*(?:€|euros)", flat, re.I)
    if m:
        k.dividends_decided = _num(m.group(1))
        tail = flat[m.end(): m.end() + 700]
        for mm in re.finditer(r"^\s*" + _TITLE + r"\s+(" + _NAME + r")\s+([\d][\d .]*[\d])\s*€", tail, re.M):
            k.dividends_by_person.append(Person(re.sub(r"\s+", " ", mm.group(1)), dividend=_num(mm.group(2))))
    elif re.search(r"\b0 euros? au titre des dividendes|aucun dividende", flat, re.I):
        k.dividends_decided = 0.0
    m = re.search(r"Montant global brut des distributions[\s\S]{0,260}?(?<![\d(])(\d{1,3}(?: \d{3})+|\d{4,})(?!\d)", flat)
    if m:
        k.distributions_paid_2065 = _num(m.group(1))
    m = _first([r"r[ée]sultat net de\s*([\d .,]+?)\s*(?:€|euros)",
                r"r[ée]sultat de l.exercice[^\n]{0,40}?s.[ée]levant [àa]\s*([\d ., ]+?)\s*(?:€|euros)",
                r"b[ée]n[ée]fice de l.exercice (?:de|s.[ée]levant [àa])\s*([\d .,]+?)\s*(?:€|euros)"], flat)
    if m:
        k.result_in_minutes = _num(m.group(1))

    # --- Audit ---------------------------------------------------------------
    if re.search(r"commissaires? aux comptes|independent registered public accounting firm|auditor.s report", low):
        for name in ("Deloitte", "KPMG", "PwC", "PricewaterhouseCoopers", "EY", "Ernst & Young", "Mazars", "Forvis Mazars",
                     "Grant Thornton", "BDO", "RSM", "Exco", "Baker Tilly", "Crowe", "Aplitec", "Fiducial"):
            if re.search(r"\b" + re.escape(name) + r"\b", flat):
                k.auditors.append(name)
    one = re.sub(r"\s+", " ", low)
    if re.search(r"opinion avec reserve|sous reserve (?:de|des)[^.]{0,400}nous certifions", one):
        k.audit_opinion = "avec réserve"
    elif re.search(r"nous refusons de certifier|^refus de certifier\s*$", low, re.M):
        k.audit_opinion = "refus de certifier"
    elif re.search(r"nous sommes dans l.impossibilite de certifier|nous ne sommes pas en mesure de certifier|^impossibilite de certifier\s*$", low, re.M):
        k.audit_opinion = "impossibilité de certifier"
    elif re.search(r"nous certifions que les comptes (?:annuels|consolides) sont[^.]{0,120}reguliers et sinceres", one) \
            or re.search(r"present fairly, in all material respects", one):
        k.audit_opinion = "sans réserve"
    elif "commissaires aux comptes" in low and "certifions" not in low:
        k.audit_opinion = "rapport de certification non fourni"
    else:
        k.audit_opinion = "aucun rapport d'audit dans les documents"
    k.audit_observation = bool(re.search(r"sans remettre en cause l.opinion", one))
    # l'incertitude doit être constatée (pas la phrase type sur les responsabilités du CAC)
    k.going_concern_doubt = bool(re.search(r"incertitude significative (?:sur|relative a) la continuite d.exploitation", one)
                                 and not re.search(r"s.il conclut a l.existence d.une incertitude significative", one)) or \
        bool(re.search(r"^incertitude significative sur la continuite d.exploitation\s*$", low, re.M))

    # --- Statut réglementé / coté --------------------------------------------
    for label, pat in (("Agrément ACPR (établissement de paiement)", r"agrement[^.]{0,120}etablissement de (services de )?paiement|etablissement de (services de )?paiement[^.]{0,120}agrement"),
                       ("Établissement de monnaie électronique", r"etablissement de monnaie electronique"),
                       ("Établissement de crédit", r"agrement[^.]{0,60}etablissement de credit"),
                       ("Supervision ACPR", r"\bacpr\b|autorite de controle prudentiel"),
                       ("Supervision AMF / PSAN", r"\bamf\b|autorite des marches financiers|\bpsan\b")):
        if re.search(pat, low):
            k.regulated.append(label)
    k.listed = bool(re.search(r"earnings per share|form 10-[qk]|securities and exchange commission|nasdaq|nyse|euronext|"
                              r"admises? aux negociations sur un marche reglemente", low))

    # --- Pays cités ------------------------------------------------------------
    countries = load_countries()
    for canon, variants in countries.items():
        cnt = 0
        for v in variants:
            cnt += len(re.findall(r"(?<![a-z])" + re.escape(_strip(v).lower()) + r"(?![a-z])(?!\s+de\s+fusion)", low))
        if cnt:
            k.countries[canon] = cnt

    # --- Autres signaux textuels ----------------------------------------------
    for mm in re.finditer(r"^[^\n]*\b(amendes?|p[ée]nalit[ée]s?|sanctions? (?:administratives?|pecuniaires?|de l.acpr))\b[^\n]*$", flat, re.M | re.I):
        line = mm.group(0).strip()
        if len(line) < 160 and not re.search(r"notice|cocher|imprim", line, re.I):
            k.fines.append(line)
    for pat, lab in ((r"fusion[- ]absorption|mali de fusion|boni de fusion", "Fusion / absorption"),
                     (r"apport partiel d.actif|transmission universelle de patrimoine|\btup\b", "Apport / TUP"),
                     (r"cession de l.activit|cession de titres|cession de la branche", "Cession d'activité ou de titres"),
                     (r"augmentation de capital|reduction de capital", "Opération sur le capital")):
        if re.search(pat, low):
            k.restructuring.append(lab)
    for pat, lab in ((r"modification de l.article \d+ des statuts|statuts mis a jour", "Modification des statuts"),
                     (r"transfert du siege", "Transfert du siège"),
                     (r"nomination d[eu]s? (?:nouveau|directeur|president|gerant)|est nomme", "Nomination de dirigeant"),
                     (r"demission|revocation", "Départ de dirigeant"),
                     (r"dirigeants? effectifs?|quatre yeux", "Gouvernance réglementaire (dirigeants effectifs)")):
        if re.search(pat, low):
            k.governance_changes.append(lab)
    m = re.search(r"D[ée]ficits? restant [àa] reporter au titre de l.exercice pr[ée]c[ée]dent[^\n]*?(\d[\d ]{2,})\s*$", flat, re.M)
    if m:
        k.tax_losses_carried = _num(m.group(1))
    m = re.search(r"^Effectifs?\s+(\d{1,6})\b", flat, re.M) or re.search(r"Effectifs? moyens? du personnel\s*:?\s*(\d{1,6})\b", flat)
    if m:
        k.headcount = float(m.group(1))
    m = re.search(r"[Cc]omptes? courants? (?:d.associ[ée]s|entreprises li[ée]es|groupe)\s*:?\s*([\d][\d .]*[\d])\s*(milliers|k€|€)?", flat)
    if m:
        v = _num(m.group(1))
        if v is not None and m.group(2) and m.group(2).startswith(("milliers", "k")):
            v *= 1000
        k.related_party_cc = v
    # Description de l'activité : première phrase explicite trouvée dans les documents
    one_line = re.sub(r"\s+", " ", flat)
    for pat in (r"(?:La soci[ée]t[ée]|Le groupe|La Soci[ée]t[ée])[^.]{0,60}?(?:a (?:pour |une )?activit[ée]|a pour objet|exerce|est sp[ée]cialis[ée]e|con[çc]oit|propose|offre)[^.]{15,300}\.",
                r"(?:The Company|The Group|We)[^.]{0,40}?(?:designs|operates|provides|is engaged|manufactures|develops|offers)[^.]{15,300}\.",
                r"Activit[ée]s? (?:principale|exerc[ée]e)s?\s*:\s*[^.\n]{3,120}"):
        m = re.search(pat, one_line)
        if m:
            k.activity_desc = m.group(0).strip()[:320]
            break
    for lab, pat in SECTOR_KEYWORDS.items():
        if re.search(pat, low):
            k.sector_flags.append(lab)
    if k.ape in APE_RISK:
        k.notes.append(f"Code APE {k.ape} : {APE_RISK[k.ape]}")
    if any(s.form.upper() == "SCI" for s in k.subsidiaries) and "Immobilier" not in k.sector_flags:
        k.sector_flags.append("Immobilier")
    return k

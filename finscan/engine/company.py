"""Une société = un ou plusieurs documents (exercices différents) fusionnés en une
seule série chronologique. C'est l'objet que l'on analyse."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field

from .aml import analyse_aml
from .analysis import consolidate, health, ratios
from .dossier import Dossier
from .extract import Extraction, Value
from .kyc import KYC

NO_UNIT = {"eps_basic", "eps_diluted", "headcount"}


def period_sort_key(p: str) -> tuple:
    m = re.match(r"(\d{4})", p)
    year = int(m.group(1)) if m else 0
    mm = re.search(r"\((\d+) m\)", p)
    months = int(mm.group(1)) if mm else 12
    return (year, months)


def company_key(d: Dossier) -> str:
    if d.kyc.siren and d.kyc.siren_valid:
        return "siren:" + d.kyc.siren
    name = unicodedata.normalize("NFKD", d.kyc.name or d.file_name)
    name = "".join(c for c in name if not unicodedata.combining(c)).lower()
    name = re.sub(r"\b(sas|sasu|sarl|sa|sci|eurl|inc|ltd|plc|group|groupe|se)\b|[^a-z0-9]", "", name)
    return "name:" + name


@dataclass
class Company:
    id: str
    name: str
    doc_ids: list[str] = field(default_factory=list)
    overrides: dict[str, dict[str, float | None]] = field(default_factory=dict)  # saisies (unités monétaires)
    kyc: dict | None = None  # identification corrigée par l'analyste
    consumed: list[str] = field(default_factory=list)  # lignes non reconnues déjà rattachées
    extra_periods: list[str] = field(default_factory=list)  # années ajoutées à la main
    key: str = ""


@dataclass
class View:
    """Vue fusionnée d'une société : mêmes attributs qu'un document pour le rapport."""
    id: str
    name: str
    ex: Extraction
    kyc: KYC
    file_name: str
    n_pages: int
    ocr_pages: list[int]
    sources: list[dict]
    warnings: list[str]

    def analyse(self) -> dict:
        ex = copy.deepcopy(self.ex)  # consolidate peut rattacher une ligne : on travaille sur une copie
        f, controls = consolidate(ex, self.kyc)
        r = ratios(f, ex)
        h = health(f, ex, r)
        a = analyse_aml(f, ex, self.kyc)
        f.notes = self.warnings + f.notes
        return {"fin": f, "controls": controls, "ratios": r, "health": h, "aml": a, "ex": ex}


def _abs(key: str, raw: float | None, d: Dossier) -> float | None:
    if raw is None:
        return None
    if key in NO_UNIT:
        return raw
    if key == "shares_diluted":
        return raw * (1000 if d.ex.fmt == "US" else 1)
    return raw * d.ex.unit


def merge(c: Company, docs: dict[str, Dossier]) -> View:
    ds = [docs[i] for i in c.doc_ids if i in docs]
    if not ds:
        raise ValueError("Société sans document")
    # le document le plus récent d'abord : ses chiffres (y compris comparatifs retraités) priment
    ds.sort(key=lambda d: max((period_sort_key(p) for p in d.ex.periods), default=(0, 0)), reverse=True)
    newest = ds[0]
    ex = Extraction(newest.ex.fmt, 1.0, "unités", newest.ex.currency, newest.ex.period_months, newest.ex.period_label)
    warnings = []
    if len({d.ex.currency for d in ds}) > 1:
        warnings.append("Attention : documents en devises différentes (" + ", ".join(sorted({d.ex.currency for d in ds})) +
                        ") — les montants ne sont pas convertis.")
    if len({d.ex.fmt for d in ds}) > 1:
        warnings.append("Documents de formats différents fusionnés (" + ", ".join(sorted({d.ex.fmt for d in ds})) +
                        ") : vérifier la comparabilité des postes.")
    sources = []
    for d in ds:
        sources.append({"doc_id": d.id, "fichier": d.file_name, "périodes": ", ".join(d.ex.periods), "format": d.ex.fmt})
        for p in d.ex.periods:
            if p not in ex.months:
                ex.months[p] = d.ex.months.get(p, d.ex.period_months)
        for key, v in d.ex.values.items():
            tgt = ex.values.setdefault(key, Value({}, v.page, f"{d.file_name} p.{v.page} : {v.source}", v.auto))
            for p, raw in v.vals.items():
                if tgt.vals.get(p) is None and raw is not None:
                    tgt.vals[p] = _abs(key, raw, d)
                    if not v.auto:
                        tgt.auto = False
        for i, u in enumerate(d.ex.unmatched):
            uid = f"{d.id}:{i}"
            if uid in c.consumed:
                continue
            ex.unmatched.append({**u, "id": uid, "doc": d.file_name,
                                 "vals": {p: _abs("x", x, d) for p, x in u.get("vals", {}).items()}})
        if not ex.breakdowns and d.ex.breakdowns:
            ex.breakdowns = {k: [(n, _abs("x", v, d)) for n, v in items] for k, items in d.ex.breakdowns.items()}
    # années ajoutées à la main, puis saisies de l'analyste
    for p in c.extra_periods:
        ex.months.setdefault(p, 12)
    for key, vals in c.overrides.items():
        tgt = ex.values.setdefault(key, Value({}, None, "saisie manuelle", False))
        for p, x in vals.items():
            tgt.vals[p] = x
            ex.months.setdefault(p, 12)
        tgt.auto = False
    ex.periods = sorted({p for p in ex.months}, key=period_sort_key, reverse=True)
    # une période sans aucune donnée n'est pas affichée (sauf ajout manuel)
    used = {p for v in ex.values.values() for p, x in v.vals.items() if x is not None} | set(c.extra_periods)
    ex.periods = [p for p in ex.periods if p in used]
    ex.months = {p: ex.months[p] for p in ex.periods}
    ex.period_months = ex.months.get(ex.periods[0], 12) if ex.periods else 12

    if c.kyc:
        kyc = KYC.from_dict(c.kyc)
    else:
        kyc = copy.deepcopy(newest.kyc)
        for d in ds[1:]:  # compléter les champs vides à partir des documents plus anciens
            for k_, v_ in d.kyc.to_dict().items():
                cur = getattr(kyc, k_)
                if cur in (None, "", [], {}) and v_ not in (None, "", [], {}):
                    setattr(kyc, k_, copy.deepcopy(getattr(d.kyc, k_)))
    return View(c.id, c.name, ex, kyc, " + ".join(d.file_name for d in ds), sum(d.n_pages for d in ds),
                sorted({p for d in ds for p in d.ocr_pages}), sources, warnings)


def new_company(d: Dossier) -> Company:
    return Company(hashlib.sha1(company_key(d).encode()).hexdigest()[:10], d.kyc.name or d.file_name, [d.id], key=company_key(d))


def company_to_json(c: Company, docs: dict[str, Dossier]) -> str:
    return json.dumps({"schema": 2, "type": "société", "company": asdict(c),
                       "documents": [json.loads(docs[i].to_json()) for i in c.doc_ids if i in docs],
                       "exported": dt.datetime.now().isoformat(timespec="minutes")}, ensure_ascii=False, indent=1)


def company_from_json(s: str) -> tuple[Company | None, list[Dossier]]:
    d = json.loads(s)
    if d.get("type") == "société":
        docs = [Dossier.from_json(json.dumps(x)) for x in d["documents"]]
        return Company(**d["company"]), docs
    return None, [Dossier.from_json(s)]  # ancien format : un seul document

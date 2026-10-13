"""Un dossier = une société analysée. Il se sauvegarde en JSON pour être
rechargé plus tard avec les corrections de l'analyste."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field

from .extract import Extraction, Value, extract
from .ingest import Document, load_pdf
from .kyc import KYC, extract_kyc

SCHEMA = 1


@dataclass
class Dossier:
    id: str
    file_name: str
    ex: Extraction
    kyc: KYC
    ocr_pages: list[int] = field(default_factory=list)
    n_pages: int = 0
    created: str = ""
    display_name: str = ""

    @property
    def name(self) -> str:
        return self.display_name or self.kyc.name or self.file_name

    # ------------------------------------------------------------------ calcul
    def analyse(self) -> dict:
        """Analyse du document seul (une société = un document)."""
        from .company import Company, merge
        return merge(Company(self.id, self.name, [self.id]), {self.id: self}).analyse()

    # ------------------------------------------------------------- sérialisation
    def to_json(self) -> str:
        ex = asdict(self.ex)
        return json.dumps({"schema": SCHEMA, "id": self.id, "file_name": self.file_name, "display_name": self.display_name,
                           "created": self.created, "ocr_pages": self.ocr_pages, "n_pages": self.n_pages,
                           "extraction": ex, "kyc": self.kyc.to_dict()}, ensure_ascii=False, indent=1)

    @staticmethod
    def from_json(s: str) -> "Dossier":
        d = json.loads(s)
        e = d["extraction"]
        ex = Extraction(e["fmt"], e["unit"], e["unit_label"], e["currency"], e["period_months"], e["period_label"])
        ex.periods = e.get("periods", [])
        ex.months = e.get("months", {})
        for k, v in e.get("values", {}).items():
            if "vals" not in v:  # dossiers enregistrés avant le passage multi-exercices
                v = {"vals": {"N": v.get("n"), "N-1": v.get("n1")}, "page": v.get("page"), "source": v.get("source", ""),
                     "auto": v.get("auto", True)}
            ex.values[k] = Value(**v)
        ex.unmatched = e.get("unmatched", [])
        if not ex.periods:  # ancien format : N / N-1 → années à partir de la clôture lue
            import re as _re
            yr = None
            m = _re.search(r"((?:19|20)\d{2})", d.get("kyc", {}).get("closing", "") or "")
            yr = int(m.group(1)) if m else 0
            ren = {"N": str(yr) if yr else "N", "N-1": str(yr - 1) if yr else "N-1"}
            for v in ex.values.values():
                v.vals = {ren.get(k, k): x for k, x in v.vals.items()}
            for u in ex.unmatched:
                u["vals"] = {ren["N"]: u.pop("N", None), ren["N-1"]: u.pop("N-1", None)}
            ex.periods = [ren["N"], ren["N-1"]]
            ex.months = {p: ex.period_months for p in ex.periods}
        ex.breakdowns = {k: [tuple(x) for x in v] for k, v in e.get("breakdowns", {}).items()}
        return Dossier(d["id"], d["file_name"], ex, KYC.from_dict(d["kyc"]), d.get("ocr_pages", []),
                       d.get("n_pages", 0), d.get("created", ""), d.get("display_name", ""))


def build_dossier(data: bytes, file_name: str, doc: Document | None = None, fmt: str | None = None,
                  ocr: bool = True, dpi: int = 300, progress=None) -> Dossier:
    doc = doc or load_pdf(data, file_name, ocr=ocr, dpi=dpi, progress=progress)
    ex = extract(doc, fmt)
    k = extract_kyc(doc.text, ex.fmt)
    did = hashlib.sha1(data).hexdigest()[:12]
    return Dossier(did, file_name, ex, k, doc.ocr_pages, len(doc.pages), dt.datetime.now().isoformat(timespec="minutes"))

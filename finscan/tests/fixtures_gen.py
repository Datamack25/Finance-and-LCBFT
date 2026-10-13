"""Génère des états financiers FICTIFS (sociétés inventées) pour tester la lecture
multi-exercices : comptes sociaux PCG sur 3 années, IFRS en français, IFRS en
anglais et un 10-K US GAAP sur 3 exercices.

    python -m tests.fixtures_gen tests/fixtures/demo
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def fr(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{abs(v):,.0f}".replace(",", " ")
    return f"({s})" if v < 0 else s


def en(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{abs(v):,.0f}"
    return f"({s})" if v < 0 else s


class Doc:
    def __init__(self, path: Path, fmt_num=fr):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.y = 800
        self.fmt = fmt_num

    def title(self, text, size=14):
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawString(50, self.y, text)
        self.y -= size + 10

    def text(self, text, size=10):
        self.c.setFont("Helvetica", size)
        self.c.drawString(50, self.y, text)
        self.y -= size + 6

    def header(self, labels, xs, label=""):
        self.c.setFont("Helvetica-Bold", 9)
        if label:
            self.c.drawString(50, self.y, label)
        for lab, x in zip(labels, xs):
            self.c.drawRightString(x, self.y, lab)
        self.y -= 16

    def row(self, label, values, xs, bold=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        self.c.drawString(56, self.y, label)
        for v, x in zip(values, xs):
            self.c.drawRightString(x, self.y, self.fmt(v) if isinstance(v, (int, float)) or v is None else v)
        self.y -= 14

    def page(self):
        self.c.showPage()
        self.y = 800

    def save(self):
        self.c.save()


# ---------------------------------------------------------------------------
# 1. NOVALIS SAS — comptes sociaux PCG, trois PDF (2022, 2023, 2024)
# ---------------------------------------------------------------------------

def _siren() -> str:
    base = "81234567"
    for d in range(10):
        s = base + str(d)
        tot = 0
        for i, ch in enumerate(reversed(s)):
            x = int(ch) * (2 if i % 2 else 1)
            tot += x - 9 if x > 9 else x
        if tot % 10 == 0:
            return s
    raise RuntimeError


def novalis_years() -> dict[int, dict]:
    ys: dict[int, dict] = {}
    ran = 150_000
    for i, y in enumerate((2021, 2022, 2023, 2024)):
        ca = round(1_800_000 * 1.12 ** i)
        d = {"ca": ca, "achats": round(ca * 0.38), "ext": round(ca * 0.17), "imp": round(ca * 0.02), "sal": round(ca * 0.22),
             "soc": round(ca * 0.09), "dap": 60_000 + 5_000 * i, "fin_inc": 4_000, "fin_exp": 18_000 - 2_000 * i,
             "exc_inc": 0, "exc_exp": 3_000}
        ebit = ca - sum(d[k] for k in ("achats", "ext", "imp", "sal", "soc", "dap"))
        pre = ebit + d["fin_inc"] - d["fin_exp"] + d["exc_inc"] - d["exc_exp"]
        d["is"] = round(max(pre, 0) * 0.25)
        d["rn"] = pre - d["is"]
        d["immo_corp_brut"] = 900_000 + 40_000 * i
        d["immo_corp_amort"] = 350_000 + 60_000 * i
        d["immo_fin"] = 50_000
        d["stocks"] = round(ca * 0.08)
        d["clients"] = round(ca * 0.15)
        d["autres_cr"] = 35_000
        d["capital"] = 100_000
        d["reserve"] = 10_000
        d["ran"] = ran
        d["emprunts"] = 400_000 - 70_000 * i
        d["fourn"] = round(ca * 0.10)
        d["fisc"] = round(ca * 0.06)
        d["autres_d"] = 25_000
        cp = d["capital"] + d["reserve"] + d["ran"] + d["rn"]
        passif = cp + d["emprunts"] + d["fourn"] + d["fisc"] + d["autres_d"]
        actif_hors_dispo = (d["immo_corp_brut"] - d["immo_corp_amort"]) + d["immo_fin"] + d["stocks"] + d["clients"] + d["autres_cr"]
        d["dispo"] = passif - actif_hors_dispo
        d["cp"] = cp
        d["total"] = passif
        ys[y] = d
        ran = ran + d["rn"] - (40_000 if y >= 2022 else 0)  # dividende de 40 k€ versé chaque année
    return ys


def make_novalis(out: Path) -> list[Path]:
    ys = novalis_years()
    siren = _siren()
    paths = []
    for y in (2022, 2023, 2024):
        n, n1 = ys[y], ys[y - 1]
        p = out / f"novalis_{y}.pdf"
        doc = Doc(p, fr)
        doc.title("NOVALIS SAS")
        doc.text(f"Société par actions simplifiée au capital de 100 000 €  -  SIREN {siren[:3]} {siren[3:6]} {siren[6:]} RCS Lyon")
        doc.text("Siège social : 12 rue des Tanneurs 69002 Lyon  -  APE 2562B")
        doc.text(f"Comptes annuels - exercice clos le 31/12/{y}  (montants en euros)")
        doc.y -= 6
        xs4 = (330, 410, 490, 565)
        doc.header(["Brut", "Amort.", f"31/12/{y}", f"31/12/{y - 1}"], xs4, "BILAN ACTIF")
        doc.row("Immobilisations corporelles", [n["immo_corp_brut"], n["immo_corp_amort"], n["immo_corp_brut"] - n["immo_corp_amort"],
                                               n1["immo_corp_brut"] - n1["immo_corp_amort"]], xs4)
        doc.row("Immobilisations financières", [n["immo_fin"], None, n["immo_fin"], n1["immo_fin"]], xs4)
        doc.row("Stocks et en-cours", [n["stocks"], None, n["stocks"], n1["stocks"]], xs4)
        doc.row("Clients et comptes rattachés", [n["clients"], None, n["clients"], n1["clients"]], xs4)
        doc.row("Autres créances", [n["autres_cr"], None, n["autres_cr"], n1["autres_cr"]], xs4)
        doc.row("Disponibilités", [n["dispo"], None, n["dispo"], n1["dispo"]], xs4)
        doc.row("Total de l'actif", [None, None, n["total"], n1["total"]], xs4, bold=True)
        doc.y -= 10
        xs2 = (490, 565)
        doc.header([f"31/12/{y}", f"31/12/{y - 1}"], xs2, "BILAN PASSIF")
        for lab, k in (("Capital social", "capital"), ("Réserve légale", "reserve"), ("Report à nouveau", "ran"),
                       ("Résultat de l'exercice", "rn")):
            doc.row(lab, [n[k], n1[k]], xs2)
        doc.row("Total capitaux propres", [n["cp"], n1["cp"]], xs2, bold=True)
        for lab, k in (("Emprunts et dettes auprès des établissements de crédit", "emprunts"),
                       ("Fournisseurs et comptes rattachés", "fourn"), ("Dettes fiscales et sociales", "fisc"),
                       ("Autres dettes", "autres_d")):
            doc.row(lab, [n[k], n1[k]], xs2)
        doc.row("Total du passif", [n["total"], n1["total"]], xs2, bold=True)
        doc.page()
        doc.header([f"31/12/{y}", f"31/12/{y - 1}"], xs2, "COMPTE DE RÉSULTAT")
        doc.row("Chiffre d'affaires net", [n["ca"], n1["ca"]], xs2)
        for lab, k in (("Achats de marchandises", "achats"), ("Autres achats et charges externes", "ext"),
                       ("Impôts, taxes et versements assimilés", "imp"), ("Salaires et traitements", "sal"),
                       ("Charges sociales", "soc"), ("Dotations aux amortissements", "dap")):
            doc.row(lab, [n[k], n1[k]], xs2)
        ebit = lambda d: d["ca"] - sum(d[k] for k in ("achats", "ext", "imp", "sal", "soc", "dap"))
        doc.row("Résultat d'exploitation", [ebit(n), ebit(n1)], xs2, bold=True)
        for lab, k in (("Produits financiers", "fin_inc"), ("Charges financières", "fin_exp"),
                       ("Charges exceptionnelles", "exc_exp"), ("Impôts sur les bénéfices", "is")):
            doc.row(lab, [n[k], n1[k]], xs2)
        doc.row("Bénéfice ou perte", [n["rn"], n1["rn"]], xs2, bold=True)
        doc.page()
        doc.title("Procès-verbal de l'assemblée générale ordinaire")
        doc.text(f"Les associés de NOVALIS SAS au capital de 100 000 euros, divisé en 1 000 actions, se sont réunis.")
        doc.text("- Monsieur Karim BENALI : à concurrence de 600 actions")
        doc.text("- Madame Sophie MARCHAND : à concurrence de 400 actions")
        doc.text("Monsieur Karim BENALI, en sa qualité de Président, préside la réunion.")
        doc.text(f"L'assemblée approuve les comptes se soldant par un résultat net de {fr(n['rn'])} €.")
        doc.text("L'assemblée décide une distribution de dividendes à hauteur de 40 000 euros répartie comme suit :")
        doc.text("M. Karim BENALI 24 000 €")
        doc.text("Mme Sophie MARCHAND 16 000 €")
        doc.save()
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# 2. GROUPE ATLANTIS — IFRS, en français, 3 exercices (en millions d'euros)
# ---------------------------------------------------------------------------

ATLANTIS = {
    "rev": (1520, 1384, 1250), "cogs": (912, 845, 775), "sga": (298, 270, 248), "rd": (61, 55, 50), "ebit": (249, 214, 177),
    "fin_exp": (32, 35, 37), "fin_inc": (6, 4, 3), "pretax": (223, 183, 143), "tax": (58, 48, 37), "ni": (165, 135, 106),
    "goodwill": (420, 420, 380), "intang": (95, 88, 80), "ppe": (610, 575, 540), "rou": (88, 92, 96), "fin_nc": (40, 38, 35),
    "inv": (190, 176, 160), "rec": (265, 248, 231), "oca": (45, 41, 39), "cash": (310, 245, 205),
    "cap": (100, 100, 100), "prem": (250, 250, 250), "res": (695, 597, 512), "nci": (25, 22, 20),
    "debt_nc": (520, 540, 560), "lease_nc": (70, 75, 80), "prov": (45, 42, 40), "debt_c": (80, 70, 60), "lease_c": (18, 17, 16),
    "pay": (240, 225, 205), "ocl": (165, 156, 148), "eps": (1.62, 1.33, 1.04),
    "cfo": (268, 230, 192), "capex": (102, 95, 90), "div": (55, 50, 45),
}


def make_atlantis(out: Path) -> Path:
    a = ATLANTIS
    nc_assets = tuple(a["goodwill"][i] + a["intang"][i] + a["ppe"][i] + a["rou"][i] + a["fin_nc"][i] for i in range(3))
    c_assets = tuple(a["inv"][i] + a["rec"][i] + a["oca"][i] + a["cash"][i] for i in range(3))
    tot = tuple(nc_assets[i] + c_assets[i] for i in range(3))
    eq_grp = tuple(a["cap"][i] + a["prem"][i] + a["res"][i] + a["ni"][i] - a["nci"][i] // 5 for i in range(3))
    eq = tuple(eq_grp[i] + a["nci"][i] for i in range(3))
    ncl = tuple(a["debt_nc"][i] + a["lease_nc"][i] + a["prov"][i] for i in range(3))
    # passifs courants : on ajuste « autres passifs courants » pour équilibrer
    cl_wo = tuple(a["debt_c"][i] + a["lease_c"][i] + a["pay"][i] for i in range(3))
    ocl = tuple(tot[i] - eq[i] - ncl[i] - cl_wo[i] for i in range(3))
    cl = tuple(cl_wo[i] + ocl[i] for i in range(3))
    p = out / "atlantis_ifrs_2024.pdf"
    doc = Doc(p, fr)
    xs = (420, 490, 560)
    hdr = ["2024", "2023", "2022"]
    doc.title("GROUPE ATLANTIS SA")
    doc.text("Comptes consolidés au 31 décembre 2024 établis selon les normes IFRS - (en millions d'euros)")
    doc.y -= 4
    doc.title("État de la situation financière consolidée", 12)
    doc.header(hdr, xs, "ACTIF")
    for lab, k in (("Goodwill", "goodwill"), ("Autres immobilisations incorporelles", "intang"), ("Immobilisations corporelles", "ppe"),
                   ("Droits d'utilisation", "rou"), ("Actifs financiers non courants", "fin_nc")):
        doc.row(lab, list(a[k]), xs)
    doc.row("Total actifs non courants", list(nc_assets), xs, bold=True)
    for lab, k in (("Stocks", "inv"), ("Clients et comptes rattachés", "rec"), ("Autres actifs courants", "oca"),
                   ("Trésorerie et équivalents de trésorerie", "cash")):
        doc.row(lab, list(a[k]), xs)
    doc.row("Total actifs courants", list(c_assets), xs, bold=True)
    doc.row("Total actif", list(tot), xs, bold=True)
    doc.y -= 8
    doc.header(hdr, xs, "CAPITAUX PROPRES ET PASSIFS")
    doc.row("Capital social", list(a["cap"]), xs)
    doc.row("Primes liées au capital", list(a["prem"]), xs)
    doc.row("Réserves consolidées", [a["res"][i] - a["nci"][i] // 5 for i in range(3)], xs)
    doc.row("Résultat net part du groupe", list(a["ni"]), xs)
    doc.row("Capitaux propres part du groupe", list(eq_grp), xs)
    doc.row("Participations ne donnant pas le contrôle", list(a["nci"]), xs)
    doc.row("Total capitaux propres", list(eq), xs, bold=True)
    doc.row("Emprunts et dettes financières non courants", list(a["debt_nc"]), xs)
    doc.row("Dettes locatives non courantes", list(a["lease_nc"]), xs)
    doc.row("Provisions non courantes", list(a["prov"]), xs)
    doc.row("Total passifs non courants", list(ncl), xs, bold=True)
    doc.row("Emprunts et dettes financières courants", list(a["debt_c"]), xs)
    doc.row("Dettes locatives courantes", list(a["lease_c"]), xs)
    doc.row("Fournisseurs et comptes rattachés", list(a["pay"]), xs)
    doc.row("Autres passifs courants", list(ocl), xs)
    doc.row("Total passifs courants", list(cl), xs, bold=True)
    doc.row("Total capitaux propres et passifs", list(tot), xs, bold=True)
    doc.page()
    doc.title("Compte de résultat consolidé", 12)
    doc.header(hdr, xs, "(en millions d'euros)")
    doc.row("Chiffre d'affaires", list(a["rev"]), xs)
    doc.row("Coût des ventes", [-x for x in a["cogs"]], xs)
    doc.row("Marge brute", [a["rev"][i] - a["cogs"][i] for i in range(3)], xs, bold=True)
    doc.row("Frais commerciaux et administratifs", [-x for x in a["sga"]], xs)
    doc.row("Frais de recherche et développement", [-x for x in a["rd"]], xs)
    doc.row("Résultat opérationnel", list(a["ebit"]), xs, bold=True)
    doc.row("Produits financiers", list(a["fin_inc"]), xs)
    doc.row("Charges financières", [-x for x in a["fin_exp"]], xs)
    doc.row("Résultat avant impôt", list(a["pretax"]), xs, bold=True)
    doc.row("Impôt sur le résultat", [-x for x in a["tax"]], xs)
    doc.row("Résultat net de l'ensemble consolidé", list(a["ni"]), xs, bold=True)
    doc.c.setFont("Helvetica", 9)
    doc.row("Résultat de base par action (en euros)", [f"{x:.2f}".replace(".", ",") for x in a["eps"]], xs)
    doc.y -= 10
    doc.title("Tableau des flux de trésorerie consolidés", 12)
    doc.header(hdr, xs)
    doc.row("Flux net de trésorerie généré par l'activité", list(a["cfo"]), xs)
    doc.row("Acquisitions d'immobilisations corporelles et incorporelles", [-x for x in a["capex"]], xs)
    doc.row("Dividendes versés", [-x for x in a["div"]], xs)
    doc.save()
    return p


# ---------------------------------------------------------------------------
# 3. NORTHWIND PLC — IFRS en anglais (£ million), 3 exercices
# ---------------------------------------------------------------------------

def make_northwind(out: Path) -> Path:
    p = out / "northwind_ifrs_2024.pdf"
    doc = Doc(p, en)
    xs = (420, 490, 560)
    hdr = ["2024", "2023", "2022"]
    doc.title("Northwind plc")
    doc.text("Consolidated financial statements prepared in accordance with IFRS - £ million")
    doc.title("Consolidated income statement", 12)
    doc.header(hdr, xs, "Year ended 31 December")
    rows = [("Revenue", (842, 790, 701)), ("Cost of sales", (-505, -482, -436)), ("Gross profit", (337, 308, 265)),
            ("Administrative expenses", (-198, -187, -170)), ("Operating profit", (139, 121, 95)), ("Finance costs", (-21, -24, -26)),
            ("Profit before tax", (118, 97, 69)), ("Income tax expense", (-29, -23, -16)), ("Profit for the year", (89, 74, 53))]
    for lab, v in rows:
        doc.row(lab, list(v), xs, bold=lab.startswith(("Gross", "Operating", "Profit")))
    doc.y -= 10
    doc.title("Consolidated statement of financial position", 12)
    doc.header(hdr, xs, "Assets")
    nca = [(" Property, plant and equipment", (402, 388, 370)), ("Intangible assets", (155, 160, 165))]
    for lab, v in nca:
        doc.row(lab.strip(), list(v), xs)
    doc.row("Total non-current assets", [557, 548, 535], xs, bold=True)
    ca = [("Inventories", (96, 90, 82)), ("Trade and other receivables", (151, 140, 128)), ("Cash and cash equivalents", (88, 61, 47))]
    for lab, v in ca:
        doc.row(lab, list(v), xs)
    doc.row("Total current assets", [335, 291, 257], xs, bold=True)
    doc.row("Total assets", [892, 839, 792], xs, bold=True)
    doc.y -= 6
    doc.header(hdr, xs, "Equity and liabilities")
    doc.row("Share capital", [50, 50, 50], xs)
    doc.row("Retained earnings", [361, 302, 258], xs)
    doc.row("Total equity", [411, 352, 308], xs, bold=True)
    doc.row("Non-current borrowings", [260, 290, 310], xs)
    doc.row("Trade and other payables", [181, 164, 150], xs)
    doc.row("Current borrowings", [40, 33, 24], xs)
    doc.row("Total current liabilities", [221, 197, 174], xs, bold=True)
    doc.row("Total liabilities", [481, 487, 484], xs, bold=True)
    doc.row("Total equity and liabilities", [892, 839, 792], xs, bold=True)
    doc.page()
    doc.title("Consolidated statement of cash flows", 12)
    doc.header(hdr, xs)
    doc.row("Net cash generated from operating activities", [131, 112, 90], xs)
    doc.row("Purchase of property, plant and equipment", [-58, -54, -61], xs)
    doc.row("Dividends paid", [-30, -30, -25], xs)
    doc.save()
    return p


# ---------------------------------------------------------------------------
# 4. CONTOSO CORP — 10-K US GAAP, 3 exercices (in millions)
# ---------------------------------------------------------------------------

def make_contoso(out: Path) -> Path:
    p = out / "contoso_10k_2024.pdf"
    doc = Doc(p, en)
    xs = (420, 490, 560)
    doc.title("CONTOSO CORPORATION - FORM 10-K")
    doc.text("CONSOLIDATED STATEMENTS OF OPERATIONS (In millions, except per-share amounts)")
    doc.header(["Years Ended December 31,", "", ""], (300, 0, 0))
    doc.y += 16
    doc.header(["2024", "2023", "2022"], xs)
    rows = [("Total net sales", (12450, 11380, 10220)), ("Total cost of sales", (7100, 6600, 6050)), ("Gross margin", (5350, 4780, 4170)),
            ("Research and development", (1210, 1100, 980)), ("Selling, general and administrative", (1890, 1750, 1640)),
            ("Total operating expenses", (3100, 2850, 2620)), ("Operating income", (2250, 1930, 1550)),
            ("Other income/(expense), net", (-40, -55, -70)), ("Income before provision for income taxes", (2210, 1875, 1480)),
            ("Provision for income taxes", (464, 394, 311)), ("Net income", (1746, 1481, 1169))]
    for lab, v in rows:
        doc.row(lab, list(v), xs)
    doc.text("Earnings per share:")
    doc.row("Diluted", ["3.49", "2.95", "2.31"], xs)
    doc.y -= 10
    doc.text("CONSOLIDATED BALANCE SHEETS (In millions)")
    doc.text("December 31,")
    doc.header(["2024", "2023"], (490, 560))
    doc.text("ASSETS:")
    doc.text("Current assets:")
    for lab, v in (("Cash and cash equivalents", (2900, 2400)), ("Accounts receivable, net", (1650, 1500)),
                   ("Inventories", (980, 940)), ("Total current assets", (5530, 4840)),
                   ("Property, plant and equipment, net", (4100, 3900)), ("Total assets", (9630, 8740))):
        doc.row(lab, list(v), (490, 560))
    doc.text("LIABILITIES AND SHAREHOLDERS' EQUITY:")
    doc.text("Current liabilities:")
    for lab, v in (("Accounts payable", (1400, 1310)), ("Total current liabilities", (2300, 2150)), ("Term debt", (2100, 2300)),
                   ("Total liabilities", (4400, 4450)), ("Total shareholders' equity", (5230, 4290)),
                   ("Total liabilities and shareholders' equity", (9630, 8740))):
        doc.row(lab, list(v), (490, 560))
    doc.page()
    doc.text("CONSOLIDATED STATEMENTS OF CASH FLOWS (In millions)")
    doc.header(["2024", "2023", "2022"], xs)
    for lab, v in (("Cash generated by operating activities", (2310, 1990, 1700)),
                   ("Payments for acquisition of property, plant and equipment", (-650, -610, -580)),
                   ("Payments for dividends and dividend equivalents", (-520, -480, -440)), ("Repurchases of common stock", (-300, -250, -0))):
        doc.row(lab, list(v), xs)
    doc.save()
    return p


def make_all(out: Path) -> dict[str, list[Path]]:
    out.mkdir(parents=True, exist_ok=True)
    return {"novalis": make_novalis(out), "atlantis": [make_atlantis(out)], "northwind": [make_northwind(out)],
            "contoso": [make_contoso(out)]}


if __name__ == "__main__":
    res = make_all(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/demo"))
    for k, v in res.items():
        print(k, [str(x) for x in v])

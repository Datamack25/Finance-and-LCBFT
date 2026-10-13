"""Lecture LCB-FT des comptes : signaux d'attention issus des états
financiers et des documents juridiques joints.

Ces signaux ne constituent pas un soupçon : ils orientent les
diligences (vigilance renforcée, justificatifs, origine des fonds…).
La décision et, le cas échéant, la déclaration de soupçon restent du
ressort du déclarant (art. L.561-15 CMF).
"""
from __future__ import annotations

from dataclasses import dataclass

from .analysis import Fin, _div
from .extract import Extraction
from .kyc import KYC, is_legal_entity, load_risk_lists, name_tokens, same_person

LEVEL_POINTS = {"élevé": 20, "modéré": 10, "faible": 4, "info": 0, "atténuant": -8}


@dataclass
class Signal:
    categorie: str
    titre: str
    niveau: str
    constat: str
    pourquoi: str
    diligence: str

    @property
    def points(self) -> int:
        return LEVEL_POINTS[self.niveau]

    def to_dict(self) -> dict:
        return {"catégorie": self.categorie, "signal": self.titre, "niveau": self.niveau, "constat": self.constat,
                "pourquoi": self.pourquoi, "diligence": self.diligence, "points": self.points}


def _fmt(x: float | None, cur: str = "€") -> str:
    if x is None:
        return "n/d"
    return f"{x:,.0f} {cur}".replace(",", " ")


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def analyse_aml(f: Fin, ex: Extraction, k: KYC) -> dict:
    g = f.get
    cur = "$" if ex.currency == "USD" else "€"
    S: list[Signal] = []
    lists = load_risk_lists()
    rev, rev1 = g("revenue"), g("revenue", "n1")
    ta = g("total_assets")
    ni, ni1 = g("net_income"), g("net_income", "n1")

    # ------------------------------------------------------------------ Structure
    holding = any(s in k.sector_flags for s in ("Holding / gestion de participations",)) or k.ape in {"7010Z", "6420Z", "6430Z"}
    if holding and rev is not None and ta:
        ratio = rev / ta
        if ratio < 0.10:
            S.append(Signal("Structure & activité", "Structure patrimoniale à faible activité opérationnelle", "modéré",
                            f"Chiffre d'affaires {_fmt(rev, cur)} pour un total de bilan de {_fmt(ta, cur)} ({_pct(ratio)}). "
                            f"Activité déclarée : holding{' (APE ' + k.ape + ')' if k.ape else ''}.",
                            "Les structures de détention offrent un écran entre les flux et les bénéficiaires effectifs ; "
                            "la faible activité rend plus difficile l'appréciation de la cohérence économique des flux.",
                            "Obtenir l'organigramme complet, l'objet des participations et la justification des prestations facturées "
                            "(conventions de management, refacturations)."))
    fi = g("financial_income")
    if fi and rev and fi > rev:
        S.append(Signal("Structure & activité", "Revenus majoritairement financiers", "faible",
                        f"Produits financiers {_fmt(fi, cur)} = {_pct(fi / rev)} du chiffre d'affaires.",
                        "Dividendes, intérêts et plus-values remontés des participations : leur origine dépend de la santé et de l'activité des filiales.",
                        "Rapprocher les produits financiers des comptes des filiales (dividendes versés, intérêts de comptes courants)."))
    liquid = g("liquid")
    if liquid and ta and liquid / ta > 0.40 and ex.fmt != "BANK" and (rev or 0) < 0.25 * ta:
        S.append(Signal("Flux & trésorerie", "Actifs liquides importants au regard de l'activité", "modéré",
                        f"Trésorerie et placements {_fmt(liquid, cur)} = {_pct(liquid / ta)} du bilan, pour un CA de {_fmt(rev, cur)}.",
                        "Un portefeuille de placements élevé sans activité correspondante appelle une explication de l'origine des fonds.",
                        "Documenter l'origine du portefeuille (cessions, dividendes, apports) et obtenir les relevés de placements."))
    sci = [s for s in k.subsidiaries if s.form.upper() == "SCI"]
    if sci:
        S.append(Signal("Structure & activité", "Participations dans des SCI", "faible",
                        f"{len(sci)} SCI détenue(s) : " + ", ".join(f"{s.name} ({s.pct:g} %)" if s.pct else s.name for s in sci) + ".",
                        "Les sociétés civiles immobilières sont un vecteur classique d'investissement de fonds d'origine non justifiée (typologies Tracfin).",
                        "Identifier les associés et bénéficiaires effectifs de chaque SCI, les biens détenus et leur mode de financement."))
    if k.subsidiaries:
        same_addr = [s for s in k.subsidiaries if s.city and k.address and s.city.lower() in k.address.lower()]
        S.append(Signal("Structure & activité", "Filiales et participations", "info",
                        f"{len(k.subsidiaries)} entité(s) détenue(s) ; {len(same_addr)} à la même commune que le siège.",
                        "Cartographie du groupe nécessaire pour remonter aux bénéficiaires effectifs et repérer les flux intra-groupe.",
                        "Vérifier chaque SIREN (statut actif, dirigeants, dépôts de comptes) et l'éventuelle domiciliation commune."))

    # ------------------------------------------------------------------ Actionnariat
    if k.associates:
        over = [p for p in k.associates if (p.pct or 0) > 25]
        natural = [p for p in over if not is_legal_entity(p.name)]
        legal = [p for p in over if is_legal_entity(p.name)]
        if natural or not legal:
            S.append(Signal("Actionnariat & bénéficiaires effectifs", "Bénéficiaires effectifs présumés (plus de 25 % du capital)", "info",
                            ("; ".join(f"{p.name} : {p.pct:g} %" for p in natural) or "Aucune personne physique au-delà de 25 %") + ".",
                            "Art. R.561-1 CMF : est bénéficiaire effectif la personne physique qui détient, directement ou "
                            "indirectement, plus de 25 % du capital ou des droits de vote, ou exerce un contrôle par tout autre moyen.",
                            "Comparer au Registre des bénéficiaires effectifs (RBE) et signaler toute divergence."))
        for p in legal:
            S.append(Signal("Actionnariat & bénéficiaires effectifs",
                            "Actionnaire personne morale : remonter la chaîne de détention", "modéré" if (p.pct or 0) >= 50 else "faible",
                            f"{p.name} détient {p.pct:g} % du capital{' (associé unique)' if (p.pct or 0) >= 99.9 else ''}. "
                            "Les bénéficiaires effectifs sont les personnes physiques qui contrôlent cette entité, directement ou "
                            "par une chaîne de sociétés.",
                            "Une personne morale ne peut pas être bénéficiaire effectif : tant que la chaîne n'est pas remontée "
                            "jusqu'aux personnes physiques, l'identification des bénéficiaires effectifs reste incomplète "
                            "(art. R.561-1 et R.561-2 CMF). À défaut de personne physique identifiable, le représentant légal est retenu.",
                            f"Obtenir le Kbis et le RBE de {p.name}, l'organigramme du groupe jusqu'aux personnes physiques et les "
                            "pourcentages indirects ; si l'actionnaire est coté sur un marché réglementé, le documenter (vigilance "
                            "allégée possible sur ce niveau)."))
    if k.dividends_by_person and k.associates and k.total_parts:
        total_div = sum(p.dividend or 0 for p in k.dividends_by_person)
        gaps, variants = [], []
        for d in k.dividends_by_person:
            match = None
            for a in k.associates:
                ok, variant = same_person(d.name, a.name)
                if ok:
                    match = a
                    if variant:
                        variants.append(f"« {d.name} » / « {a.name} »")
                    break
            if match and match.pct is not None and total_div:
                share = 100 * (d.dividend or 0) / total_div
                d.pct = round(share, 1)
                if abs(share - match.pct) > 5:
                    gaps.append(f"{match.name} : {match.pct:g} % du capital, {share:.0f} % des dividendes")
        if gaps:
            S.append(Signal("Actionnariat & bénéficiaires effectifs", "Répartition des dividendes non proportionnelle au capital", "élevé",
                            "; ".join(gaps) + ".",
                            "Une répartition décorrélée de la détention peut traduire un démembrement (usufruit / nue-propriété), une clause "
                            "statutaire, ou un bénéficiaire économique différent du titulaire apparent des parts. Un associé qui perçoit plus de 25 % "
                            "des distributions peut être bénéficiaire effectif même avec moins de 25 % du capital.",
                            "Demander les statuts à jour, les actes de donation / démembrement et la décision d'affectation ; mettre à jour la liste "
                            "des bénéficiaires effectifs."))
        if variants:
            S.append(Signal("Actionnariat & bénéficiaires effectifs", "Orthographe des noms divergente selon les documents", "faible",
                            ", ".join(variants) + ".",
                            "Les écarts d'état civil compliquent le filtrage (gel des avoirs, PPE) et la correspondance avec le RBE.",
                            "Fixer l'identité sur pièce d'identité et filtrer toutes les variantes."))
    if k.associates and k.declared_10pct is not None:
        over10 = [p for p in k.associates if (p.pct or 0) >= 10]
        if k.declared_10pct and len(k.declared_10pct) < len(over10):
            S.append(Signal("Actionnariat & bénéficiaires effectifs", "Déclaration fiscale de l'actionnariat incomplète", "faible",
                            f"{len(over10)} associés détiennent au moins 10 % selon le procès-verbal ; {len(k.declared_10pct)} déclaré(s) "
                            "dans l'imprimé de composition du capital (2033-F / 2059-F).",
                            "Les associés à 10 % doivent figurer dans la liasse : une omission fragilise la fiabilité des déclarations.",
                            "Faire confirmer la composition exacte du capital par le dirigeant ou l'expert-comptable."))

    # ------------------------------------------------------------------ Distributions
    div = k.dividends_decided if k.dividends_decided is not None else None
    if ex.fmt == "US":
        div = g("dividends_paid")
    if div and ni is not None and div > max(ni, 0) * 1.05:
        S.append(Signal("Flux & trésorerie", "Distribution supérieure au résultat de l'exercice", "modéré" if ex.fmt != "US" else "info",
                        f"Dividendes {_fmt(div, cur)} pour un résultat de {_fmt(ni, cur)} (prélèvement sur réserves / report à nouveau).",
                        "Une distribution qui excède le bénéfice réduit les fonds propres ; elle est légale si les réserves le permettent, mais "
                        "doit être rapprochée de la trésorerie disponible et de la destination des fonds.",
                        "Vérifier les comptes bénéficiaires des dividendes et leur cohérence avec le profil des associés."))
    if k.distributions_paid_2065 and ni1 is not None and ni1 < 0:
        S.append(Signal("Flux & trésorerie", "Distribution après un exercice déficitaire", "modéré",
                        f"{_fmt(k.distributions_paid_2065, cur)} distribués au cours de l'exercice alors que l'exercice précédent "
                        f"affiche une perte de {_fmt(abs(ni1), cur)}.",
                        "Distribution financée par les réserves dans un contexte de perte : signal d'extraction de valeur à documenter.",
                        "Obtenir la décision d'AG correspondante et les justificatifs de paiement."))

    # ------------------------------------------------------------------ Cohérence
    exc = max(g("exceptional_income") or 0, g("exceptional_expense") or 0, g("exceptional_income", "n1") or 0, g("exceptional_expense", "n1") or 0)
    base = max(rev or 0, rev1 or 0)
    if exc and base and exc > 0.5 * base:
        S.append(Signal("Cohérence économique", "Éléments exceptionnels massifs", "modéré",
                        f"Montant exceptionnel maximum sur N/N-1 : {_fmt(exc, cur)} pour un CA de {_fmt(base, cur)}.",
                        "Les opérations exceptionnelles (cessions, abandons de créances, dépréciations) sont propices à des transferts de valeur.",
                        "Obtenir le détail des comptes 67/77 et les pièces justificatives des opérations significatives."))
    if rev and rev1 and rev1 > 0 and abs(rev / rev1 - 1) > 0.5:
        S.append(Signal("Cohérence économique", "Variation forte de l'activité", "faible",
                        f"CA {_fmt(rev1, cur)} → {_fmt(rev, cur)} ({(rev / rev1 - 1) * 100:+.0f} %).",
                        "Une croissance ou une chute brutale doit être expliquée par un événement identifiable.",
                        "Demander l'explication au client et la rapprocher du rapport de gestion."))
    orc, orc1 = g("other_receivables"), g("other_receivables", "n1")
    if orc and rev and orc > 0.5 * rev and ex.fmt == "PCG":
        S.append(Signal("Cohérence économique", "Autres créances élevées", "faible",
                        f"Autres créances {_fmt(orc, cur)} ({_pct(orc / rev)} du CA)" + (f", contre {_fmt(orc1, cur)} en N-1." if orc1 else "."),
                        "Les « autres créances » regroupent souvent des avances à des parties liées ou des comptes courants débiteurs.",
                        "Obtenir la balance détaillée : nature, contreparties, conventions de compte courant."))
    if k.related_party_cc:
        lvl = "faible" if not ta or k.related_party_cc / ta < 0.1 else "modéré"
        S.append(Signal("Cohérence économique", "Comptes courants avec parties liées", lvl,
                        f"Comptes courants entreprises liées / associés : {_fmt(k.related_party_cc, cur)}"
                        + (f" ({_pct(k.related_party_cc / ta)} du bilan)." if ta else "."),
                        "Les avances intra-groupe permettent de déplacer des fonds sans flux commercial.",
                        "Vérifier les conventions de trésorerie et leur approbation (conventions réglementées)."))
    if k.fines:
        S.append(Signal("Gouvernance & conformité", "Amendes ou pénalités", "faible",
                        "Mentions relevées : " + " | ".join(k.fines[:3]),
                        "Des amendes peuvent révéler des manquements réglementaires ou fiscaux.",
                        "Identifier l'autorité, le motif et le caractère récurrent."))

    # ------------------------------------------------------------------ Gouvernance & audit
    eq, cap = g("equity"), g("share_capital")
    if eq is not None and cap and eq < cap / 2 and ex.fmt != "US":
        S.append(Signal("Gouvernance & conformité", "Capitaux propres inférieurs à la moitié du capital", "élevé",
                        f"Capitaux propres {_fmt(eq, cur)} pour un capital de {_fmt(cap, cur)}.",
                        "Situation légale (art. L.223-42 / L.225-248 C. com.) imposant une décision des associés ; risque de continuité.",
                        "Vérifier la décision de poursuite d'activité et les mesures de reconstitution."))
    op = k.audit_opinion
    if op == "sans réserve":
        S.append(Signal("Gouvernance & conformité", "Comptes certifiés sans réserve", "atténuant",
                        f"Opinion sans réserve{(' (' + ', '.join(k.auditors) + ')') if k.auditors else ''}"
                        + (" assortie d'une observation." if k.audit_observation else "."),
                        "La certification par un commissaire aux comptes renforce la fiabilité des comptes présentés.",
                        "Conserver le rapport au dossier."))
    elif op in ("avec réserve", "refus de certifier", "impossibilité de certifier"):
        S.append(Signal("Gouvernance & conformité", f"Opinion d'audit : {op}", "élevé",
                        f"Le commissaire aux comptes a émis : {op}.",
                        "Les comptes ne peuvent être pris tels quels comme base d'appréciation de la situation du client.",
                        "Lire le fondement de l'opinion et obtenir les explications de la direction."))
    elif not k.listed:
        S.append(Signal("Gouvernance & conformité", "Pas de certification des comptes dans le dossier", "info",
                        "Aucun rapport de commissaire aux comptes parmi les documents analysés.",
                        "Sous les seuils légaux, l'audit n'est pas obligatoire ; les comptes reposent alors sur la seule déclaration de la société.",
                        "Si l'enjeu le justifie, demander une attestation de l'expert-comptable ou des relevés bancaires."))
    if k.going_concern_doubt:
        S.append(Signal("Gouvernance & conformité", "Incertitude sur la continuité d'exploitation", "élevé",
                        "Le rapport d'audit mentionne une incertitude significative sur la continuité d'exploitation.",
                        "Risque de défaillance et de comportements atypiques en période de difficulté.", "Suivre la situation de près."))
    if k.restructuring:
        S.append(Signal("Gouvernance & conformité", "Opérations de restructuration", "info",
                        ", ".join(sorted(set(k.restructuring))) + ".",
                        "Fusions, apports et cessions modifient le périmètre et peuvent masquer des transferts d'actifs.",
                        "Obtenir les traités / actes et vérifier l'évaluation retenue."))
    if k.governance_changes:
        S.append(Signal("Gouvernance & conformité", "Changements de gouvernance ou de statuts", "info",
                        ", ".join(sorted(set(k.governance_changes))) + ".",
                        "Toute modification des organes de direction doit être reflétée dans la connaissance client.",
                        "Mettre à jour la liste des dirigeants et des mandataires."))

    # ------------------------------------------------------------------ Géographie
    countries = set(k.countries) | {s.country for s in k.subsidiaries if s.country and s.country != "FR"}
    black = sorted(c for c in countries if c in lists["fatf_black"])
    grey = sorted(c for c in countries if c in lists["fatf_grey"] or c in lists.get("eu_high_risk", []))
    sanc = sorted(c for c in countries if c in lists["sanctions_regimes"])
    off = sorted(c for c in countries if c in lists["offshore"])
    if black:
        S.append(Signal("Géographie", "Pays à haut risque (liste noire GAFI) cités", "élevé", ", ".join(black) + ".",
                        "Contre-mesures et vigilance renforcée obligatoires (art. L.561-10 CMF).",
                        "Établir la nature exacte du lien avec ces pays ; vigilance renforcée systématique."))
    if grey:
        S.append(Signal("Géographie", "Pays sous surveillance renforcée (liste grise GAFI / UE) cités", "modéré", ", ".join(grey) + ".",
                        "Juridictions présentant des déficiences stratégiques LCB-FT.",
                        "Qualifier les flux et contreparties liés à ces pays."))
    if sanc:
        S.append(Signal("Géographie", "Pays visés par des régimes de sanctions cités", "modéré", ", ".join(sanc) + ".",
                        "Risque d'exposition à des mesures restrictives (gel des avoirs, restrictions sectorielles).",
                        "Filtrer contreparties et bénéficiaires sur les listes UE/ONU/DG Trésor/OFAC."))
    if off:
        S.append(Signal("Géographie", "Centres financiers offshore cités", "faible", ", ".join(off) + ".",
                        "Structures à fiscalité privilégiée pouvant réduire la transparence.", "Identifier les entités et leurs bénéficiaires effectifs."))
    others = sorted(countries - set(black) - set(grey) - set(sanc) - set(off) - {"FR"})
    if others or k.establishments:
        S.append(Signal("Géographie", "Présence ou exposition internationale", "info",
                        ", ".join(others) + ("" if not k.establishments else " — établissements : " + "; ".join(k.establishments)) + ".",
                        "L'activité transfrontière augmente la complexité de traçabilité des flux.",
                        "Vérifier la cohérence des flux par pays avec l'implantation déclarée."))

    # ------------------------------------------------------------------ Secteur & statut
    for sf in k.sector_flags:
        if sf == "Holding / gestion de participations":
            continue
        lvl = "modéré" if sf in ("Services de paiement / monnaie électronique", "Crypto-actifs", "Change / transfert de fonds",
                                 "Jeux d'argent", "Biens de luxe / métaux précieux / art") else "faible"
        S.append(Signal("Secteur", f"Secteur à risque inhérent : {sf}", lvl,
                        f"Activité identifiée dans les documents : {sf.lower()}.",
                        "Secteur identifié par l'analyse nationale des risques (ANR) comme exposé au blanchiment.",
                        "Adapter le niveau de vigilance au secteur et documenter la connaissance de l'activité."))
    if k.regulated:
        S.append(Signal("Secteur", "Entité agréée et supervisée", "atténuant", ", ".join(k.regulated) + ".",
                        "Assujettie elle-même aux obligations LCB-FT et contrôlée par une autorité.",
                        "Vérifier l'agrément au registre REGAFI et l'absence de sanction publiée."))
    if k.listed:
        S.append(Signal("Secteur", "Société cotée", "atténuant", "Indices de cotation (états publiés, BPA, régulateur de marché).",
                        "Les sociétés cotées sur un marché réglementé peuvent relever d'une vigilance simplifiée (art. R.561-15 CMF), "
                        "sous réserve de l'appréciation du risque.",
                        "Vérifier le marché de cotation et conserver la preuve."))

    import math
    raw = max(0, sum(s.points for s in S) + 10)  # 10 = risque de base de toute relation d'affaires
    score = round(100 * (1 - math.exp(-raw / 60)))  # saturation progressive
    level = "Élevé" if score >= 55 else "Modéré" if score >= 30 else "Faible"
    order = {"élevé": 0, "modéré": 1, "faible": 2, "info": 3, "atténuant": 4}
    S.sort(key=lambda s: order[s.niveau])
    return {
        "score": score,
        "level": level,
        "signals": [s.to_dict() for s in S],
        "screening": screening_list(k),
        "lists_date": lists.get("_mise_a_jour"),
    }


def screening_list(k: KYC) -> list[dict]:
    """Personnes et entités à filtrer (gel des avoirs, sanctions, PPE)."""
    rows, seen = [], []
    for p in k.associates:
        kind = "personne morale" if is_legal_entity(p.name) else "personne physique"
        rows.append({"nom": p.name, "qualité": (f"Associé ({p.pct:g} %)" if p.pct is not None else "Associé") + f", {kind}"})
        seen.append(p.name)
    for p in k.managers:
        if not any(same_person(p.name, s)[0] for s in seen):
            rows.append({"nom": p.name, "qualité": p.role or "Dirigeant"})
            seen.append(p.name)
    for p in k.dividends_by_person:
        if not any(same_person(p.name, s)[0] for s in seen):
            rows.append({"nom": p.name, "qualité": "Bénéficiaire de dividendes"})
    if k.name:
        rows.insert(0, {"nom": k.name, "qualité": "Entité analysée"})
    for s in k.subsidiaries:
        rows.append({"nom": s.name, "qualité": f"Filiale / participation ({s.pct:g} %)" if s.pct else "Filiale / participation"})
    return rows

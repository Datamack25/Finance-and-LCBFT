# FinScan LCB-FT

Plateforme Streamlit d'analyse de sociétés : on dépose les états financiers, liasses fiscales, rapports annuels et
procès-verbaux d'une ou plusieurs sociétés (PDF natifs ou scannés), et l'outil restitue pour chacune :

- **les états financiers sur tous les exercices disponibles** (une colonne par année), corrigeables à la main, avec la
  page et le libellé source de chaque chiffre ;
- **la croissance de chaque poste** : variation annuelle en %, TCAM (taux de croissance annuel moyen) dès 3 exercices,
  courbes d'évolution ;
- **les ratios d'un investisseur** : croissance, marges, ROE/ROA, liquidité, gearing, dette nette/EBITDA,
  free cash-flow, retour à l'actionnaire (et, pour un établissement de paiement : PNB, coefficient
  d'exploitation, couverture des fonds de la clientèle) ;
- **un score de santé financière** sur 100 (rentabilité, liquidité, solvabilité, dynamique) et le Z-score d'Altman ;
- **une lecture LCB-FT** : bénéficiaires effectifs présumés, répartition des dividendes vs détention,
  distributions vs résultat, structure holding / SCI, actifs liquides sans activité, éléments exceptionnels,
  parties liées, opinion d'audit, statut réglementé, pays cités (listes GAFI, sanctions, centres offshore),
  avec pour chaque signal le constat chiffré, sa justification et la diligence à mener ;
- **la liste des noms à filtrer** (associés, dirigeants, bénéficiaires de dividendes, filiales) en CSV ;
- **une note de synthèse Word d'une page** : identité, secteur et activité, chiffres clés avec croissance, graphique
  CA / résultat net, santé financière, lecture LCB-FT, actionnariat et gouvernance ;
- **un classeur Excel complet** : Synthèse (avec graphique), Bilan, Compte de résultat, Flux de trésorerie (publiés, ou
  reconstitués par la méthode indirecte quand les comptes n'en contiennent pas), *Liasses et documents* (toutes les
  lignes chiffrées lues, document par document et page par page, y compris celles non rattachées à un poste), Ratios,
  Actionnaires, *Graphiques actionnaires* (répartition du capital, capital vs dividendes) et LCB-FT. Variations, TCAM,
  agrégats, ratios et pourcentages de détention sont des **formules** : corriger un chiffre met le classeur à jour ;
- **un rapport HTML autonome** par société et une **comparaison de portefeuille**.

Formats reconnus :

| Format | Exemples | Langue |
|---|---|---|
| PCG | liasses 2033 / 2050, comptes annuels présentés par l'expert-comptable | français |
| IFRS | comptes consolidés (état de la situation financière, résultat, flux) | français et anglais |
| US GAAP | 10-K (3 exercices), 10-Q (cumul semestriel / trimestriel) | anglais |
| Bancaire | établissements de crédit, de paiement, de monnaie électronique (ANC 2014-07 : PNB, cantonnement) | français |

### Trois exercices et plus

Un rapport annuel présente en général 2 exercices (comptes sociaux) ou 3 (10-K, certains rapports IFRS) : toutes les
colonnes datées sont lues. Pour allonger la série, déposez les comptes d'années antérieures : les documents d'une même
société (même SIREN, sinon même dénomination) sont **fusionnés automatiquement**. Quand une année figure dans plusieurs
documents, le plus récent l'emporte (comparatifs retraités). Un document mal rattaché se déplace dans l'onglet
*Documents et contrôles*, et une année manquante peut être ajoutée et saisie à la main.

### Présentations variées

La lecture ne dépend pas d'une mise en page fixe : les colonnes sont repérées par les années de l'en-tête
(« 2024 », « 31/12/2023 », « 31-déc.-25 », « N », « N-1 ») ou, à défaut, par l'alignement des chiffres ; les libellés
sont rapprochés par similarité (fautes d'OCR tolérées) avec un dictionnaire par format, puis avec ceux des autres
formats pour les présentations hybrides. Aucun outil ne lit pour autant 100 % des présentations : ce qui n'est pas
reconnu est listé (« lignes non reconnues ») et se rattache en un clic, et l'onglet *Contrôles* vérifie l'équilibre du
bilan et la cohérence du résultat.

## Démarrer en local

```bash
git clone https://github.com/<votre-compte>/finscan-lcbft.git
cd finscan-lcbft
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

L'OCR des PDF scannés utilise **Tesseract** (avec le français) :

- Windows : installer depuis https://github.com/UB-Mannheim/tesseract/wiki en cochant « French »,
  puis ajouter `C:\Program Files\Tesseract-OCR` au PATH ;
- macOS : `brew install tesseract tesseract-lang` ;
- Linux : `sudo apt install tesseract-ocr tesseract-ocr-fra`.

Sans Tesseract, l'application fonctionne pour les PDF dont le texte est sélectionnable.

## Mettre en ligne (GitHub + Streamlit Community Cloud)

GitHub héberge le code ; Streamlit Community Cloud l'exécute gratuitement à partir du dépôt.

1. Créer un dépôt **privé** sur GitHub et y pousser ce dossier :
   ```bash
   git init && git add . && git commit -m "FinScan LCB-FT"
   git branch -M main
   git remote add origin https://github.com/<votre-compte>/finscan-lcbft.git
   git push -u origin main
   ```
2. Sur https://share.streamlit.io : *Create app* → choisir le dépôt, la branche `main` et le fichier `app.py`.
   Le fichier `packages.txt` installe Tesseract et le pack français automatiquement.
3. Dans *Advanced settings → Secrets*, ajouter un mot de passe d'accès :
   ```toml
   APP_PASSWORD = "un-mot-de-passe-solide"
   ```
4. Dans les paramètres de l'application, restreindre la visibilité aux personnes invitées.

### Confidentialité

Les comptes, PV et liasses contiennent des données personnelles (associés, dates de naissance, adresses).

- Ne jamais versionner de documents clients : le `.gitignore` exclut les PDF.
- L'application ne stocke rien : les fichiers restent en mémoire le temps de la session. Le cache de lecture
  est propre au serveur et se vide à son redémarrage.
- Pour des dossiers réels, préférer une exécution en local ou sur une infrastructure maîtrisée, et un
  dépôt privé avec mot de passe pour toute version en ligne.

## Utilisation

1. Déposer un ou plusieurs PDF (un fichier = une société ; regrouper bilan, compte de résultat, liasse et PV
   dans le même PDF donne la lecture la plus complète).
2. *Analyser*. Un PDF scanné de 25 pages prend environ une à deux minutes.
3. Onglet **Documents et contrôles** : vérifier l'équilibre du bilan et la cohérence du résultat. L'outil corrige seul
   certaines erreurs d'OCR (résultat confirmé par le recalcul et le PV, net = brut − amortissements,
   ligne non reconnue égale à l'écart du bilan) ; les corrections de résultat et les rattachements sont listés.
4. Onglet **États financiers** : corriger un chiffre, ou rattacher une ligne non reconnue à un poste.
   Bouton *Page source* pour comparer à l'original.
5. Onglet **Identification** : corriger associés, parts et dividendes si besoin.
6. Onglet **Export** : note Word d'une page, classeur Excel complet, rapport HTML détaillé, et sauvegarde de la
   société en JSON (documents + corrections, rechargeable plus tard).

## Architecture

```
app.py                 interface Streamlit
engine/ingest.py       lecture PDF : texte natif, sinon OCR (positions des mots conservées)
engine/numbers.py      découpage libellé / nombres, recollage des milliers selon l'écart entre mots
engine/extract.py      détection du format, de l'unité, de la période et des colonnes N / N-1 ; rattachement aux postes
engine/fields.py       dictionnaire des postes par format (libellés reconnus)  ← ajouter un libellé ici
engine/company.py      fusion de plusieurs documents d'une même société en une série chronologique
engine/kyc.py          identité, SIREN (clé de Luhn), associés, dirigeants, filiales, dividendes, audit, pays
engine/analysis.py     consolidation, contrôles de cohérence, ratios, score de santé, Z-score
engine/aml.py          signaux LCB-FT, score indicatif, liste de filtrage
engine/report.py       rapport HTML
engine/export_docx.py  note de synthèse Word d'une page (python-docx + graphique matplotlib)
engine/export_xlsx.py  classeur Excel complet (openpyxl, formules et graphiques natifs)
data/risk_lists.json   listes GAFI / sanctions / offshore  ← à mettre à jour après chaque plénière du GAFI
data/countries.json    pays et variantes de noms (FR / EN)
tests/                 python -m pytest -q  (génère des comptes fictifs sur 3-4 exercices : PCG, IFRS FR/EN, 10-K)
```

### Méthode de lecture des chiffres

Chaque ligne garde la position de ses mots. Deux groupes de chiffres sont recollés (« 1 276 969 ») si
l'écart qui les sépare est petit par rapport à la hauteur du texte ; un grand écart marque une nouvelle colonne.
Les colonnes sont repérées par les années de l'en-tête (« 31/12/2021 », « March 28, 2026 », « 31-déc.-25 ») ou,
à défaut, par l'alignement des chiffres sur la page. Toutes les années présentes sont conservées. Pour un 10-Q, la
colonne retenue est le cumul depuis l'ouverture de l'exercice ; la période est étiquetée « 2026 (6 m) », comparée
seulement aux périodes de même durée, et les ratios rapportés à un stock sont annualisés.

### Score LCB-FT

Chaque signal a un poids (élevé 20, modéré 10, faible 4, atténuant −8), auquel s'ajoute un risque de base de 10.
Le total est ramené sur 100 par une courbe de saturation. Seuils : Faible < 30 ≤ Modéré < 55 ≤ Élevé.
Ce score oriente la vigilance ; il ne remplace ni la classification des risques de votre établissement ni le
jugement de l'analyste, et ne vaut pas soupçon.

## Limites connues

- L'OCR peut se tromper sur un chiffre : toujours lire l'onglet *Contrôles* avant d'exploiter un dossier.
- Les formulaires 2033 très chargés (cases, traits) se lisent mal ; la présentation de l'expert-comptable
  jointe à la liasse est généralement bien lue et prime.
- Les listes de pays sont datées (`_mise_a_jour` dans `data/risk_lists.json`). La liste UE des pays tiers à
  haut risque est à compléter selon votre référentiel.
- Le filtrage sanctions / PPE n'est pas réalisé par l'outil : il produit la liste des noms à passer dans
  votre outil de screening.

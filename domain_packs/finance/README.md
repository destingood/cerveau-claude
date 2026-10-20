# Pack Finance

Pack P1 de CERVEAU (section 9.2, plan de phase 2) : le portefeuille de Lucas en lecture, ses
mesures de risque, ses scénarios de stress, un rééquilibrage étudié et sa performance, plus les
actualités de ses lignes. Autonomie courante N0 (`config/autonomy.yaml`, `domains.finance`) : le
pack analyse, il n'agit pas ; aucun ordre n'existe en phase 2. Seul Lucas promeut le pack, à la
main, au vu du rapport (D16). Statut : **expérimental** jusqu'à ce que Lucas le passe en « actif »
au vu d'une mesure réelle du golden set (section 9.3).

Chaque chiffre vient d'un outil déterministe (R1) : le modèle recopie l'affichage de l'outil et le
nomme ; une mesure que l'outil dit impossible est rapportée, jamais estimée.

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`finance_data`, `finance_portfolio`, `finance_risk`, `finance_optimize`, `finance_report`, `finance_research`, `web_research`), renvoi à l'autonomie et aux seuils, sources autorisées |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `committee.yaml` | Comité d'investissement (§7.2, Annexe E, ADR-028) : trois analystes et leurs boîtes à outils de lecture et de calcul, défenseur, contradicteur et gestionnaire sans outil, contrôleur de risque avec `risk_report` ; analystes fondamental et sentiment inactifs (aucune source). Agent `plugins/finance_committee`, niveaux de modèle dans `config/committee.yaml` |
| `prompts/committee/` | Une fiche par membre actif : mission, sorties, règles et interdits de l'Annexe E ; toute modification change la version du Comité et relance les évals (R9) |
| `prompts/rubric.md` | Grille du juge des évals : 5 critères notés 0, 1 ou 2, chiffres comparés aux résultats des outils ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Corpus RAG autorisé : vide en phase 2 |
| `evals/golden.jsonl` | Golden set : 60 cas (minimum 50), seuil 0,85 (`config/evals.yaml`, D17) ; chiffres gelés sur la base de référence, à valider par Lucas avant le gel (R9) |
| `evals/behaviors.yaml` | 50 cas : 6 cas de base (chiffre recopié, chiffre inventé, signe inversé et date postérieure marqués, rééquilibrage N0, notion générale sourcée) et 44 cas en 7 thèmes d'au moins 5 cas : traçabilité (R1), point-in-time (R10), étiquettes (R12), parité, analyse N0 contre proposition, R16, qualité des données |

Le red team du pack est dans `evals/redteam/injection_finance/` (23 cas : ordres, exfiltration du
portefeuille, chiffres imposés, fuite des consignes, consignes dans un fichier CSV importé) ; les
suites communes à tous les packs dans
`evals/behaviors/` et `evals/redteam/injection_base/`.

## Données des cas hors ligne

Les outils finance lisent la base de référence de `tests/fixtures/finance/reference/` (portefeuille
fictif, titres `FICT-*`), à l'horloge des évals : le 18 octobre 2026 à 13 h UTC (ADR-023). Chaque
cas porte les chiffres que l'outil doit retrouver (`expect.figures` : outil, identifiant,
affichage) ; un écart d'un centime fait échouer le cas. Les pages web des actualités sont dans
`evals/fixtures/web.yaml`.

## Lancer les évals

```bash
make eval
```

Hors ligne et gratuit : chaque cas rejoue le vrai graphe avec un modèle scripté, les vrais
serveurs MCP finance et les pages des fixtures ; les contrôles déterministes (statut, outils,
chiffres, sources, notes, canaris, R5) s'appliquent. Le score du juge n'existe qu'en mesure réelle,
payante, lancée seulement avec l'accord de Lucas pour chaque campagne (D8) :

```bash
make eval-live CAMPAIGN=<nom> SUITES="golden"
```

En mesure réelle, la requête garde l'horloge réelle : une question Finance nomme ses dates.

## Versions

Le prompt système porte la version `system@<version Annexe D>+sha256:<empreinte>` (modèles et rôle
du pack) et la grille du juge `rubric_finance@<version>+sha256:<empreinte>` ; les deux sont écrites
dans le journal d'audit à chaque appel (R11). Toute modification d'un prompt relance les évals
(R9) ; un seuil ne baisse jamais et un cas du golden set ne se retouche pas sans l'accord de Lucas.

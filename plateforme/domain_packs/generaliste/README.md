# Pack Généraliste

Pack P0 de CERVEAU (section 9.2) : raisonnement, recherche web et vérification, et repli pour toute
question sans pack de domaine dédié. Autonomie maximale N1 (`config/autonomy.yaml`) : le pack lit,
il n'agit pas. Statut : **expérimental** jusqu'à ce que Lucas le passe en « actif » au vu d'une
mesure réelle du golden set (section 9.3).

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugin (`web_research`), renvoi à l'autonomie et aux seuils, sources autorisées |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : 5 critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Corpus RAG autorisé : vide en phase 1 |
| `evals/golden.jsonl` | Golden set : 37 cas (objectif 300), seuil 0,80 (`config/evals.yaml`) |
| `evals/behaviors.yaml` | 5 cas : un domaine sans pack (juridique, jardinage, astronomie, cuisine, business) est signalé, jamais simulé ; la finance, la recherche, le code et la cyber ont leur pack (ADR-021, ADR-046, ADR-050, ADR-057) |

Les pages web des cas hors ligne sont dans `evals/fixtures/web.yaml` ; les suites communes à tous
les packs dans `evals/behaviors/` (principes de l'Annexe D, format 7.3, auto-contrôle) et
`evals/redteam/injection_base/` (R5).

## Lancer les évals

```bash
make eval
```

Hors ligne et gratuit : chaque cas rejoue le vrai graphe avec un modèle scripté et les pages des
fixtures ; les contrôles déterministes (statut, sources, notes, canaris, R5) s'appliquent. Le
score du juge n'existe qu'en mesure réelle, payante, lancée seulement avec l'accord de Lucas pour
chaque campagne (D8) :

```bash
make eval-live CAMPAIGN=<nom> SUITES="golden"
```

## Versions

Le prompt système porte la version `system@<version Annexe D>+sha256:<empreinte>` (modèles et rôle
du pack) et la grille du juge `rubric@<version>+sha256:<empreinte>` ; les deux sont écrites dans le
journal d'audit à chaque appel (R11). Toute modification d'un prompt relance les évals (R9) ; un
seuil ne baisse jamais et un cas du golden set ne se retouche pas sans l'accord de Lucas.

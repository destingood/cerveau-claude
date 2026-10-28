# Pack Recherche

Pack P2 de CERVEAU (section 9.2, plan de phase 6) : synthèse d'un sujet à partir de pages web
publiques, de métadonnées et de résumés de publications (arXiv, Crossref) et de flux de veille
datés. Autonomie courante N0 (`config/autonomy.yaml`, `domains.recherche`, D3) : le pack lit et
synthétise, il n'agit pas. Statut : **expérimental** jusqu'à ce que Lucas le passe en « actif » au
vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque affirmation renvoie à un extrait retrouvé mot pour mot dans une source lue (R1, R12) ; un
chiffre ou une date absents de l'extrait cité font retirer l'affirmation, listée dans les points
non vérifiés (D15). Un préprint est signalé, une publication rétractée n'est jamais lue, une
correction publiée est signalée ; ni PDF ni texte intégral ne sont lus (D12).

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`web_research`, `scholarly`, `feeds`), agent `deep_research` (`cerveau ask --approfondi` seulement, D14), renvoi à l'autonomie et aux seuils, sources autorisées |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : 5 critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Liste blanche des flux RSS et Atom et corpus RAG : vides en phase 6 ; seul Lucas les remplit (D16, D18) |
| `evals/golden.jsonl` | Golden set : 34 cas (minimum 30), seuil 0,80 (`config/evals.yaml`, D4) : synthèse, contradiction entre sources, veille datée, préprint, rétractation, correction, « je ne sais pas », injection, texte payant, chiffre inventé, R16, recherche approfondie |
| `evals/behaviors.yaml` | 8 cas : renvoi par affirmation, préprint signalé, rétractation jamais lue, chiffre hors extrait retiré (R1), « je ne sais pas » (R12), PDF refusé (D12), synthèse pour des tiers refusée (R16), revue systématique routée vers le pack (ADR-046) |

Le red team du pack est dans `evals/redteam/injection_recherche/` (18 cas : consignes dans une
page, un résumé ou un titre de notice ; flux de veille piégés ; exfiltration par une lecture, un
lien, une requête ou des données personnelles ; rédacteur et planificateur manipulés de la recherche
approfondie) ; les suites communes à tous les packs dans `evals/behaviors/` et
`evals/redteam/injection_base/`.

## Données des cas hors ligne

Les cas portent leurs propres pages web (`pages`, `hits`), leurs notices de publication
(`records` : source, préprint, rétractation ou correction, résumé, extraits) et leurs flux
(`feeds` : XML servi par un lecteur de flux factice), tous sur des domaines `.example`. Aucun appel
réseau : `web_research`, `scholarly` et `feeds` sont remplacés par des serveurs de test qui ne
servent que les données du cas (`core/evals/offline.py`). Un cas `approfondi: true` passe par
l'agent `deep_research` ; son plan, ses rapports et ses affirmations peuvent être scriptés
(`offline.research`) pour simuler un modèle manipulé.

## Lancer les évals

```bash
make eval
```

Hors ligne et gratuit : chaque cas rejoue le vrai graphe avec un modèle scripté ; les contrôles
déterministes (statut, sources, renvois, affirmations retirées, notes, canaris, R5) s'appliquent.
Le score du juge n'existe qu'en mesure réelle, payante, lancée seulement avec l'accord de Lucas
pour chaque campagne (D5) :

```bash
make eval-live CAMPAIGN=<nom> SUITES="golden"
```

## Versions

Le prompt système porte la version `system@<version Annexe D>+sha256:<empreinte>` (modèles et rôle
du pack) et la grille du juge `rubric_recherche@<version>+sha256:<empreinte>` ; les deux sont
écrites dans le journal d'audit à chaque appel (R11). Toute modification d'un prompt relance les
évals (R9) ; un seuil ne baisse jamais et un cas du golden set ne se retouche pas sans l'accord de
Lucas.

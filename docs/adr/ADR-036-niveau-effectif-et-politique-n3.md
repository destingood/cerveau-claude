# ADR-036 — Niveau effectif plafonné par la signature, politique `approbation` en N3

- Statut : accepté (D5, D6, D7 et D10 du plan de phase 5, validées par l'utilisateur le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le moteur de politique lit le niveau dans `autonomy.yaml` sans vérifier la signature que
`governance/approvals/` doit contenir (§8.3). `autonomy.yaml` n'est protégé par aucun hook :
modifier ce fichier suffirait donc à promouvoir. Le moteur n'accorde que `auto`, `proposition` et
`paper` ; la cellule FINANCIERE de N3 (`approbation`) est refusée.

## Options
1. Niveau lu dans `autonomy.yaml` seul.
2. **Niveau effectif = min(niveau écrit, plus haut niveau signé)**, pour les domaines soumis à
   promotion.

## Décision
Option 2, et la décision `approbation` en N3.

- **Signature (D7)** : `governance/approvals/AAAA-MM-JJ-<domaine>-N<k>.md`, avec un en-tête YAML
  `domain`, `level`, `date`, `promotion_report_sha256`, `signed_by: owner`. Le code le lit et ne
  l'écrit jamais. Une signature compte si son nom, son en-tête et sa date concordent et, à partir
  de N3, si le rapport de promotion cité existe sous `var/promotion/` avec cette empreinte. Une
  signature invalide est ignorée et signalée. Depuis la phase 6 (B240), une signature datée après
  aujourd'hui (à Paris ; la boucle paper prend le jour de sa séance) ou avant le jour, à Paris, où
  le rapport cité a été généré (`genere_le`) ne compte pas ; une signature est lue jusqu'à 64 Kio
  et un rapport jusqu'à 1 Mio, au-delà ils sont ignorés et signalés (B233).
- **Niveau effectif (D6)** : `core/governance/signatures.py`, appliqué par les appelants du moteur
  (adaptateur MCP, boucle paper, API), pas par le chargeur de configuration. Seuls les domaines
  présents sous `promotion` y sont soumis (aujourd'hui `finance`) ; N0 n'exige aucune signature.
  Le généraliste reste en N1, borné par son `max_level`.
- **Politique (D5)** : `approbation` est accordé pour FINANCIERE dans le domaine `finance`
  seulement. COMMUNICATION_EXTERNE et IRREVERSIBLE restent refusés : aucun composant ne les porte.
  Un test parcourt toute la matrice pour vérifier qu'aucun chemin n'est plus permissif qu'écrit.
- **Effet `approbation`** : l'intention passe la Porte, est inscrite au carnet en INTENTION et
  attend. Elle n'est validée et envoyée qu'après un accord valide (ADR-035) ; un refus ou une
  expiration la fait passer à REJETEE.
- **Répétition sur le paper (D10)** : tant que le live est désactivé, une intention approuvée part
  au simulateur paper, étiquetée « paper ».
- **Défense en profondeur** : `live.yaml` à `enabled: true` sans les autres conditions d'ADR-039
  donne toujours un refus avec alerte.

## Conséquences
- Modifier `autonomy.yaml` seul ne promeut rien ; une rétrogradation dans `autonomy.yaml` reste
  immédiate (le minimum ne peut que baisser).
- Les tests qui posent N2 dans une configuration temporaire fournissent la signature
  correspondante dans leur dossier temporaire.
- Revue `risk-gate-auditor` obligatoire (`core/policy/**`, `config/autonomy.yaml`).

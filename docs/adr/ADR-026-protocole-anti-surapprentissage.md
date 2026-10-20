# ADR-026 — Protocole anti-surapprentissage : point-in-time, journal des essais, DSR, PBO et portes

- Statut : accepté (D7 à D11 du plan de phase 3, validées par Lucas le 19/10/2026 ; les précisions
  ci-dessous sont soumises à sa relecture au compte rendu de phase 3)
- Date : 2026-10-19
- Phase : 3

## Contexte
Le §10.6 exige un protocole avant toute promotion d'une stratégie : découpage, walk-forward, frais,
nombre d'essais, Deflated Sharpe ratio, PBO, crises et référence. R10 interdit toute donnée
postérieure à la décision, et le §17 demande un test d'injection qui le prouve.

Sources lues le 19/10/2026 (articles téléchargés, texte relu) :

- **DSR** : Bailey et López de Prado, « The Deflated Sharpe Ratio », SSRN 2460551, version du
  31/07/2014 (Journal of Portfolio Management). Avec γ ≈ 0,5772156649 (Euler-Mascheroni), Z la loi
  normale et V la variance des Sharpe des essais :
  - SR₀ = √V · ((1−γ)·Z⁻¹[1 − 1/N] + γ·Z⁻¹[1 − 1/(N·e)]) ;
  - DSR = Z[(SR − SR₀)·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²)], γ₄ étant l'aplatissement non excédentaire.

  Le code redonne les exemples de l'article : DSR 0,9004 (N = 100), 0,9505 (N = 46), et un seuil
  de 0,95 franchi à N = 88 pour des rendements normaux.
- **PBO** : Bailey, Borwein, López de Prado et Zhu, « The Probability of Backtest Overfitting »,
  version révisée de février 2015 (revue de publication `A_VERIFIER`), algorithme CSCV du §2.2.
  - L'article écrit 12 780 combinaisons pour S = 16 ; C(16, 8) vaut 12 870.
  - Il cite 0,05 comme seuil de rejet « habituel », bien plus strict que la porte D9 (< 0,5).
    Lucas décide s'il veut la durcir. R9 interdit seulement de la baisser.

## Options
1. Walk-forward et échantillon final seulement : pas de correction du nombre d'essais.
2. DSR seul : il ne mesure pas la dégradation entre l'apprentissage et le test.
3. **Protocole complet** : point-in-time actif, journal des essais, DSR, PBO, walk-forward,
   échantillon final, crises et référence, avec des portes fixées avant toute mesure.

## Décision
Option 3, déterministe et sans modèle de langage (`cerveau strategy protocol <id>`), dans
`core/finance/research/`.

- **Point-in-time (R10)** :
  - `PointInTimeView` ne sert que les lignes publiées avant la coupure de t, dans leur révision
    connue à t, ajustées des seules opérations sur titres connues à t. Toute lecture au-delà lève
    `LookAheadError`, et le protocole échoue.
  - Invariance par troncature : pour un échantillon de dates, le signal recalculé sur des données
    coupées à t doit être identique, `decide` comme `weights_frame`. Ce contrôle tourne dans chaque
    protocole.
  - Cinq tests d'injection : lecture de t+1, `shift(-1)` vectorisé, cours publié plus tard, split
    futur et une propriété Hypothesis.
- **Découpage (D7)** : 70 % pour le développement, un embargo de 5 séances, puis 30 % pour
  l'échantillon final. L'échantillon final n'est lu qu'une fois par version (code et grille), et
  chaque lecture entre au journal. Un backtest du Copilot ou un criblage dont la fenêtre atteint
  l'échantillon final compte aussi comme une lecture, et au Comité `strategy_lab` ne sert qu'en
  mode signaux (revue quantitative de phase 3, M2).
- **Walk-forward (D8)** :
  - chaque combinaison de la grille tourne une fois, en continu, sur tout l'échantillon de
    développement ;
  - ces séries sont découpées en 5 blocs égaux : le pli k apprend sur les blocs 1 à k et teste sur
    le bloc k+1 ;
  - le paramètre retenu est le meilleur Sharpe net en apprentissage, à égalité le premier de la
    grille ;
  - le coût de transition entre deux plis n'est pas compté `[Hypothèse]`, écrit dans le rapport.
- **Échantillon final** : la configuration retenue (meilleur Sharpe net sur tout le développement)
  part en cash après l'embargo. Elle tourne avec les frais normaux et avec des frais doublés
  (commission, minimum et glissement), dans la même lecture. Un passage sur toute la période donne
  les mesures de crise.
- **Journal des essais (D10)** : table `research_trials` de la base Finance.
  - Des déclencheurs SQLite refusent UPDATE et DELETE.
  - Chaque ligne enregistre :
    - la stratégie, l'empreinte du code, les paramètres et leur empreinte ;
    - la fenêtre et le nombre de séances ;
    - l'origine : `criblage`, `protocole`, `protocole-final` ou `copilote` ;
    - le Sharpe quotidien et le Sharpe annualisé ;
    - l'empreinte SHA-256 de la série et le jeu de frais.
  - La variante à frais doublés n'est pas un essai : elle ne peut que faire échouer, jamais
    sélectionner.
- **DSR** :
  - N est le nombre brut de lignes de la famille (même stratégie, toutes versions et origines) ;
    V est la plus grande de trois variances (ddof = 1) de Sharpe quotidiens : celle de la
    famille, celle de ses séries distinctes (fenêtre et empreinte de la série) et celle de la grille
    en cours. Des copies d'un essai moyen baissaient V et relevaient le DSR ; répéter un essai ne
    peut plus que relever SR₀ (revue quantitative de phase 3, M1) ;
  - SR, γ₃ et γ₄ sont calculés sur les rendements nets de développement de la configuration
    retenue ;
  - si N = 1 ou V = 0, SR₀ = 0 ;
  - le N effectif par regroupement va au backlog.
- **PBO (CSCV)** :
  - matrice T × N des rendements nets de développement de la grille, S = 16 blocs (configuration) ;
  - les T mod S premières lignes sont écartées ;
  - pour chaque combinaison : n* est le meilleur Sharpe en apprentissage (à égalité, le premier) ;
    on prend son rang en test (rangs croissants, ex æquo au rang moyen), ω̄ = rang/(N+1) et
    λ = ln(ω̄/(1−ω̄)) ;
  - PBO = part des λ ≤ 0 ;
  - un écart-type nul donne un Sharpe nul, et moins de 2 configurations rend le PBO non évaluable.
- **Référence** : l'achat-conservation de l'indice de `market_risk.benchmark` sur données réelles,
  ou de l'univers à poids égaux sur données synthétiques, nommée comme telle.
- **Portes (D9)**, dans `config/research.yaml`, fixées avant la première mesure :
  1. DSR ≥ 0,95 ;
  2. PBO < 0,5 ;
  3. Sharpe du walk-forward > 0, et Sharpe final ≥ 0,5 × celui du walk-forward ;
  4. Sharpe final > celui de la référence sur la même fenêtre ; non évaluable sous 252 séances ;
  5. Sharpe final > 0 à frais doublés ;
  6. sur chaque crise de `market_risk.historical_stress`, perte maximale ≤ celle de la
     référence. Une crise non couverte, ou datée `A_VERIFIER`, rend la porte non évaluable.

  Une porte R10 s'y ajoute : `LookAheadError` ou invariance rompue, l'échec est immédiat.
- **Verdict** : `echoue` si une porte échoue ; sinon `incomplet` si une porte n'est pas évaluable ;
  sinon `reussi`. Seul `reussi` rend une stratégie promouvable (ADR-027).

## Conséquences
- **Validation par les tests** :
  - des marches aléatoires sans effet font rejeter la meilleure combinaison d'une grille large ;
  - un effet de tendance planté fait passer la stratégie qui l'exploite ;
  - les exemples chiffrés des deux articles sont reproduits.
- **Limites écrites** :
  - le PBO tend vers 0,5 quand toutes les configurations se valent, sans qu'il y ait surapprentissage ;
  - le N brut rend le DSR prudent ;
  - un Sharpe de Copilot calculé sur une autre fenêtre entre dans V.
- **Données réelles** : tant que les frais sont `A_DEFINIR`, le protocole y est refusé (ADR-024).
  Ensuite, tant que l'indice ou les dates de crise restent `A_VERIFIER`, le verdict est au mieux
  `incomplet`, ce qui est voulu (R7).
- **Durée** : le protocole échappe au budget de 120 s d'une requête. Le Copilot ne fait que lire le
  dernier verdict.

# Jeu de recherche synthétique

Données de test du protocole de backtest (plan de phase 3, §7, D4). **Tout est inventé** : les
quatre instruments, leurs cours, leurs opérations, les crises et les frais. Aucun identifiant
ne désigne un vrai titre (pas d'ISIN), chaque nom porte « (fictif) » et aucune valeur ne vient
d'un fournisseur.

**L'effet planté est volontairement fort et irréaliste** : le meilleur croisement de moyennes
mobiles y atteint un Sharpe annualisé de 3 à 4, ce qu'aucun marché réel n'offre durablement. Le
jeu sert à vérifier que le protocole trouve un effet qui existe et rejette ceux qui n'existent
pas. Il ne dit rien d'un vrai marché ; aucune conclusion d'investissement ne peut en sortir.

## Fichiers

| Fichier | Contenu | Format |
|---|---|---|
| `instruments.csv` | 4 actions `FICT-R…` en EUR sur Euronext Paris (XPAR) | référentiel CSV (ADR-013) |
| `cours.csv` | clôtures du 04/01/2016 au 31/12/2025, avec leur heure de publication | `date,identifiant,cloture,devise,publie_le` |
| `operations.csv` | 11 opérations : 1 split, 10 dividendes | `date_ex,identifiant,type,valeur,devise,date_annonce` |
| `crises_fictives.yaml` | 3 fenêtres de crise fictives | forme de `config/risk.yaml` › `market_risk.historical_stress` |
| `frais_fictifs.yaml` | frais de démonstration, avec le nom à afficher | forme de `config/risk.yaml` › `trading_costs` |
| `generate.py` | le générateur, à graine fixe | Python : bibliothèque standard et `core.finance.calendars` |

Les cours suivent les séances d'Euronext Paris selon exchange-calendars : 2 560 séances par
instrument, plus les 40 corrections décrites plus bas.

## Régénérer

```bash
uv run python tests/fixtures/finance/research/generate.py
```

La graine est fixe (`cerveau-recherche-2026-3`), chaque série a son propre flux aléatoire, les
tirages gaussiens sont calculés à la main (Box–Muller) et chaque tirage est fait tous les jours
ouvrés, fériés compris : le résultat ne dépend ni de la version de Python ni d'un jour férié.
`tests/test_finance_research_data.py` vérifie que les fichiers commités sont exactement ceux du
générateur. Une nouvelle version d'exchange-calendars qui change un jour férié peut casser ce
test : il faut alors régénérer et relire le diff. Les fichiers sont en fin de ligne LF.

## Paramètres et choix de la graine

Les paramètres ont été réglés pour que l'effet soit trouvé de façon robuste, pas sur une graine
chanceuse. Contrôle fait lors du réglage, hors dépôt et hors protocole : grille de 224
croisements de moyennes mobiles (courte de 5 à 50 par pas de 5, longue de 20 à 250 par pas de
10), position prise deux séances après le signal, 15 points de base par changement de
position, deflated Sharpe ratio sur les 70 premiers pour cent des séances, avec les 224 essais.

| Contrôle sur 20 graines | Résultat |
|---|---|
| FICT-RTEND, DSR ≥ 0,95 | 18 graines sur 20 (les deux autres : 0,50 et 0,94) |
| Marches aléatoires, DSR ≥ 0,95 | 1 série sur 60, à 0,95 tout juste ; les 59 autres sous 0,95 |

La graine retenue est, parmi ces 20, celle dont les marches aléatoires sont le plus loin du
seuil : DSR de 0,998 pour la tendance, de 0,07, 0,06 et 0,23 pour les marches aléatoires. Ce
choix est assumé : il évite qu'un test du protocole repose sur un tirage limite. Le vrai
protocole (étape 6, six portes de `config/research.yaml`) est plus exigeant que ce contrôle.

## Anomalies placées

| Anomalie | Où | Ce qu'elle teste |
|---|---|---|
| Tendance plantée | FICT-RTEND : dérive logarithmique de +120 % ou −120 % par an, qui bascule avec une probabilité de 1 % par jour ouvré (régimes d'une centaine de séances), volatilité de 15 % | le protocole doit trouver l'effet |
| Borne de la tendance | FICT-RTEND : le régime repart vers le premier cours (50 €) dès que le cours sort de [50/3, 50 × 3] | sans elle, une suite de régimes baissiers mène le cours à quelques centimes |
| Marches aléatoires | FICT-RALEA1, 2 et 3 : dérive de 3 % par an, volatilité de 18 %, aucun avantage | le protocole doit les rejeter |
| Crises fictives | les 4 instruments, 15/05–07/07/2017, 04/02–29/03/2019, 05/02–28/03/2024 : chute de 25 % sur les 5 premières séances, volatilité doublée sur toute la fenêtre | la porte des crises ; la crise de 2024 tombe dans l'échantillon final |
| Clôtures publiées en retard | 5 % des clôtures, connues le jour ouvré suivant à 08:00 à Paris | une décision prise le soir de la séance ne les voit pas |
| Cours corrigés | une clôture par instrument et par an (40 au total), d'abord publiée à ±4 %, corrigée le jour ouvré suivant à 09:00 à Paris | la révision : la décision à t voit le cours faux, celle d'après le cours juste |
| Split 2 pour 1 | FICT-RALEA2, jour ex 14/06/2021, annoncé le 17/05/2021 | l'ajustement ; aucun cours vu avant la date ex ne change |
| Dividendes annuels | FICT-RALEA1, 2,5 % du dernier cours connu le jour de l'annonce, annoncés 4 semaines avant le jour ex (première séance à partir du 20 mai) | le crédit en cash à la date ex |

La chute de crise est brutale exprès : une baisse lente offrirait un avantage à n'importe quel
suiveur de tendance, marches aléatoires comprises, et le protocole n'aurait plus rien à rejeter.

## Frais fictifs

Commission de 0,10 % (minimum 2 € par ordre), glissement de 5 points de base, change de 10
points de base. Ils portent le nom « frais fictifs de démonstration », que toute sortie qui les
utilise doit afficher. Aucun courtier ne les pratique, et ils ne remplacent pas
`config/risk.yaml` › `trading_costs`, qui reste `A_DEFINIR` (D13 de la phase 2) : un backtest
sur des données réelles reste refusé tant que Lucas n'a pas donné les frais de son courtier.

## Dates de connaissance

Les fichiers sont lus comme s'ils avaient été récupérés le dimanche 04/01/2026 à 12:00 UTC.

- Une clôture à l'heure est connue à la clôture de sa séance plus une heure de marge
  (ADR-017).
- Une clôture en retard ou une correction porte sa propre heure dans `publie_le`.
- Une opération est connue à la fin de son jour d'annonce à Paris, plus la marge.

## Chargement

- `core.finance.fixtures.load_research(store)` charge les fichiers dans une base finance neuve :
  le référentiel, les opérations par `CsvCorporateActions`, puis les cours par
  `PublishedCloses`, qui garde l'heure de publication de chaque ligne.
- Les lignes sont ingérées dans l'ordre de publication : une correction devient la révision 2
  du cours faux.
- Il n'y a pas de score de qualité : un backtest lit chaque série telle qu'elle était publiée.
- Il ne faut charger le jeu qu'une fois par base. Une seconde lecture enregistrerait chaque
  cours faux comme une nouvelle révision.
- `research_crises()` lit les crises fictives, et `research_costs()` lit les frais fictifs avec
  leur nom.
- Chaque enregistrement porte la source `fixtures` (R12).

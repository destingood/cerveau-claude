# Réglages à trancher

Étape B3 du plan (« Réglages »), partie 3. Date : 27/11/2026. Statut : **à toi de trancher**.
Rien de cette fiche n'est écrit dans `config/`.

## Où on en est

- Avant l'étape B3 : 42 fonctions bloquées.
- Partie 2 (valeurs techniques, proposées et appliquées, à valider dans la PR) : 28 fonctions
  bloquées. Débloquées : l'API locale, le kill switch sur perte de données, la santé des plugins,
  la rotation des clés, le contrôle qualité des données, les 7 portes des golden sets, les motifs
  de la boucle d'apprentissage, la pseudonymisation.
- Restent les réglages de cette fiche. Ils touchent à l'argent, au risque, à l'autonomie ou à des
  accès. C'est toi qui décides.
- Pour un réglage, tu écris la valeur dans le fichier, ou tu me la donnes et je l'écris. Seule
  exception : `config/live.yaml`, que tu modifies toujours toi-même, à la main (R3).
- Après chaque changement : `uv run cerveau config check`.

## Les réponses qui débloquent le plus

| # | Ta réponse | Fonctions débloquées |
|---|---|---|
| 1 | Ton courtier et ses frais (`risk.yaml › trading_costs`) | 2 tout de suite : frais d'une proposition, backtest sur données réelles. Le paper trading en a besoin aussi (avec les réponses 4 et 5). |
| 2 | Ton identifiant Discord (`interfaces.yaml › discord.owner_user_id`) | 2 : le bot Discord et les approbations N3 (le port de l'API est déjà fixé). |
| 3 | Tes dépôts et l'image des contrôles (`code.yaml › repositories`, `checks.image`) | 2 : lecture des dépôts, contrôles ruff et pytest. |
| 4 | La liste des instruments du paper trading (`risk_limits.paper.yaml › universe`) | Avec 1 et 5 : le paper trading. |
| 5 | Tes exclusions personnelles (`compliance.yaml › exclusions_personnelles`) | Avec 1 et 4 : le paper trading. |

Le budget en euros apparaît dans 5 fonctions bloquées. Mais ton budget d'API est de 0 € (17/11).
Ma recommandation est donc de le laisser bloqué : voir plus bas.

## Argent : budgets des modèles payants

### `budgets.yaml › llm_budget_eur.daily` et `.monthly`

- **Ce qu'il règle** : le plafond de dépense d'API par jour et par mois. À 100 %, les nouvelles
  requêtes sont refusées (D9).
- **Ce que le débloquer permettrait** : la fonction « budgets ». Puis, avec les plafonds par
  tâche ci-dessous : le Comité d'investissement, la recherche approfondie, l'agent de code. Il
  sert aussi à la mise en ligne automatique de la couche apprise.
- **Options** : le laisser à `A_DEFINIR` ; ou un montant (le code refuse 0).
- **Ma recommandation : le laisser à `A_DEFINIR`.** Ton budget d'API est de 0 €. Un marqueur
  bloque tout appel payant ; c'est exactement ce que tu as décidé. Si un jour tu paies : 5 € par
  jour et 50 € par mois (proposition du 17/11 : environ 1 000 requêtes et une campagne d'évals).
- **Ta décision du 26/11 reste vraie** : le pont MCP n'a pas de budget en euros. Il ne dépense
  aucun euro d'API. Ses plafonds d'appels (200 par session, 1 000 par jour) suffisent.

### `budgets.yaml › per_committee.*` (jetons, secondes, appels d'outils)

- **Ce qu'il règle** : la taille maximale d'une séance du Comité d'investissement.
- **Ce que le débloquer permettrait** : des séances réelles du Comité, avec le budget en euros.
- **Options** : `A_DEFINIR` ; ou trois plafonds.
- **Ma recommandation : `A_DEFINIR` tant que le budget est à 0 €.** Sinon : 400 000 jetons,
  600 s, 40 appels (ta proposition du plan de phase 3).

### `budgets.yaml › per_deep_research.*`

- **Ce qu'il règle** : la taille maximale d'une recherche approfondie (déjà bornée à 5
  sous-questions et 12 lectures).
- **Ce que le débloquer permettrait** : des recherches approfondies réelles, avec le budget.
- **Ma recommandation : `A_DEFINIR` tant que le budget est à 0 €.** Sinon : 300 000 jetons,
  600 s, 30 appels.

### `budgets.yaml › per_code_agent.*` et `code.yaml › agent.max_requests`

- **Ce qu'il règle** : la taille d'une tâche de l'agent de code, et le nombre de requêtes à l'API
  qu'il peut faire par tâche (le proxy le tient, en plus de `max_usd: 2`).
- **Ce que le débloquer permettrait** : l'agent de code en conteneur (il rend un patch, que tu
  appliques toi-même). Il faut aussi les dépôts et les images (plus bas).
- **Ma recommandation : `A_DEFINIR` tant que le budget est à 0 €.** Sinon : 500 000 jetons, 960 s
  (une tâche de 900 s au plus, plus la réponse), 10 appels ; et `max_requests: 30`, une requête par
  tour au plus (`max_turns: 30`). C'est plus strict que les 60 proposés le 17/11 : `max_usd` reste
  le vrai plafond, et 30 coupe plus tôt une tâche qui tourne en rond.

## Risque : finance

### `risk.yaml › trading_costs.*` (commission, minimum, glissement, change)

- **Ce qu'il règle** : les frais et le glissement comptés dans chaque backtest et chaque
  proposition (R10). Ils dépendent du courtier que tu choisis (D12, encore ouverte).
- **Ce que le débloquer permettrait** : la liste d'opérations d'une proposition, le backtest sur
  données réelles, et une part du paper trading.
- **Options** : les frais de ton courtier, lus sur sa grille.
- **Ma recommandation** : si tu choisis Interactive Brokers (formule « Fixed », Euronext et
  Xetra, grille lue le 17/11) : `commission_pct: 0.05`, `min_commission_eur: 3.75`,
  `slippage_bps: 5`, `fx_conversion_bps: 3`. Ces valeurs comptent déjà une marge : le minimum
  inclut les frais de bourse refacturés, le glissement est environ trois fois celui mesuré sur les
  ETF les plus liquides. En cas de doute, arrondis vers le haut : des frais trop hauts rendent un
  backtest plus prudent.

### `risk_limits.paper.yaml › universe`

- **Ce qu'il règle** : la liste blanche des instruments que la Porte de risque accepte en paper.
- **Ce que le débloquer permettrait** : le paper trading (avec les frais et les exclusions).
- **Options** : une liste d'identifiants de la base Finance.
- **Ma recommandation** : la plus courte possible. L'indice de référence (son ISIN est en cours de
  vérification) et les lignes de ton portefeuille. On l'élargit plus tard.

### `compliance.yaml › exclusions_personnelles`

- **Ce qu'il règle** : les secteurs ou émetteurs que tu refuses. `[]` veut dire « aucune
  exclusion ».
- **Ce que le débloquer permettrait** : le paper trading (avec l'univers et les frais).
- **Ma recommandation** : aucune valeur prudente n'existe ici, c'est un choix personnel. Écris ta
  liste, ou `[]` si tu n'exclus rien.

### `risk.yaml › optimization.risk_aversion`

- **Ce qu'il règle** : l'aversion au risque de l'optimisation moyenne-variance. Plus elle est
  haute, moins le portefeuille proposé est risqué.
- **Ce que le débloquer permettrait** : la méthode moyenne-variance (les autres méthodes marchent
  déjà).
- **Options** : un nombre positif. La plage habituelle va de 2 à 5.
- **Ma recommandation : 5**, le haut de la plage, donc le plus prudent. Aucune source ne donne
  « la bonne » valeur : c'est ton attitude face au risque (ADR-019). La moyenne historique n'est
  pas une prévision.

## Autonomie

### `autonomy.yaml › promotion.finance.N3_to_N4.*`

- **Ce qu'il règle** : le nombre minimal d'approbations N3, et le taux d'accord entre toi et
  CERVEAU, avant le passage en N4 (exécution réelle sans approbation, dans les limites du live).
- **Ce que le débloquer permettrait** : de calculer un rapport de promotion N4. La signature
  manuelle reste exigée.
- **Ma recommandation : le laisser à `A_DEFINIR`.** N4 est hors du plan. Si un jour tu le veux :
  50 approbations au moins et 95 % d'accord au moins.

### `evals.yaml › learning.promotion_margin`

- **Ce qu'il règle** : le gain minimal qu'un challenger doit montrer pour être mis en ligne
  automatiquement (ADR-065, D4).
- **Ce que le débloquer permettrait** : la mise en ligne automatique d'une leçon apprise, avec le
  budget en euros (les évals réelles sont payantes).
- **Ma recommandation** : `0.02` quand tu voudras l'activer ; d'ici là `A_DEFINIR`. La partie 2 a
  déjà fixé la taille minimale du jeu tenu à l'écart (50 cas) : aucune mise en ligne avant un
  golden de 250 cas environ.

### `evals.yaml › learning.rollback_window_days`

- **Ce qu'il règle** : combien de jours une mise en ligne reste surveillée. Une baisse en
  production pendant ce temps la défait.
- **Pourquoi ici et pas en partie 2** : tant qu'il vaut `A_DEFINIR`, chaque mise en ligne est
  surveillée **pour toujours**. Fixer un nombre réduirait la surveillance.
- **Ma recommandation : le laisser à `A_DEFINIR`.** C'est déjà le plus prudent.

### `evals.yaml › calibration.*` (`min_resolved`, `window_days`, `brier_drift_max`)

- **Ce qu'il règle** : quand une dérive de calibration de tes prévisions fait redescendre un
  domaine d'un niveau (section 8.3).
- **Pourquoi ici et pas en partie 2** : la rétrogradation n'est pas encore branchée (B351). Et le
  côté prudent n'est pas clair : une fenêtre courte réagit plus vite, mais si elle contient trop
  peu de prévisions, aucun verdict ne tombe jamais.
- **Ma recommandation** : à fixer quand B351 sera écrit, par exemple 20 prévisions résolues au
  moins, une fenêtre de 90 jours, une hausse du score de Brier de 0,05 au plus (environ une erreur
  type sur 20 prévisions : on rétrograde vite, c'est le côté sûr).

## Accès et comptes

### `interfaces.yaml › discord.owner_user_id`

- **Ce qu'il règle** : le seul compte Discord auquel le bot répond.
- **Ce que le débloquer permettrait** : le bot (`/kill`, `/status`, rapport quotidien) et les
  approbations N3. Le canal des approbations (D8) reste à confirmer.
- **Ma recommandation** : ton identifiant numérique Discord, **entre guillemets** (17 à 20
  chiffres). Tu crées le bot toi-même ; Claude Code ne se connecte jamais à Discord.

### `interfaces.yaml › ntfy.server`

- **Ce qu'il règle** : le serveur qui reçoit les alertes (kill switch, budgets).
- **Pourquoi ici et pas en partie 2** : un serveur tiers reçoit tes alertes. C'est un compte et
  un accès, donc ta décision.
- **Ma recommandation** : `https://ntfy.sh` jusqu'au VPS (D14), avec un sujet d'au moins 32
  caractères aléatoires dans la variable `NTFY_TOPIC` (le sujet vaut un mot de passe) et aucun
  contenu sensible. Plus tard : ton propre serveur sur le VPS.

### `models.yaml › tiers.local.model`

- **Ce qu'il règle** : le modèle Ollama local (D9, encore ouverte).
- **Ce que le débloquer permettrait** : le niveau « local ».
- **Ma recommandation** : `A_DEFINIR` tant qu'aucun modèle n'est installé. Ensuite : le nom exact
  affiché par `ollama list`, après avoir vérifié sa licence (R14).

### `risk.yaml › infra.private_network`

- **Ce qu'il règle** : le réseau privé du VPS (section 13).
- **Ce que le débloquer permettrait** : le déploiement sur un VPS.
- **Ma recommandation** : `A_DEFINIR` tant qu'il n'y a pas de VPS ; WireGuard au moment du
  déploiement (B9).

### `code.yaml › repositories`, `checks.image`, `agent.image`, `agent.proxy_image`

- **Ce qu'il règle** : les dépôts que les outils de code peuvent lire, et les images Docker que
  tu construis (épinglées par leur empreinte `sha256`, jamais téléchargées par CERVEAU).
- **Ce que le débloquer permettrait** : `repositories` seul, la lecture des dépôts ;
  avec `checks.image`, les contrôles ruff et pytest ; avec les deux images de l'agent et les
  budgets, l'agent de code.
- **Ma recommandation** : commence par un seul dépôt, avec `pytest: false`, puis l'image des
  contrôles (`infra/agent/README.md`). Les images de l'agent attendent le budget.

## Hors de cette fiche

- **`live.yaml › broker`** : seulement pour mémoire. Tu l'écris toi-même, à la main (R3), quand
  tu auras choisi ton courtier.
- **Faits à vérifier (`A_VERIFIER`)** : stress historiques, indice de référence, fiscalité,
  plateformes crypto, conditions d'OpenBB et de FRED, empreinte d'ATT&CK, adresse de Légifrance.
  Une autre tâche les vérifie en parallèle.

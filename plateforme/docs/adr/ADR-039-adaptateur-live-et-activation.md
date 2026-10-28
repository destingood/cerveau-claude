# ADR-039 — Adaptateur live présent mais désactivé : six conditions revérifiées à chaque appel

- Statut : accepté (D8, D9 et D19 du plan de phase 5, validées par Lucas le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le §17 exige un adaptateur live présent mais désactivé, et une activation impossible sans action
manuelle de Lucas. `config/live.yaml` vaut `enabled: false`, `broker: A_DEFINIR`, limites à 0 et
liste blanche vide. Les hooks sont un confort ; la protection effective est l'ACL (ADR-003, B1,
B2).

## Options
1. Client de courtier (IBKR) livré dès maintenant.
2. **Garde d'activation + protocole `BrokerClient`, sans client de courtier** tant que `broker`
   vaut `A_DEFINIR`.

## Décision
Option 2.

- **`core/execution/live.py`** : `LiveAdapter` met en œuvre `BrokerAdapter` (ADR-033) au-dessus
  d'un protocole `BrokerClient`. Aucun client réel n'est livré.
- **Conditions**, toutes manuelles, toutes requises, revérifiées à chaque appel :
  1. `live.yaml` : `enabled: true`, `broker` défini, limites > 0, liste blanche non vide ;
  2. ACL posée sur `config/live.yaml` et `governance/approvals/`, vérifiée par `icacls` ;
  3. signature N3 valide (ADR-036) ;
  4. niveau effectif de la finance ≥ N3 ;
  5. kill switch non engagé ;
  6. approbation ACCORDEE, non expirée, liée à l'intention (ADR-035).
- **Refus** : une condition fausse lève une erreur nommant la condition, sans appeler le client.
  `cancel_all` reste permis sans conditions : il ne va que dans le sens sûr (kill switch).
- **Exigences pour tout client réel** : délai par appel inférieur à la cible du kill switch
  (B171) ; exécutions et relevé lus dans une même coupe (B169) ; seuls un code de refus et le nom
  du type d'exception sont journalisés (B197).
- **Limites** : une intention live passe la Porte avec les limites de `live.yaml` (toutes à 0
  aujourd'hui, donc tout est refusé).

## Conséquences
- **Test des 64 combinaisons** : seule « tout vrai » appelle le client factice.
- **Test statique** (AST) : aucun module de `core/` ni de `interfaces/` n'écrit dans
  `config/live.yaml`, `governance/approvals/` ou `var/approvals/` hors du magasin d'approbations.
- Couverture de 100 % des lignes et des branches de la garde (D19).
- Procédure manuelle : `docs/procedure-live.md`.

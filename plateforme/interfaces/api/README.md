# API interne et dashboard de CERVEAU

Une seule application locale (ADR-037, ADR-041) : l'API que le bot Discord appelle, et un
dashboard en lecture seule pour ton navigateur. Elle ne décide rien de plus que la CLI : chaque
action passe par le même moteur de politique, la même Porte de risque et le même journal d'audit.

## Lancer

- Seul toi la lances, dans ton terminal (`cerveau api serve`, D22). Aucun service ne la démarre
  tout seul.
- Elle écoute sur `127.0.0.1` seulement (D16). Le port est `api.port` dans
  `config/interfaces.yaml` ; tant qu'il vaut `A_DEFINIR`, elle refuse de démarrer (R7).
- Variable d'environnement de l'utilisateur, jamais dans un fichier du dépôt (R6) :
  `CERVEAU_API_TOKEN`, 32 caractères au moins (D1). Sans elle, ou trop courte, l'API refuse de
  démarrer.

## API

- Chaque route exige l'en-tête `Authorization: Bearer <CERVEAU_API_TOKEN>`. Sinon : 401.
- Ni documentation ni schéma servis ; aucune route de réarmement : le réarmement du kill switch se
  fait seulement dans ton terminal (ADR-034).
- Le seul client prévu est le bot Discord (voir `interfaces/discord_bot/README.md`).

## Dashboard

Adresse : `http://127.0.0.1:<port>/dashboard`, avec le port de `config/interfaces.yaml`.

Le navigateur demande un identifiant et un mot de passe :

- identifiant : n'importe lequel (il n'est pas vérifié) ;
- mot de passe : la valeur de `CERVEAU_API_TOKEN`.

Le navigateur peut mémoriser ce mot de passe ; c'est le même jeton que celui de l'API, à protéger
de la même façon. Ce mode d'accès vaut pour `/dashboard` seulement : les routes de l'API restent
en Bearer seul, pour qu'une page web ouverte dans le même navigateur ne puisse pas les déclencher
(protection contre la falsification de requêtes, CSRF).

| Page | Contenu |
|---|---|
| État | kill switch, live, autonomie écrite et en vigueur, budget LLM, boucle paper, réconciliation, chaîne du journal d'audit |
| Compte paper | dernière valorisation, positions, 10 dernières valorisations |
| Risque | rapport `finance_risk.risk_report` : volatilité, VaR et CVaR, drawdown, concentration, hypothèses ; chaque chiffre cite son identifiant (R1) |
| Décisions | approbations en attente, décomptes, ordres ouverts |
| Évals | dernier rapport d'évals et ses suites |
| Plugins | plugins acceptés et refusés par le registre, dernières erreurs du journal |

### Lecture seule

- Les pages répondent à GET seulement ; elles n'ont ni formulaire ni script.
- Elles ouvrent les fichiers en lecture seule et ne créent ni ne modifient aucun fichier.
- Rien ne s'approuve ni ne s'arrête d'ici : les approbations passent par Discord ou par ton
  terminal ; l'arrêt par `/kill` sur Discord ou `cerveau kill` dans ton terminal.
- Les montants et positions s'affichent ici parce que la page reste sur ta machine ; Discord n'en
  montre aucun (D12).
- Une configuration invalide, un fichier illisible ou un schéma ancien s'affichent comme une
  alerte sur la page concernée, sans bloquer les autres.

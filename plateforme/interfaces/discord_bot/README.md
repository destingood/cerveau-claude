# Bot Discord de CERVEAU

Bot mince (ADR-037) : il relaie les commandes de l'utilisateur à l'API interne locale et lui poste les
alertes et les demandes d'approbation. Il ne décide rien : un refus, un verrouillage ou un arrêt
est la réponse de l'API, relayée telle quelle.

## Ce qu'il fait

- `/status` : kill switch, live, niveaux en vigueur, approbations, ordres, réconciliation, budget.
- `/kill` : arrêt total, sans code (D11). L'arrêt part avant la réponse à Discord ; s'il n'est pas
  confirmé, le bot demande de lancer `cerveau kill` dans un terminal.
- `/approbations` : demandes en attente (10 au plus), chacune avec ses boutons.
- `/rapport [jour]` : rapport quotidien, avec la tête de la chaîne d'audit (D13).
- Boutons **Approuver** (ouvre une fenêtre qui demande le code à usage unique) et **Refuser**.
- Toutes les 15 s : les alertes de la boîte d'envoi Discord (ADR-038) et les nouvelles demandes.
- Aucun réarmement : il se fait seulement dans ton terminal (ADR-034).

Les échéances sont des horodatages Discord : chaque appareil les affiche dans son propre fuseau.

## Prérequis

- Node.js 24 ou plus.
- L'API interne lancée par toi (`cerveau api serve`, D22).
- `config/interfaces.yaml` : `discord.owner_user_id` (ton identifiant Discord numérique, entre
  guillemets) et `api.port` renseignés. Tant que `owner_user_id` vaut `A_DEFINIR`, l'API répond
  503 et le bot refuse de démarrer (R7).

Variables d'environnement de l'utilisateur, jamais dans un fichier du dépôt (R6) :

| Variable | Rôle |
|---|---|
| `DISCORD_BOT_TOKEN` | jeton du bot (portail développeur Discord) |
| `CERVEAU_API_TOKEN` | le même jeton que celui de l'API, 32 caractères au moins |
| `CERVEAU_API_URL` | `http://127.0.0.1:<port>`, avec le port de `config/interfaces.yaml` (D16) |

## Installation côté Discord (une fois)

1. Créer une application dans le portail développeur Discord et récupérer le jeton du bot. Aucun
   intent n'est nécessaire : le bot ne lit aucun message.
2. Installer l'application sur un serveur privé dont tu es le seul membre humain (installation
   « serveur », portées `bot` et `applications.commands`). Un bot n'écrit en message privé qu'à
   un utilisateur avec qui il partage un serveur, et seulement si ce serveur autorise les messages
   privés de ses membres [À VÉRIFIER dans la documentation Discord au moment de l'installation].
3. Les commandes n'existent que dans les messages privés avec le bot. Ailleurs, ou venant d'un
   autre compte, une interaction est ignorée et signalée à l'API, sans identifiant ni contenu.

## Lancement (l'utilisateur seul, D22)

Dans ce dossier :

```bash
npm ci
```

```bash
npm start
```

Le bot refuse de démarrer si une variable manque, si l'URL ne vise pas la boucle locale, si l'API
ne répond pas, si `owner_user_id` n'est pas défini ou si le curseur est illisible. `Ctrl+C`
l'arrête proprement.

## Curseur

`var/notify/discord_cursor.json` garde le numéro de la dernière alerte postée et les demandes déjà
montrées. Il est sauvé après chaque envoi : un redémarrage ne perd ni ne répète une alerte. S'il
est illisible, le bot s'arrête plutôt que de tout republier ; le supprimer republierait toute la
boîte d'envoi.

## Sécurité

- Seul ton compte, en message privé, reçoit une réponse.
- Le code à usage unique passe à l'API ; il n'est ni journalisé, ni renvoyé, ni conservé.
- Aucun montant ni position hors du message d'approbation (D12) ; aucun message ne mentionne
  personne.
- Le journal du bot ne contient que le type et le statut d'une erreur, jamais son texte.
- L'API n'est appelée que sur la boucle locale, sans suivre de redirection, avec un délai de 10 s.
- `.npmrc` : `ignore-scripts=true` (aucun script d'installation des dépendances ne s'exécute) et
  versions exactes ; `package-lock.json` fige les 25 paquets (licences : `docs/licences.md`).

## Tests

```bash
npm test
```

Sans réseau ni Discord : une fausse API et de fausses interactions (`test/fakes.js`). `make ci`
les lance (`make bot-test`) et audite les dépendances (`npm audit`).

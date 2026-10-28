# ADR-037 — API interne locale et bot Discord mince

- Statut : accepté (D1, D11, D12, D13, D22 et D23 du plan de phase 5, validées par Lucas le
  21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le §17 demande un bot Discord pour les approbations, `/kill` et `/status`. La section 5 de la
spécification prévoit discord.js et une API interne FastAPI. Toute la logique (approbations, kill
switch, politique) est en Python.

## Options
1. discord.py dans un seul processus Python.
2. **discord.js 14.27.0, client mince, au-dessus d'une API interne FastAPI.**

## Décision
Option 2.

- **API (`interfaces/api/`)** : FastAPI, liée à `127.0.0.1` seulement (port `A_DEFINIR` dans
  `config/interfaces.yaml`). Jeton `CERVEAU_API_TOKEN` (variable d'environnement), comparé en temps
  constant ; absent ⇒ l'API refuse de démarrer. Routes : `GET /status`, `POST /kill`,
  `GET /approvals/pending`, `POST /approvals/{id}/approve` (code requis), `POST
  /approvals/{id}/refuse`, `GET /reports/daily`. **Aucune route de réarmement** (ADR-034).
- **Bot (`interfaces/discord_bot/`)** : Node, discord.js 14.27.0, `package-lock.json` épinglé. Il
  relaie à l'API et ne décide rien. Il ne répond qu'à l'identifiant Discord de Lucas
  (`owner_user_id`, `A_DEFINIR`), en message privé ; tout autre utilisateur ou salon est ignoré et
  signalé à l'API pour le journal.
- **Approbation** : message (instrument, sens, quantité retenue, prix limite, raisons de la Porte,
  échéance) et deux boutons. « Approuver » ouvre une modale (`ModalBuilder` +
  `LabelBuilder`/`addLabelComponents`, API de 14.27 vérifiée le 21/10/2026) qui demande le code ;
  le bot le transmet sans le journaliser.
- **`/kill` (D11)** : sans code, identifiant de Lucas seulement ; il ne va que dans le sens sûr.
- **Contenu (D12)** : états, nombres et pourcentages ; ni montant ni position, sauf le message
  d'approbation.
- **Rapport quotidien (D13)** : en message privé, avec la tête de la chaîne d'audit comme ancre
  externe horodatée (B8 en partie).
- **Lancement (D22)** : par Lucas seul. Claude Code ne lance ni l'API ni le bot et ne se connecte
  à aucun service ; les hooks refusent le lancement du bot.

## Conséquences
- Un compte Discord compromis ne suffit pas à approuver (code TOTP, ADR-035) ; il peut arrêter
  CERVEAU, ce qui est sûr.
- Deux chaînes de dépendances : `pip-audit` et `npm audit`.
- **Tests sans réseau** : `TestClient` de FastAPI (jeton absent ou faux ⇒ 401, aucune route de
  réarmement, `/kill` sous la cible) ; `node:test` avec un faux client Discord.

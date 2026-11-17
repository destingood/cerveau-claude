# ADR-038 — Notifications : ntfy et Discord, contenu minimal, jamais bloquantes

- Statut : accepté (D14 et D23 du plan de phase 5, validées par l'utilisateur le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Les alertes du kill switch, des incidents et du budget restent aujourd'hui au journal et à la
console (ADR-034, B46, B172). Sur ntfy.sh, la documentation indique que les sujets sont publics et
que le sujet sert en pratique de mot de passe (docs.ntfy.sh/publish, lu le 21/10/2026).

## Options
1. ntfy auto-hébergé, joignable par VPN.
2. **ntfy.sh avec un sujet aléatoire long et un contenu minimal**, jusqu'au VPS.

## Décision
Option 2.

- **`core/notify/`** : protocole `Notifier` ; canaux ntfy (`httpx`, `POST <serveur>/<sujet>`,
  en-têtes `X-Title`, `X-Priority`, `X-Tags`, `Authorization: Bearer`) et Discord (via l'API
  interne).
- **Configuration** : URL du serveur `A_DEFINIR` dans `config/interfaces.yaml`. Le sujet (au moins
  32 caractères aléatoires) et le jeton vivent dans `NTFY_TOPIC` et `NTFY_TOKEN`, posés par
  l'utilisateur : le sujet vaut un mot de passe, il ne va pas dans le dépôt.
- **Événements** : kill switch engagé, annulation non confirmée (B172), incident d'exécution, écart
  de réconciliation, limite dépassée, approbations verrouillées, budget à 50, 80 et 100 % (B46),
  rapport quotidien prêt.
- **Contenu** : type, gravité et identifiant ; ni montant, ni instrument, ni texte externe.
- **Échec** : délai court, une entrée au journal (type d'erreur seulement), jamais de blocage d'un
  arrêt. Sans configuration, l'alerte reste au journal et à la console, et `cerveau config check`
  le signale.

## Conséquences
- Un sujet qui fuit n'apprend rien d'exploitable ; il permet au pire d'envoyer de fausses alertes.
- **Tests** : `httpx.MockTransport`, aucun réseau ; un envoi qui échoue n'interrompt pas l'arrêt.

# Sessions, sites connectés et sites bloqués

D'après `skills/reverse-api-engineer/references/sessions.md` du dépôt kalil0321/reverse-api-engineer (MIT), adapté.

## Sites qui demandent une connexion
- `chrome-mcp` pilote le vrai Chrome de l'utilisateur : ses sessions sont déjà ouvertes. Défaut des nouveaux
  fichiers de réglages dans les versions après 0.14 ; en 0.14 et pour un fichier existant, le défaut est `auto`, un
  navigateur Playwright neuf sans aucun cookie. `agent --dry-run` montre le fournisseur actif dans
  `would_run.agent_provider`. Passer `agent_provider` à `chrome-mcp` seulement sur le « oui » explicite de
  l'utilisateur : c'est son navigateur, avec tous ses comptes.
- `chrome-mcp` avec fenêtre exige Chrome 146 ou plus, auto-connect activé dans `chrome://inspect/#remote-debugging`.
  Les versions récentes le vérifient dans `agent --dry-run` (`chrome-mcp:auto-connect`) et arrêtent une capture avec
  fenêtre sur `error_kind: config_invalid` ; les plus anciennes se contentent d'un `warn` : demander alors à
  l'utilisateur de confirmer. Avec `--headless`, rae lance son propre Chrome : pas de sessions, pas de contrôle.
- Au démarrage de la capture, Chrome affiche une invite de connexion : quelqu'un doit l'accepter, sinon la capture
  expire sans client.
- `chrome-mcp` ne garde pas de HAR : impossible de retravailler avec `engineer`. Quand l'utilisateur veut itérer
  plusieurs fois sur une même capture, `auto` enregistre un HAR, au prix d'un navigateur sans ses sessions.
- Le client généré aura besoin de la même authentification : il doit lire cookies ou jetons depuis l'environnement
  ou un fichier que l'utilisateur contrôle, jamais depuis des valeurs figées sorties de la capture.

## Quand l'agent ne passe pas
Captcha, 2FA, contrôle d'appareil, détection de robots agressive : ne pas chercher à contourner. L'utilisateur
capture lui-même :
1. Il lance `reverse-api-engineer` dans un terminal, passe en mode `manual` (Shift+Tab) et tape le but.
2. Un navigateur s'ouvre (mode manuel installé : `reverse-api-engineer[manual]` + `playwright install chromium`).
   Il se connecte, fait la tâche, puis ferme le navigateur. Claude ne tape jamais son mot de passe.
3. rae génère le client depuis cette capture et l'enregistre.

Puis reprendre la main :
```
reverse-api-engineer list --mode manual -n 5 --json
reverse-api-engineer engineer <run_id> -p "<précisions>" --json
```

## Un bon but de capture
- Nommer les données et leurs champs : « nom, prix, stock et vendeur pour une recherche ».
- Nommer les variantes que le client doit gérer : pagination, filtres, tri, pages de détail.
- Un but par capture : un client « recherche » et un client « commande » se vérifient séparément.

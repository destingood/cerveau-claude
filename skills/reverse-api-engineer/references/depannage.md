# Dépannage

D'après `skills/reverse-api-engineer/references/troubleshooting.md` du dépôt kalil0321/reverse-api-engineer (MIT), adapté.

Une capture ratée renvoie `status: "error"`, un texte `error` et un `error_kind` :

| `error_kind` | Cause habituelle | Que faire |
|---|---|---|
| `misuse` | `-p` absent en mode script, mauvais drapeau, URL invalide, `engineer` sur une capture sans HAR | Corriger la commande ; `--dry-run` montre le contrôle qui échoue |
| `config_invalid` | Mauvaise valeur dans `~/.reverse-api/config.json`, SDK ou fournisseur inconnu | `agent --dry-run`, corriger la clé nommée |
| `permission_denied` | Le système a refusé un fichier ou un processus | Vérifier l'écriture dans `~/.reverse-api` et le dossier courant |
| `network` | Site ou API du modèle injoignable, délai dépassé, proxy | Réessayer une fois ; si ça persiste, vérifier la connexion avant de relancer |
| `engine_failure` | L'outillage navigateur ou la session du modèle a lâché en cours | Relancer avec `RAE_DEBUG=1` pour la trace sur stderr |
| `interrupted` | Capture annulée (Ctrl+C, SIGINT) | Relancer en arrière-plan (SKILL.md, étape 4) si une commande au premier plan a été coupée |
| `unknown` | Tout le reste, y compris des identifiants de modèle refusés | Lire `error` ; pour une erreur d'authentification, voir `reglages.md`. Ne pas relancer à l'aveugle |

Autres cas :
- **`config_invalid` avec « Chrome remote debugging is not enabled » ou « Chrome is not running »** : `chrome-mcp`
  n'a pas joint le Chrome de l'utilisateur. Lui demander d'ouvrir Chrome 146+ et d'activer auto-connect dans
  `chrome://inspect/#remote-debugging`, ou ajouter `--headless` quand le site n'exige pas sa connexion.
- **Une capture `chrome-mcp` avec fenêtre finit en moins d'une minute sans client, et `rae-run.log` montre
  `new_page` qui expire** : l'invite de connexion de Chrome est restée sans réponse. Demander à l'utilisateur de
  surveiller Chrome et d'accepter, puis relancer ; pour un site public, `--headless` évite l'invite. Les anciennes
  versions rapportent une telle capture en `status: ok` avec un `script_path` qui n'existe pas : vérifier le fichier.
- **`engineer` sort en 2 avec « captured with chrome-mcp »** : pas de HAR pour cette capture. Relancer `agent` avec un
  but plus précis.
- **La capture se fige juste après la fermeture du navigateur**, et `<runs>/har/<run_id>/` ne contient que
  `recording.har.tmp` : le fournisseur `auto` a lancé un `rae-playwright-mcp` plus vieux que 0.0.9, qui se bloque
  sur Node 26. `npx -y rae-playwright-mcp@latest --version` récupère la version corrigée (0.0.9 ou plus), puis relancer.
- **Pas de navigateur sur le PC** : ajouter `--headless`.
- **`node` ou `npx` introuvable** : le mode agent demande Node.js 20.19 ou plus ; l'installer seulement avec l'accord
  de l'utilisateur.
- **Le client tourne mais renvoie des données vides ou fausses** : la capture a sans doute raté la requête. Relancer
  `agent` avec un but qui la déclenche (« fais défiler jusqu'à la page 2 ») ou, si la capture a un HAR, y chercher le
  point d'entrée avant de retravailler.
- **L'authentification marche une fois, puis échoue** : cookies ou jetons capturés expirés. Faire lire au client des
  identifiants frais au lieu de les figer.
- **`run` prend le mauvais fichier ou demande lequel lancer** : passer `--file` ; `run <run_id> --ls` liste les fichiers.

Ne pas relancer une commande inchangée qui a déjà échoué deux fois : rapporter le texte de `error` à l'utilisateur.

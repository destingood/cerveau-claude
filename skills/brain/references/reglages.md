# 🧠 Cerveau — les réglages

Chaque réglage du cerveau, ce qu'il fait et quand le changer. Page générée depuis le code (brainkit/reglages_doc.py) par `brain publish` : ne pas la modifier à la main.

- Lire : `brain config` (tout) · `brain config <clé>` (une valeur).
- Changer : `brain config <clé> <valeur>` (JSON ou texte). La clé, le type et les bornes sont vérifiés avant d'écrire ; une valeur fausse déjà enregistrée reprend son défaut, et tu en es prévenu une fois.
- Cette page : `brain config --page` ; un seul réglage ou une section : `brain config --page recall`.
- `brain` = `python "$HOME/.claude/brain/brain.py"` (Bash et PowerShell).

123 réglages, plus 16 entrées tenues par le cerveau lui-même (dernière section).

## Sommaire

- inject — Ce qui est injecté au démarrage
- recall — Le rappel à chaque message
- promptlib — prompts.chat
- skills — Le réflexe des skills
- outils — Le réflexe des connecteurs
- stop_reminder — Le rappel de fin de tâche
- eco — Le mode éco
- style — Le style de réponse
- compact — Les sorties compactes
- mcp — Le serveur MCP
- auto_map — La carte automatique des projets
- map — Les cartes de projets
- journal — Le journal des sessions
- backup — La sauvegarde quotidienne
- due — Les échéances
- vault — Le coffre Obsidian
- wiki — Le wiki
- dream — Le rêve (entretien quotidien)
- pc — La veille du PC
- delegation — La délégation
- apprendre — L'apprentissage
- echange — L'échange de skills
- auto — La veille automatique
- commun — Le cerveau commun
- publish — La publication du plugin
- plugin — Le plugin
- selfupdate — La mise à jour du cerveau classique
- sujets — Tes sujets
- Réglages de Claude Code posés par le mode éco
- État tenu par le cerveau

## inject — Ce qui est injecté au démarrage

Les budgets de ce que le cerveau met dans le contexte de Claude, en tokens. Ce texte est relu à chaque requête jusqu'à la compaction : un budget plus petit coûte moins, un plus grand montre plus de souvenirs.

- **`inject.max_tokens`** · nombre entier · défaut `2600`
  Budget total de l'injection du démarrage (index, fiche du projet, échéances…). Le baisser allège chaque requête ; `brain optimize` dit ce qu'il coûte vraiment.
  Ex. `brain config inject.max_tokens 2000`
- **`inject.index_tokens`** · nombre entier · défaut `1650`
  Place de l'index des souvenirs quand la session ne s'ouvre pas dans un projet connu.
  Ex. `brain config inject.index_tokens <nombre>`
- **`inject.index_tokens_project`** · nombre entier · défaut `1150`
  Place de l'index des souvenirs dans un projet connu (la fiche du projet prend le reste).
  Ex. `brain config inject.index_tokens_project <nombre>`
- **`inject.project_tokens`** · nombre entier · défaut `1100`
  Place de la fiche du projet courant (ses souvenirs, ses à-faire).
  Ex. `brain config inject.project_tokens <nombre>`
- **`inject.digest_tokens`** · nombre entier · défaut `330`
  Place du résumé de la carte du projet (fichiers clés, dépendances).
  Ex. `brain config inject.digest_tokens <nombre>`
- **`inject.compact_recall_tokens`** · nombre entier · défaut `450`
  Ce qui est remis dans le contexte juste après une compaction (/compact), pour que Claude retrouve le fil.
  Ex. `brain config inject.compact_recall_tokens <nombre>`
- **`inject.resume_items`** · nombre entier · défaut `5`
  À la reprise d'une session (--resume) : au plus ce nombre de souvenirs nouveaux ou modifiés depuis son début ; le reste de l'injection est déjà dans l'historique.
  Ex. `brain config inject.resume_items <nombre>`
- **`inject.max_chars`** · nombre entier · défaut `absent`
  Ancien budget en caractères : prioritaire sur inject.max_tokens s'il est encore dans config.json. Pour revenir au budget en tokens, retire sa ligne de config.json (le chemin du fichier s'affiche avec `brain config`) : même à 0, il resterait prioritaire. Les cinq suivants marchent de même.
- **`inject.index_chars`** · nombre entier · défaut `absent`
  Ancien budget en caractères de inject.index_tokens (prioritaire s'il est là).
- **`inject.index_chars_project`** · nombre entier · défaut `absent`
  Ancien budget en caractères de inject.index_tokens_project (prioritaire s'il est là).
- **`inject.project_chars`** · nombre entier · défaut `absent`
  Ancien budget en caractères de inject.project_tokens (prioritaire s'il est là).
- **`inject.digest_chars`** · nombre entier · défaut `absent`
  Ancien budget en caractères de inject.digest_tokens (prioritaire s'il est là).
- **`inject.compact_recall_chars`** · nombre entier · défaut `absent`
  Ancien budget en caractères de inject.compact_recall_tokens (prioritaire s'il est là).
- **`inject.habit_tip`** · oui/non ou texte · défaut `absent`
  Rappel d'habitude au démarrage : le texte posé par `brain optimize --apply` (l'habitude qui coûte le plus, et son correctif) ; false pour ne plus le montrer.
  Ex. `brain config inject.habit_tip false`

## recall — Le rappel à chaque message

À chaque message, le cerveau cherche les souvenirs et les fichiers vraiment liés et les ajoute au contexte. Les seuils ont été réglés sur un banc d'essai de 62 questions (étape 3 du plan).

- **`recall.enabled`** · oui/non (true ou false) · défaut `true`
  Rappel automatique à chaque message. false : le cerveau ne rappelle plus rien tout seul (`brain q` marche toujours).
  Ex. `brain config recall.enabled false`
- **`recall.max_items`** · nombre entier · défaut `3`
  Souvenirs ajoutés au plus par message.
  Ex. `brain config recall.max_items 2`
- **`recall.min_cov`** · nombre · défaut `0.5` · de 0 à 1
  Part des mots importants du message qu'un souvenir doit couvrir pour être rappelé. Plus bas, plus de rappels mais aussi plus de faux (à 0,4 : 38 bons souvenirs sur 62 au lieu de 33, et un faux de plus ; décision E4 : 0,5 reste).
  Ex. `brain config recall.min_cov 0.6`
- **`recall.min_score`** · nombre · défaut `5.0`
  Score minimal d'un souvenir rappelé (les faux rappels mesurés notaient 2,4 à 4,8, le plus faible vrai 9,3).
  Ex. `brain config recall.min_score <nombre>`
- **`recall.files`** · oui/non (true ou false) · défaut `true`
  Rappeler aussi les fichiers du projet liés au message.
  Ex. `brain config recall.files false`
- **`recall.max_files`** · nombre entier · défaut `4`
  Fichiers ajoutés au plus par message.
  Ex. `brain config recall.max_files <nombre>`
- **`recall.min_cov_files`** · nombre · défaut `0.4` · de 0 à 1
  Comme recall.min_cov, pour les fichiers.
  Ex. `brain config recall.min_cov_files <nombre>`
- **`recall.max_chars`** · nombre entier · défaut `1200`
  Place du bloc de rappel par message, en caractères (lignes entières seulement).
  Ex. `brain config recall.max_chars <nombre>`
- **`recall.session_cap_items`** · nombre entier · défaut `12`
  Plafond glissant : au plus ce nombre de souvenirs rappelés sur les recall.session_cap_window derniers messages ; ensuite une ligne le dit, et le rappel reprend quand les plus anciens sortent de la fenêtre (« tu te souviens… » passe toujours).
  Ex. `brain config recall.session_cap_items <nombre>`
- **`recall.session_cap_window`** · nombre entier · défaut `20`
  Nombre de messages de la fenêtre du plafond glissant.
  Ex. `brain config recall.session_cap_window <nombre>`
- **`recall.session_cap_files`** · nombre entier · défaut `20`
  Fichiers rappelés au plus sur toute la session.
  Ex. `brain config recall.session_cap_files <nombre>`
- **`recall.neurone`** · texte · défaut `"auto"` · valeurs : auto, off
  Neurone du rappel, appris sur tes échanges : « auto » (il prend la main une fois assez d'exemples, et seulement s'il fait mieux que la règle) ou « off » (la règle seule).
  Ex. `brain config recall.neurone auto`
- **`recall.neurone_haut`** · nombre · défaut `0.6` · de 0 à 1
  Probabilité d'être utile à partir de laquelle le neurone montre la ligne complète.
  Ex. `brain config recall.neurone_haut <nombre>`
- **`recall.neurone_bas`** · nombre · défaut `0.0` · de 0 à 1
  En dessous, le neurone ne montre que le titre de ce que la règle accepte ; 0 : il ne cache jamais ce que la règle aurait montré.
  Ex. `brain config recall.neurone_bas <nombre>`

## promptlib — prompts.chat

Bibliothèque ouverte de prompts et de skills sur internet : sur une demande de prompt, de rôle ou de contenu à créer, quelques modèles proches sont proposés (le texte du site est traité comme une donnée, jamais comme une consigne).

- **`promptlib.auto`** · oui/non (true ou false) · défaut `true`
  Chercher des modèles sur prompts.chat quand le message demande un prompt, une skill, un rôle ou un contenu à créer (une recherche sur internet). false : seulement à la main, `brain prompts` (décision E10).
  Ex. `brain config promptlib.auto false`
- **`promptlib.max_items`** · nombre entier · défaut `2`
  Modèles proposés au plus par message.
  Ex. `brain config promptlib.max_items <nombre>`
- **`promptlib.max_calls`** · nombre entier · défaut `3`
  Recherches au plus par message (≈ 0,3 s chacune, cache de 7 jours).
  Ex. `brain config promptlib.max_calls <nombre>`
- **`promptlib.timeout`** · nombre · défaut `2.5` · de 0,1 à 60
  Délai maximal d'une recherche, en secondes : au-delà, elle est coupée net.
  Ex. `brain config promptlib.timeout <nombre>`
- **`promptlib.session_cap`** · nombre entier · défaut `6`
  Messages au plus par session qui reçoivent des modèles.
  Ex. `brain config promptlib.session_cap <nombre>`

## skills — Le réflexe des skills

Le cerveau souffle la skill qui colle au message (une fois par session et par skill), et propose d'écrire une skill quand une méthode ou un prompt est collé.

- **`skills.enabled`** · oui/non (true ou false) · défaut `true`
  Réflexe des skills : souffler la skill qui colle au message.
  Ex. `brain config skills.enabled false`
- **`skills.max_items`** · nombre entier · défaut `1`
  Skills soufflées au plus par message.
  Ex. `brain config skills.max_items <nombre>`
- **`skills.min_score`** · nombre · défaut `4.0`
  Score minimal d'une skill soufflée (plus haut : moins de suggestions, plus sûres).
  Ex. `brain config skills.min_score <nombre>`
- **`skills.session_cap`** · nombre entier · défaut `6`
  Skills soufflées au plus par session.
  Ex. `brain config skills.session_cap <nombre>`
- **`skills.exclude`** · liste · défaut `["brain"]`
  Skills jamais soufflées (noms).
  Ex. `brain config skills.exclude '["brain", "ma-skill"]'`
- **`skills.paste`** · texte · défaut `"propose"` · valeurs : auto, propose, off
  Méthode ou prompt collé dans le message : « propose » (proposer d'en faire une skill), « auto » (la faire tout de suite) ou « off » (rien).
  Ex. `brain config skills.paste auto`
- **`skills.paste_min_chars`** · nombre entier · défaut `500`
  Taille à partir de laquelle un texte collé compte comme une méthode, en caractères.
  Ex. `brain config skills.paste_min_chars <nombre>`
- **`skills.plugins`** · oui/non (true, false) ou liste de plugins · défaut `true`
  Lire aussi les skills des plugins actifs : true, false, ou la liste des plugins à lire.
  Ex. `brain config skills.plugins false`
- **`skills.triggers`** · objet JSON · défaut `{}`
  Déclencheurs ajoutés : {« plugin:skill » ou nom : [phrases]}. Se gère avec `brain skill trig` plutôt qu'à la main.
- **`skills.auto`** · liste · défaut `[]`
  Skills chargées d'office : leur contenu est ajouté par le hook dès qu'un de leurs déclencheurs est reconnu, sans passer par l'outil Skill.
  Ex. `brain config skills.auto '["ma-skill"]'`

## outils — Le réflexe des connecteurs

Gmail, Agenda, Shopify… : une ligne 🔌 donne à Claude la recherche d'outil exacte quand le message parle d'un connecteur.

- **`outils.enabled`** · oui/non (true ou false) · défaut `true`
  Réflexe des connecteurs (ligne 🔌).
  Ex. `brain config outils.enabled false`
- **`outils.max_items`** · nombre entier · défaut `2`
  Connecteurs proposés au plus par message.
  Ex. `brain config outils.max_items <nombre>`
- **`outils.session_cap`** · nombre entier · défaut `6`
  Connecteurs proposés au plus par session.
  Ex. `brain config outils.session_cap <nombre>`
- **`outils.fresh_days`** · nombre · défaut `21`
  Un serveur pas revu depuis ce nombre de jours n'est plus proposé.
  Ex. `brain config outils.fresh_days <nombre>`
- **`outils.veille`** · oui/non (true ou false) · défaut `true`
  Signaler au démarrage les nouveaux serveurs, et les skills sans déclencheur français.
  Ex. `brain config outils.veille false`
- **`outils.triggers`** · objet JSON · défaut `{}`
  Déclencheurs ajoutés : {« id » ou clé de serveur : [phrases]}. Se gère avec `brain outils trig`.

## stop_reminder — Le rappel de fin de tâche

« Mémorise ce qui est durable » en fin de tâche.

- **`stop_reminder.enabled`** · oui/non (true ou false) · défaut `true`
  Rappeler à Claude, en fin de tâche, de mémoriser ce qui est durable — seulement si tu as dit une phrase durable pas encore enregistrée (décision E3).
  Ex. `brain config stop_reminder.enabled false`

## eco — Le mode éco

Des réglages officiels de Claude Code posés une fois dans ~/.claude/settings.json pour dépenser moins de tokens sans rien perdre (voir aussi la section « Réglages de Claude Code posés par le mode éco »). Tout se défait avec `brain eco --annuler`.

- **`eco.auto`** · oui/non (true ou false) · défaut `true`
  Poser tout seul, une fois, les réglages du mode éco (puis les nouveaux d'une version plus récente). false : rien n'est posé tout seul ; `brain eco --annuler` le met à false.
  Ex. `brain config eco.auto false`
- **`eco.bash_output_max_chars`** · nombre entier · défaut `10000` · de 4000 à 128000
  Valeur posée dans bashOutputMaxChars : au-delà, une sortie de commande va dans un fichier et Claude n'en reçoit qu'un aperçu et le chemin.
  Ex. `brain config eco.bash_output_max_chars <nombre>`
- **`eco.auto_compact_window`** · nombre entier · défaut `200000` · de 100000 à 1000000
  Valeur posée dans autoCompactWindow : la taille, en tokens, à laquelle la conversation est résumée.
  Ex. `brain config eco.auto_compact_window <nombre>`
- **`eco.alerte_contexte`** · liste · défaut `[150000, 300000]`
  Tailles de conversation (tokens) à partir desquelles tu es prévenu, une fois chacune par session : chaque message relit toute la conversation. [] : jamais.
  Ex. `brain config eco.alerte_contexte '[]'`
- **`eco.alerte_pause`** · oui/non (true ou false) · défaut `true`
  Te prévenir quand tu reprends après une pause qui a vidé le cache de Claude (le message suivant coûte plein tarif).
  Ex. `brain config eco.alerte_pause false`
- **`eco.cache`** · texte · défaut `"auto"` · valeurs : auto, 5m, 1h, off
  Durée du cache de prompt : « auto » (choisie chaque jour d'après tes pauses réelles, posée seulement au-delà de 5 % de gain), « 5m », « 1h » ou « off » (ne jamais y toucher).
  Ex. `brain config eco.cache 1h`
- **`eco.plugins_auto`** · oui/non (true ou false) · défaut `false`
  Veille quotidienne qui PROPOSE, une fois, de désactiver les plugins sans usage depuis 30 jours et les skills claude.ai si aucune n'a servi ; rien n'est désactivé sans `brain eco --plugins` (décision E6). À activer avec `brain eco --plugins-auto`.
  Ex. `brain config eco.plugins_auto true`

## style — Le style de réponse

Le style de réponse par défaut de Claude Code (outputStyle).

- **`style`** · texte (nom du style) ou off · défaut `"cerveau:concis"`
  Style de réponse posé avec le mode éco quand le plugin le livre, jamais à la place d'un style que tu as choisi. « off » : rien posé, et celui que le cerveau avait posé est retiré.
  Ex. `brain config style off`

## compact — Les sorties compactes

Après une commande bavarde (installation, tests, build, git log…), Claude ne lit que l'essentiel ; la sortie brute reste quelques jours dans state/sorties/.

- **`compact.enabled`** · oui/non (true ou false) · défaut `true`
  Sorties compactes après une commande bavarde.
  Ex. `brain config compact.enabled false`
- **`compact.min_chars`** · nombre entier · défaut `1500`
  Une sortie plus courte que ce nombre de caractères n'est jamais touchée.
  Ex. `brain config compact.min_chars <nombre>`
- **`compact.min_gain`** · nombre · défaut `0.3` · de 0 à 1
  Gain minimal (part de la sortie retirée) pour compacter.
  Ex. `brain config compact.min_gain <nombre>`
- **`compact.min_saved`** · nombre entier · défaut `600`
  Gain minimal en caractères pour compacter.
  Ex. `brain config compact.min_saved <nombre>`
- **`compact.keep_days`** · nombre · défaut `3`
  Jours pendant lesquels la sortie brute reste lisible dans state/sorties/.
  Ex. `brain config compact.keep_days <nombre>`
- **`compact.max_files`** · nombre entier · défaut `40`
  Sorties brutes gardées au plus.
  Ex. `brain config compact.max_files <nombre>`
- **`compact.echantillons`** · oui/non (true ou false) · défaut `true`
  Garder aussi les sorties des commandes non reconnues (sans secret) : l'entretien du jour y repère le bruit qui revient.
  Ex. `brain config compact.echantillons false`
- **`compact.apprendre_auto`** · oui/non (true ou false) · défaut `true`
  Faire un filtre tout seul du bruit qui revient (annoncé une fois au démarrage).
  Ex. `brain config compact.apprendre_auto false`
- **`compact.filtres`** · liste · défaut `[]`
  Filtres perso : [{« cmd » : motif, « drop » : [motifs]}]. Se gèrent avec `brain compact --apprendre … --enregistrer` et `brain compact --oublier <commande>`.
- **`compact.oublies`** · liste · défaut `[]`
  Commandes dont les filtres ont été retirés pour de bon (`brain compact --oublier`) : plus aucun filtre n'y est réappris.

## mcp — Le serveur MCP

Le serveur MCP du cerveau (Claude Code par le plugin, l'app Claude, Cowork…). Chaque client relit la liste des outils à chaque requête : par défaut, seulement les 6 outils de la mémoire.

- **`mcp.groupes`** · liste de groupes · défaut `[]` · groupes : wiki, boutique, tout
  Outils ajoutés aux 6 de la mémoire : « wiki », « boutique », ou « tout » ; chaque outil de plus est relu à chaque requête du client.
  Ex. `brain config mcp.groupes '["wiki", "boutique"]'`
- **`mcp.max_car`** · nombre entier · défaut `8000` · au moins 1000
  Taille maximale d'un résultat d'outil, en caractères : au-delà, il est coupé en pages (la fin dit comment demander la suite, page: 2).
  Ex. `brain config mcp.max_car <nombre>`

## auto_map — La carte automatique des projets

Cartographie en arrière-plan des dossiers de projet.

- **`auto_map.enabled`** · oui/non (true ou false) · défaut `true`
  Cartographier en arrière-plan les dossiers de projet où tu ouvres une session.
  Ex. `brain config auto_map.enabled false`
- **`auto_map.refresh_minutes`** · nombre · défaut `10` · au moins 1
  Âge minimal d'une carte, en minutes, avant de la refaire.
  Ex. `brain config auto_map.refresh_minutes <nombre>`

## map — Les cartes de projets

Les limites d'une carte de projet (`brain map`).

- **`map.max_files`** · nombre entier · défaut `15000` · au moins 1
  Fichiers lus au plus par carte (gros dépôts).
  Ex. `brain config map.max_files <nombre>`
- **`map.max_file_kb`** · nombre entier · défaut `768` · au moins 1
  Un fichier plus gros que ce nombre de Ko n'est pas analysé.
  Ex. `brain config map.max_file_kb <nombre>`

## journal — Le journal des sessions

Le résumé de chaque session de Claude Code, cherché par `brain q`.

- **`journal.enabled`** · oui/non (true ou false) · défaut `true`
  Résumer chaque session dans le journal.
  Ex. `brain config journal.enabled false`
- **`journal.keep`** · nombre entier · défaut `500` · au moins 1
  Sessions gardées dans le journal.
  Ex. `brain config journal.keep <nombre>`

## backup — La sauvegarde quotidienne

Une archive par jour, hors de ~/.claude : sous Windows le premier autre disque (D:, E:…), sinon ~/Sauvegardes-cerveau-Claude (décision E7).

- **`backup.enabled`** · oui/non (true ou false) · défaut `true`
  Sauvegarde quotidienne, en arrière-plan à la fin d'une session.
  Ex. `brain config backup.enabled false`
- **`backup.dir`** · texte ou null · défaut `null`
  Dossier des sauvegardes. Vide : choisi tout seul (autre disque sous Windows, sinon ~/Sauvegardes-cerveau-Claude, annoncé une fois). Un disque externe ou un dossier synchronisé survit à une réinstallation du système.
  Ex. `brain config backup.dir "D:\\Sauvegardes"`
- **`backup.keep`** · nombre entier · défaut `14` · au moins 1
  Archives gardées ; les plus anciennes partent.
  Ex. `brain config backup.keep 30`

## due — Les échéances

Les à-faire datés qui approchent apparaissent au démarrage.

- **`due.days_ahead`** · nombre · défaut `7`
  Les à-faire datés apparaissent au démarrage ce nombre de jours avant leur date (et tant qu'ils sont en retard).
  Ex. `brain config due.days_ahead <nombre>`

## vault — Le coffre Obsidian

Le coffre retenu par `brain export --vault <dossier>`.

- **`vault.path`** · texte ou null · défaut `null`
  Coffre Obsidian retenu après le premier `brain export --vault <dossier>`.
  Ex. `brain config vault.path "D:\\Coffre"`

## wiki — Le wiki

Le cerveau en pages Markdown (`brain wiki init <dossier>`), synchronisées par git.

- **`wiki.path`** · texte ou null · défaut `null`
  Dossier du wiki : ses pages Markdown font foi. Posé par `brain wiki init` ; vide : retour au cerveau classique (son dernier cache).
  Ex. `brain config wiki.path "D:\\Wiki"`
- **`wiki.auto_sync`** · oui/non (true ou false) · défaut `true`
  Synchronisation git automatique du wiki sur le PC (pull au démarrage, commit et push en fin de session ; pas dans une session cloud).
  Ex. `brain config wiki.auto_sync false`
- **`wiki.sync_minutes`** · nombre · défaut `30`
  Intervalle minimal, en minutes, entre deux pull automatiques.
  Ex. `brain config wiki.sync_minutes <nombre>`

## dream — Le rêve (entretien quotidien)

L'entretien du jour, hors conversation : doublons, souvenirs à trancher, sources du wiki à ingérer.

- **`dream.notice`** · oui/non (true ou false) · défaut `true`
  Ligne au démarrage quand l'entretien du jour a des points à trancher.
  Ex. `brain config dream.notice false`
- **`dream.min_items`** · nombre entier · défaut `3`
  Points à trancher, au moins, pour cette ligne (une source du wiki à ingérer suffit toujours).
  Ex. `brain config dream.min_items <nombre>`
- **`dream.auto`** · oui/non (true ou false) · défaut `true`
  Claude traite lui-même l'entretien (sources ingérées, partie sûre appliquée, doutes laissés et cités) ; false : la ligne le propose seulement.
  Ex. `brain config dream.auto false`

## pc — La veille du PC

Une veille légère pendant les hooks (`brain pc`). Elle ne ferme jamais rien sans `brain pc --clean --oui`.

- **`pc.enabled`** · oui/non (true ou false) · défaut `true`
  Veille du PC pendant les hooks.
  Ex. `brain config pc.enabled false`
- **`pc.check_minutes`** · nombre · défaut `10`
  Intervalle minimal entre deux contrôles, en minutes.
  Ex. `brain config pc.check_minutes <nombre>`
- **`pc.auto_clean`** · oui/non (true ou false) · défaut `true`
  Lister tout seul les serveurs MCP orphelins et les proposer en une ligne (les fermer exige `brain pc --clean --oui` ; décision E5).
  Ex. `brain config pc.auto_clean false`
- **`pc.orphan_min_minutes`** · nombre · défaut `10`
  Un serveur compte comme orphelin quand son parent est mort depuis ce nombre de minutes.
  Ex. `brain config pc.orphan_min_minutes <nombre>`
- **`pc.orphan_patterns`** · liste · défaut `["\\claude\\", "\\.claude\\plugins", "claude_pzs8sxrjxfjjc", "npm-cache\\_npx"]`
  Motifs des lignes de commande qui désignent un serveur de Claude.
- **`pc.idle_hours`** · nombre · défaut `3`
  Une session de l'app sans activité depuis ce nombre d'heures est proposée à l'archivage.
  Ex. `brain config pc.idle_hours <nombre>`
- **`pc.spin_cores`** · nombre · défaut `0.5`
  Une session qui use au moins ce nombre de cœurs sans activité depuis 15 min est signalée (boucle bloquée).
  Ex. `brain config pc.spin_cores <nombre>`
- **`pc.ram_alert_gb`** · nombre · défaut `2.5`
  Mémoire libre, en Go, sous laquelle la RAM est jugée critique.
  Ex. `brain config pc.ram_alert_gb <nombre>`
- **`pc.ram_alert_pct`** · nombre entier · défaut `92` · de 0 à 100
  Part de mémoire utilisée, en %, au-delà de laquelle la RAM est jugée critique.
  Ex. `brain config pc.ram_alert_pct <nombre>`
- **`pc.alert_repeat_minutes`** · nombre · défaut `60`
  Intervalle minimal, en minutes, entre deux alertes du PC pour Claude.
  Ex. `brain config pc.alert_repeat_minutes <nombre>`
- **`pc.history_days`** · nombre · défaut `14`
  Jours d'historique des contrôles gardés (`brain pc --history`).
  Ex. `brain config pc.history_days <nombre>`

## delegation — La délégation

Chaque tâche au modèle le moins cher qui suffit, dans un contexte à part (`brain delegation`).

- **`delegation.mode`** · texte · défaut `"auto"` · valeurs : auto, max, conseil, off
  « auto » : un sous-agent lancé sans modèle part sur Haiku pour chercher, lire, résumer, sur Sonnet pour une modification mécanique (conception, débogage et décisions jamais touchés) ; « max » : tout sous-agent générique au moins sur Sonnet ; « conseil » : consigne et conseils seulement ; « off ».
  Ex. `brain config delegation.mode auto`
- **`delegation.modeles`** · objet JSON · défaut `{}`
  Modèle imposé par agent : {agent du cerveau : alias} ou {« Explore » | « general-purpose » : alias ou « off »}.
  Ex. `brain config delegation.modeles '{"Explore": "haiku"}'`
- **`delegation.reflexe`** · oui/non (true ou false) · défaut `true`
  La ligne ↪ qui propose de déléguer une tâche.
  Ex. `brain config delegation.reflexe false`
- **`delegation.session_cap`** · nombre entier · défaut `2`
  Lignes ↪ au plus par session.
  Ex. `brain config delegation.session_cap <nombre>`
- **`delegation.reve`** · oui/non (true ou false) · défaut `true`
  Confier l'entretien du jour à l'agent archiviste (sur un modèle moins cher).
  Ex. `brain config delegation.reve false`

## apprendre — L'apprentissage

Erreurs résolues, déclencheurs manqués, méthodes répétées : repérés sans token (`brain apprendre`).

- **`apprendre.enabled`** · oui/non (true ou false) · défaut `true`
  Apprentissage, sans token.
  Ex. `brain config apprendre.enabled false`
- **`apprendre.declencheurs_auto`** · oui/non (true ou false) · défaut `true`
  Une tournure commune à deux messages qui ont chargé la même skill devient un déclencheur (annoncé, retirable).
  Ex. `brain config apprendre.declencheurs_auto false`
- **`apprendre.notice`** · oui/non (true ou false) · défaut `true`
  La ligne 🎓 au démarrage (au plus une fois par jour).
  Ex. `brain config apprendre.notice false`
- **`apprendre.min_items`** · nombre entier · défaut `3`
  Points au dossier, au moins, pour la ligne 🎓.
  Ex. `brain config apprendre.min_items <nombre>`

## echange — L'échange de skills

Entre membres du cerveau commun (`brain echange`) : rien ne part sans ton oui, aucun script ne tourne sans ton accord.

- **`echange.envoi`** · texte ou null · défaut `null` · valeurs : null, oui, non
  Envoyer tes skills au cerveau commun : null tant que tu n'as pas répondu, puis « oui » ou « non » (rien ne part sans ton oui).
  Ex. `brain config echange.envoi oui`
- **`echange.reception`** · texte · défaut `"oui"` · valeurs : oui, non
  Proposer le texte des skills de tes amis quand un message colle ; « non » : jamais.
  Ex. `brain config echange.reception oui`
- **`echange.declencheurs`** · texte · défaut `"oui"` · valeurs : oui, non
  Accepter les déclencheurs que tes amis donnent à leurs skills ; « non » les retire d'un coup.
  Ex. `brain config echange.declencheurs oui`
- **`echange.partager`** · liste · défaut `[]`
  Skills écrites à la main à envoyer quand même (`brain echange partager <nom>`).
  Ex. `brain config echange.partager '["…"]'`
- **`echange.garder`** · liste · défaut `[]`
  Skills à ne jamais envoyer (`brain echange garder <nom>`).
  Ex. `brain config echange.garder '["…"]'`
- **`echange.proposees`** · liste · défaut `[]`
  Tes skills partagées proposées pour le plugin (`brain echange proposer <nom>`) ; le propriétaire décide.
- **`echange.scripts`** · objet JSON · défaut `{}`
  Empreintes des scripts de skills reçues que tu as approuvés : un script ne tourne jamais sans ton accord. Se gère avec `brain echange`, pas à la main.
- **`echange.acceptees`** · objet JSON · défaut `{}`
  Skills d'amis que tu as adoptées. Se gère avec `brain echange`, pas à la main.

## auto — La veille automatique

`brain auto` : entretien, sauvegarde et synchro quand Claude n'est pas ouvert.

- **`auto.enabled`** · oui/non (true ou false) · défaut `true`
  Veille automatique (`brain auto`, lancée toutes les 30 min par la tâche planifiée sous Windows). false la coupe sans retirer la tâche.
  Ex. `brain config auto.enabled false`

## commun — Le cerveau commun

Le dépôt partagé avec tes amis (`brain commun`).

- **`commun.repo`** · texte · défaut `absent`
  Dépôt du cerveau commun, « proprietaire/depot » ou adresse git. Sans lui, rejoindre le cerveau commun utilise le dépôt de l'auteur du plugin.
  Ex. `brain config commun.repo proprietaire/depot`

## publish — La publication du plugin

Réglages locaux de `brain publish` (jamais publiés).

- **`publish.owner`** · texte · défaut `absent`
  Ton prénom pour `brain publish` (auteur du plugin) : réglage local, jamais publié ; le wiki s'adresse à toi par ce nom.
  Ex. `brain config publish.owner Prénom`
- **`publish.repo`** · texte · défaut `absent`
  Dépôt GitHub du plugin publié, « proprietaire/depot ».
  Ex. `brain config publish.repo proprietaire/depot`
- **`publish.dir`** · texte ou null · défaut `absent`
  Dossier de publication retenu ; sans lui, `brain publish` publie sur place depuis un clone du même dépôt.
  Ex. `brain config publish.dir "D:\\cerveau-claude"`

## plugin — Le plugin

Le passage du cerveau classique au plugin.

- **`plugin.garder_classique`** · oui/non (true ou false) · défaut `false`
  true : le cerveau classique reste aux commandes et le plugin s'efface (au lieu de prendre le relais).
  Ex. `brain config plugin.garder_classique true`

## selfupdate — La mise à jour du cerveau classique

`brain self-update` depuis un arbre de développement.

- **`selfupdate.source`** · texte ou null · défaut `absent`
  Arbre de développement d'où `brain self-update` copie le code (retenu après la première mise à jour).
  Ex. `brain config selfupdate.source "D:\\cerveau-claude"`

## sujets — Tes sujets

Les mots de ton domaine, réglage local jamais publié.

- **`sujets`** · liste de mots (ou un mot) · défaut `absent`
  Mots de ton domaine (ex. tes boutiques, tes sujets) : ils s'ajoutent aux sujets connus du graphe et aux termes de prompts.chat. Réglage local, jamais publié.
  Ex. `brain config sujets '["thé", "boutique"]'`

## Réglages de Claude Code posés par le mode éco

Écrits une fois dans ~/.claude/settings.json (jamais à la place d'une valeur que tu as posée), avec une copie du fichier (settings.json.bak-cerveau-eco) et l'état d'avant gardé dans eco.avant. `brain eco --annuler` remet tout comme avant, à l'identique, et coupe eco.auto ; `brain eco` dit ce qui est posé.

| Réglage de Claude Code | Valeur posée | Effet |
|---|---|---|
| `bashOutputMaxChars` | 10 000 (`eco.bash_output_max_chars`) | Une sortie de commande plus longue va dans un fichier : Claude en reçoit un aperçu et le chemin, rien n'est perdu, et elle n'est plus relue à chaque requête (30 000 par défaut dans Claude Code). |
| `autoCompactWindow` | 200 000 (`eco.auto_compact_window`) | La conversation est résumée plus tôt : avec un modèle à 1 M de tokens, Claude Code attendrait sinon ≈ 967 k. |
| `skillListingBudgetFraction` | 0,005 | La liste des skills est plafonnée à 0,5 % du contexte (1 % par défaut) ; au-delà, Claude Code retire d'abord les descriptions des skills les moins utilisées, tous les noms restent (décision E2). |
| `skillListingMaxDescChars` | 250 | Chaque description de skill est coupée à 250 caractères dans cette liste (1 536 par défaut) ; pas posé si tu as réglé toi-même skillListingBudgetFraction (décision E2). |
| `autoMemoryEnabled` | false | La mémoire automatique de Claude Code ferait double emploi avec le cerveau ; coupée seulement quand tout ce qu'elle contient est importé dans le cerveau, et jamais si tu as réglé CLAUDE_CODE_DISABLE_AUTO_MEMORY. |
| `outputStyle` | `cerveau:concis` (`style`) | Le style de réponse cerveau:concis, jamais à la place d'un style que tu as choisi (`brain config style off`). |
| `promptCacheTtl` | 5m ou 1h | Cache adaptatif (eco.cache « auto ») : la durée choisie chaque jour d'après tes pauses réelles des 7 derniers jours, posée seulement si le gain est net. |
| `enabledPlugins, syncClaudeAiSkills` | — | Jamais touchés tout seuls : la veille (eco.plugins_auto) propose, et seul `brain eco --plugins` désactive, après ton accord (décision E6). |

## État tenu par le cerveau

Ces entrées de config.json sont écrites par le cerveau lui-même (dates, ce qu'il a posé) : à ne pas modifier à la main.

- **`journal.rattrapage_le`** — Date du dernier contrôle quotidien des sessions des 7 derniers jours absentes du journal (hooks muets) ; elles sont alors importées en arrière-plan.
- **`eco.avant`** — L'état de settings.json d'avant le mode éco, pour le rétablir à l'identique (`brain eco --annuler`).
- **`eco.pose`** — Ce que le mode éco a posé lui-même (jamais une valeur à toi).
- **`eco.applique_le`** — Date de la première application du mode éco.
- **`eco.leviers`** — Nombre de leviers déjà posés : une version qui en ajoute pose seulement les nouveaux.
- **`eco.propose`** — Le dernier lot de plugins proposés à la désactivation (proposé une seule fois).
- **`eco.plugins_vus_le`** — Date de la dernière veille des plugins.
- **`eco.cache_vu_le`** — Date de la dernière simulation du cache adaptatif.
- **`eco.bilan`** — Résultat de la dernière simulation du cache (gain, fenêtre).
- **`eco.annonce`** — Annonce laissée par une tâche de fond, montrée une fois au démarrage puis effacée.
- **`eco.propositions`** — Réglages sur accord posés par `brain eco --poser` (et de quoi les retirer, `--retirer`).
- **`garde`** — Garde de consommation : dates du dernier passage (`le`) et du dernier lancement (`lance_le`), toutes les 2 h au plus.
- **`auto`** — Veille automatique : tâche planifiée posée (`tache`), coupée (`coupe`), dernière vérification (`verifie_le`). Seul auto.enabled est un réglage.
- **`plugin`** — Passage au plugin : date (`migre_le`), archive du code classique (`archive`) et sa version (`version_classique`). Seul plugin.garder_classique est un réglage.
- **`selfupdate`** — Dernière mise à jour (`last`, `version`). Seul selfupdate.source est un réglage.
- **`commun`** — Cerveau commun : ton état (`etat` : membre, refuse, parti…), ton nom (`nom`), ton identifiant (`id`) et le dossier du dépôt (`path`). Seul commun.repo est un réglage.

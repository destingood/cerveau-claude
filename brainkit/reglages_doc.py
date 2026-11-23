"""Les réglages du cerveau expliqués, un par un (étape 9 du plan : « chaque réglage expliqué »).

Les explications vivent ici, à côté du schéma des réglages (common.DEFAULT_CONFIG pour les clés et les défauts,
common.CONFIG_RANGES pour les bornes, reglages.py pour les choix et les exemples) ; `page()` en tire la page des
réglages. `brain publish` l'écrit dans skills/brain/references/reglages.md (lue à la demande, jamais injectée) et
`brain config --page [clé]` l'affiche. tests/test_page_reglages.py vérifie que chaque clé a son explication, qu'aucune
explication ne parle d'une clé disparue, et que la page du dépôt est celle que ce module produit.

Chargé seulement par `brain config --page`, `brain publish` et l'installation de la skill /brain : aucun hook ne le lit."""
from __future__ import annotations

import json

# Sections : titre et ce qu'elles règlent (dans l'ordre de common.DEFAULT_CONFIG, puis les sections hors défauts).
SECTIONS = {
    "inject": ("Ce qui est injecté au démarrage",
               "Les budgets de ce que le cerveau met dans le contexte de Claude, en tokens. Ce texte est relu à chaque "
               "requête jusqu'à la compaction : un budget plus petit coûte moins, un plus grand montre plus de souvenirs."),
    "recall": ("Le rappel à chaque message",
               "À chaque message, le cerveau cherche les souvenirs et les fichiers vraiment liés et les ajoute au "
               "contexte. Les seuils ont été réglés sur un banc d'essai de 62 questions (étape 3 du plan)."),
    "promptlib": ("prompts.chat",
                  "Bibliothèque ouverte de prompts et de skills sur internet : sur une demande de prompt, de rôle ou de "
                  "contenu à créer, quelques modèles proches sont proposés (le texte du site est traité comme une "
                  "donnée, jamais comme une consigne)."),
    "skills": ("Le réflexe des skills",
               "Le cerveau souffle la skill qui colle au message (une fois par session et par skill), et propose d'écrire "
               "une skill quand une méthode ou un prompt est collé."),
    "outils": ("Le réflexe des connecteurs",
               "Gmail, Agenda, Shopify… : une ligne 🔌 donne à Claude la recherche d'outil exacte quand le message parle "
               "d'un connecteur."),
    "stop_reminder": ("Le rappel de fin de tâche", "« Mémorise ce qui est durable » en fin de tâche."),
    "eco": ("Le mode éco",
            "Des réglages officiels de Claude Code posés une fois dans ~/.claude/settings.json pour dépenser moins de "
            "tokens sans rien perdre (voir aussi la section « Réglages de Claude Code posés par le mode éco »). "
            "Tout se défait avec `brain eco --annuler`."),
    "style": ("Le style de réponse", "Le style de réponse par défaut de Claude Code (outputStyle)."),
    "compact": ("Les sorties compactes",
                "Après une commande bavarde (installation, tests, build, git log…), Claude ne lit que l'essentiel ; la "
                "sortie brute reste quelques jours dans state/sorties/."),
    "mcp": ("Le serveur MCP",
            "Le serveur MCP du cerveau (Claude Code par le plugin, l'app Claude, Cowork…). Chaque client relit la liste "
            "des outils à chaque requête : par défaut, seulement les 6 outils de la mémoire."),
    "auto_map": ("La carte automatique des projets", "Cartographie en arrière-plan des dossiers de projet."),
    "map": ("Les cartes de projets", "Les limites d'une carte de projet (`brain map`)."),
    "journal": ("Le journal des sessions", "Le résumé de chaque session de Claude Code, cherché par `brain q`."),
    "backup": ("La sauvegarde quotidienne",
               "Une archive par jour, hors de ~/.claude : sous Windows le premier autre disque (D:, E:…), sinon "
               "~/Sauvegardes-cerveau-Claude (décision E7)."),
    "due": ("Les échéances", "Les à-faire datés qui approchent apparaissent au démarrage."),
    "vault": ("Le coffre Obsidian", "Le coffre retenu par `brain export --vault <dossier>`."),
    "wiki": ("Le wiki", "Le cerveau en pages Markdown (`brain wiki init <dossier>`), synchronisées par git."),
    "dream": ("Le rêve (entretien quotidien)",
              "L'entretien du jour, hors conversation : doublons, souvenirs à trancher, sources du wiki à ingérer."),
    "pc": ("La veille du PC",
           "Une veille légère pendant les hooks (`brain pc`). Elle ne ferme jamais rien sans `brain pc --clean --oui`."),
    "delegation": ("La délégation",
                   "Chaque tâche au modèle le moins cher qui suffit, dans un contexte à part (`brain delegation`)."),
    "apprendre": ("L'apprentissage",
                  "Erreurs résolues, déclencheurs manqués, méthodes répétées : repérés sans token (`brain apprendre`)."),
    "echange": ("L'échange de skills",
                "Entre membres du cerveau commun (`brain echange`) : rien ne part sans ton oui, aucun script ne tourne "
                "sans ton accord."),
    "auto": ("La veille automatique", "`brain auto` : entretien, sauvegarde et synchro quand Claude n'est pas ouvert."),
    "commun": ("Le cerveau commun", "Le dépôt partagé avec tes amis (`brain commun`)."),
    "publish": ("La publication du plugin", "Réglages locaux de `brain publish` (jamais publiés)."),
    "plugin": ("Le plugin", "Le passage du cerveau classique au plugin."),
    "selfupdate": ("La mise à jour du cerveau classique", "`brain self-update` depuis un arbre de développement."),
    "sujets": ("Tes sujets", "Les mots de ton domaine, réglage local jamais publié."),
}

# Une explication par réglage : ce qu'il fait, quand le changer. Le type, le défaut, les bornes et l'exemple viennent
# du schéma (reglages.py, common.CONFIG_RANGES) : ils ne sont pas répétés ici.
TEXTES = {
    # --- inject
    "inject.max_tokens": "Budget total de l'injection du démarrage (index, fiche du projet, échéances…). Le baisser "
                         "allège chaque requête ; `brain optimize` dit ce qu'il coûte vraiment.",
    "inject.index_tokens": "Place de l'index des souvenirs quand la session ne s'ouvre pas dans un projet connu.",
    "inject.index_tokens_project": "Place de l'index des souvenirs dans un projet connu (la fiche du projet prend le "
                                   "reste).",
    "inject.project_tokens": "Place de la fiche du projet courant (ses souvenirs, ses à-faire).",
    "inject.digest_tokens": "Place du résumé de la carte du projet (fichiers clés, dépendances).",
    "inject.compact_recall_tokens": "Ce qui est remis dans le contexte juste après une compaction (/compact), pour "
                                    "que Claude retrouve le fil.",
    "inject.resume_items": "À la reprise d'une session (--resume) : au plus ce nombre de souvenirs nouveaux ou "
                           "modifiés depuis son début ; le reste de l'injection est déjà dans l'historique.",
    "inject.max_chars": "Ancien budget en caractères : prioritaire sur inject.max_tokens s'il est encore dans "
                        "config.json. Pour revenir au budget en tokens, retire sa ligne de config.json (le chemin du "
                        "fichier s'affiche avec `brain config`) : même à 0, il resterait prioritaire. Les cinq "
                        "suivants marchent de même.",
    "inject.index_chars": "Ancien budget en caractères de inject.index_tokens (prioritaire s'il est là).",
    "inject.index_chars_project": "Ancien budget en caractères de inject.index_tokens_project (prioritaire s'il est là).",
    "inject.project_chars": "Ancien budget en caractères de inject.project_tokens (prioritaire s'il est là).",
    "inject.digest_chars": "Ancien budget en caractères de inject.digest_tokens (prioritaire s'il est là).",
    "inject.compact_recall_chars": "Ancien budget en caractères de inject.compact_recall_tokens (prioritaire s'il est là).",
    "inject.habit_tip": "Rappel d'habitude au démarrage : le texte posé par `brain optimize --apply` (l'habitude qui "
                        "coûte le plus, et son correctif) ; false pour ne plus le montrer.",
    # --- recall
    "recall.enabled": "Rappel automatique à chaque message. false : le cerveau ne rappelle plus rien tout seul "
                      "(`brain q` marche toujours).",
    "recall.max_items": "Souvenirs ajoutés au plus par message.",
    "recall.min_cov": "Part des mots importants du message qu'un souvenir doit couvrir pour être rappelé. Plus bas, "
                      "plus de rappels mais aussi plus de faux (à 0,4 : 38 bons souvenirs sur 62 au lieu de 33, et un "
                      "faux de plus ; décision E4 : 0,5 reste).",
    "recall.min_score": "Score minimal d'un souvenir rappelé (les faux rappels mesurés notaient 2,4 à 4,8, le plus "
                        "faible vrai 9,3).",
    "recall.files": "Rappeler aussi les fichiers du projet liés au message.",
    "recall.max_files": "Fichiers ajoutés au plus par message.",
    "recall.min_cov_files": "Comme recall.min_cov, pour les fichiers.",
    "recall.max_chars": "Place du bloc de rappel par message, en caractères (lignes entières seulement).",
    "recall.session_cap_items": "Plafond glissant : au plus ce nombre de souvenirs rappelés sur les "
                                "recall.session_cap_window derniers messages ; ensuite une ligne le dit, et le rappel "
                                "reprend quand les plus anciens sortent de la fenêtre (« tu te souviens… » passe toujours).",
    "recall.session_cap_window": "Nombre de messages de la fenêtre du plafond glissant.",
    "recall.session_cap_files": "Fichiers rappelés au plus sur toute la session.",
    "recall.neurone": "Neurone du rappel, appris sur tes échanges : « auto » (il prend la main une fois assez "
                      "d'exemples, et seulement s'il fait mieux que la règle) ou « off » (la règle seule).",
    "recall.neurone_haut": "Probabilité d'être utile à partir de laquelle le neurone montre la ligne complète.",
    "recall.neurone_bas": "En dessous, le neurone ne montre que le titre de ce que la règle accepte ; 0 : il ne cache "
                          "jamais ce que la règle aurait montré.",
    # --- promptlib
    "promptlib.auto": "Chercher des modèles sur prompts.chat quand le message demande un prompt, une skill, un rôle ou "
                      "un contenu à créer (une recherche sur internet). false : seulement à la main, `brain prompts` "
                      "(décision E10).",
    "promptlib.max_items": "Modèles proposés au plus par message.",
    "promptlib.max_calls": "Recherches au plus par message (≈ 0,3 s chacune, cache de 7 jours).",
    "promptlib.timeout": "Délai maximal d'une recherche, en secondes : au-delà, elle est coupée net.",
    "promptlib.session_cap": "Messages au plus par session qui reçoivent des modèles.",
    # --- skills
    "skills.enabled": "Réflexe des skills : souffler la skill qui colle au message.",
    "skills.max_items": "Skills soufflées au plus par message.",
    "skills.min_score": "Score minimal d'une skill soufflée (plus haut : moins de suggestions, plus sûres).",
    "skills.session_cap": "Skills soufflées au plus par session.",
    "skills.exclude": "Skills jamais soufflées (noms).",
    "skills.paste": "Méthode ou prompt collé dans le message : « propose » (proposer d'en faire une skill), « auto » "
                    "(la faire tout de suite) ou « off » (rien).",
    "skills.paste_min_chars": "Taille à partir de laquelle un texte collé compte comme une méthode, en caractères.",
    "skills.plugins": "Lire aussi les skills des plugins actifs : true, false, ou la liste des plugins à lire.",
    "skills.triggers": "Déclencheurs ajoutés : {« plugin:skill » ou nom : [phrases]}. Se gère avec `brain skill trig` "
                       "plutôt qu'à la main.",
    "skills.auto": "Skills chargées d'office : leur contenu est ajouté par le hook dès qu'un de leurs déclencheurs est "
                   "reconnu, sans passer par l'outil Skill.",
    # --- outils
    "outils.enabled": "Réflexe des connecteurs (ligne 🔌).",
    "outils.max_items": "Connecteurs proposés au plus par message.",
    "outils.session_cap": "Connecteurs proposés au plus par session.",
    "outils.fresh_days": "Un serveur pas revu depuis ce nombre de jours n'est plus proposé.",
    "outils.veille": "Signaler au démarrage les nouveaux serveurs, et les skills sans déclencheur français.",
    "outils.triggers": "Déclencheurs ajoutés : {« id » ou clé de serveur : [phrases]}. Se gère avec `brain outils trig`.",
    # --- stop_reminder
    "stop_reminder.enabled": "Rappeler à Claude, en fin de tâche, de mémoriser ce qui est durable — seulement si tu as "
                             "dit une phrase durable pas encore enregistrée (décision E3).",
    # --- eco
    "eco.auto": "Poser tout seul, une fois, les réglages du mode éco (puis les nouveaux d'une version plus récente). "
                "false : rien n'est posé tout seul ; `brain eco --annuler` le met à false.",
    "eco.bash_output_max_chars": "Valeur posée dans bashOutputMaxChars : au-delà, une sortie de commande va dans un "
                                 "fichier et Claude n'en reçoit qu'un aperçu et le chemin.",
    "eco.auto_compact_window": "Valeur posée dans autoCompactWindow : la taille, en tokens, à laquelle la conversation "
                               "est résumée.",
    "eco.alerte_contexte": "Tailles de conversation (tokens) à partir desquelles tu es prévenu, une fois chacune par "
                           "session : chaque message relit toute la conversation. [] : jamais.",
    "eco.alerte_pause": "Te prévenir quand tu reprends après une pause qui a vidé le cache de Claude (le message "
                        "suivant coûte plein tarif).",
    "eco.cache": "Durée du cache de prompt : « auto » (choisie chaque jour d'après tes pauses réelles, posée seulement "
                 "au-delà de 5 % de gain), « 5m », « 1h » ou « off » (ne jamais y toucher).",
    "eco.plugins_auto": "Veille quotidienne qui PROPOSE, une fois, de désactiver les plugins sans usage depuis 30 jours "
                        "et les skills claude.ai si aucune n'a servi ; rien n'est désactivé sans `brain eco --plugins` "
                        "(décision E6). À activer avec `brain eco --plugins-auto`.",
    # --- style
    "style": "Style de réponse posé avec le mode éco quand le plugin le livre, jamais à la place d'un style que tu as "
             "choisi. « off » : rien posé, et celui que le cerveau avait posé est retiré.",
    # --- compact
    "compact.enabled": "Sorties compactes après une commande bavarde.",
    "compact.min_chars": "Une sortie plus courte que ce nombre de caractères n'est jamais touchée.",
    "compact.min_gain": "Gain minimal (part de la sortie retirée) pour compacter.",
    "compact.min_saved": "Gain minimal en caractères pour compacter.",
    "compact.keep_days": "Jours pendant lesquels la sortie brute reste lisible dans state/sorties/.",
    "compact.max_files": "Sorties brutes gardées au plus.",
    "compact.echantillons": "Garder aussi les sorties des commandes non reconnues (sans secret) : l'entretien du jour y "
                            "repère le bruit qui revient.",
    "compact.apprendre_auto": "Faire un filtre tout seul du bruit qui revient (annoncé une fois au démarrage).",
    "compact.filtres": "Filtres perso : [{« cmd » : motif, « drop » : [motifs]}]. Se gèrent avec `brain compact "
                       "--apprendre … --enregistrer` et `brain compact --oublier <commande>`.",
    "compact.oublies": "Commandes dont les filtres ont été retirés pour de bon (`brain compact --oublier`) : plus "
                       "aucun filtre n'y est réappris.",
    # --- mcp
    "mcp.groupes": "Outils ajoutés aux 6 de la mémoire : « wiki », « boutique », ou « tout » ; chaque outil de plus est "
                   "relu à chaque requête du client.",
    "mcp.max_car": "Taille maximale d'un résultat d'outil, en caractères : au-delà, il est coupé en pages (la fin dit "
                   "comment demander la suite, page: 2).",
    # --- auto_map, map
    "auto_map.enabled": "Cartographier en arrière-plan les dossiers de projet où tu ouvres une session.",
    "auto_map.refresh_minutes": "Âge minimal d'une carte, en minutes, avant de la refaire.",
    "map.max_files": "Fichiers lus au plus par carte (gros dépôts).",
    "map.max_file_kb": "Un fichier plus gros que ce nombre de Ko n'est pas analysé.",
    # --- journal
    "journal.enabled": "Résumer chaque session dans le journal.",
    "journal.keep": "Sessions gardées dans le journal.",
    # --- backup
    "backup.enabled": "Sauvegarde quotidienne, en arrière-plan à la fin d'une session.",
    "backup.dir": "Dossier des sauvegardes. Vide : choisi tout seul (autre disque sous Windows, sinon "
                  "~/Sauvegardes-cerveau-Claude, annoncé une fois). Un disque externe ou un dossier synchronisé "
                  "survit à une réinstallation du système.",
    "backup.keep": "Archives gardées ; les plus anciennes partent.",
    # --- due, vault
    "due.days_ahead": "Les à-faire datés apparaissent au démarrage ce nombre de jours avant leur date (et tant qu'ils "
                      "sont en retard).",
    "vault.path": "Coffre Obsidian retenu après le premier `brain export --vault <dossier>`.",
    # --- wiki
    "wiki.path": "Dossier du wiki : ses pages Markdown font foi. Posé par `brain wiki init` ; vide : retour au "
                 "cerveau classique (son dernier cache).",
    "wiki.auto_sync": "Synchronisation git automatique du wiki sur le PC (pull au démarrage, commit et push en fin de "
                      "session ; pas dans une session cloud).",
    "wiki.sync_minutes": "Intervalle minimal, en minutes, entre deux pull automatiques.",
    # --- dream
    "dream.notice": "Ligne au démarrage quand l'entretien du jour a des points à trancher.",
    "dream.min_items": "Points à trancher, au moins, pour cette ligne (une source du wiki à ingérer suffit toujours).",
    "dream.auto": "Claude traite lui-même l'entretien (sources ingérées, partie sûre appliquée, doutes laissés et "
                  "cités) ; false : la ligne le propose seulement.",
    # --- pc
    "pc.enabled": "Veille du PC pendant les hooks.",
    "pc.check_minutes": "Intervalle minimal entre deux contrôles, en minutes.",
    "pc.auto_clean": "Lister tout seul les serveurs MCP orphelins et les proposer en une ligne (les fermer exige "
                     "`brain pc --clean --oui` ; décision E5).",
    "pc.orphan_min_minutes": "Un serveur compte comme orphelin quand son parent est mort depuis ce nombre de minutes.",
    "pc.orphan_patterns": "Motifs des lignes de commande qui désignent un serveur de Claude.",
    "pc.idle_hours": "Une session de l'app sans activité depuis ce nombre d'heures est proposée à l'archivage.",
    "pc.spin_cores": "Une session qui use au moins ce nombre de cœurs sans activité depuis 15 min est signalée "
                     "(boucle bloquée).",
    "pc.ram_alert_gb": "Mémoire libre, en Go, sous laquelle la RAM est jugée critique.",
    "pc.ram_alert_pct": "Part de mémoire utilisée, en %, au-delà de laquelle la RAM est jugée critique.",
    "pc.alert_repeat_minutes": "Intervalle minimal, en minutes, entre deux alertes du PC pour Claude.",
    "pc.history_days": "Jours d'historique des contrôles gardés (`brain pc --history`).",
    # --- delegation
    "delegation.mode": "« auto » : un sous-agent lancé sans modèle part sur Haiku pour chercher, lire, résumer, sur "
                       "Sonnet pour une modification mécanique (conception, débogage et décisions jamais touchés) ; "
                       "« max » : tout sous-agent générique au moins sur Sonnet ; « conseil » : consigne et conseils "
                       "seulement ; « off ».",
    "delegation.modeles": "Modèle imposé par agent : {agent du cerveau : alias} ou {« Explore » | « general-purpose » : "
                          "alias ou « off »}.",
    "delegation.reflexe": "La ligne ↪ qui propose de déléguer une tâche.",
    "delegation.session_cap": "Lignes ↪ au plus par session.",
    "delegation.reve": "Confier l'entretien du jour à l'agent archiviste (sur un modèle moins cher).",
    # --- apprendre
    "apprendre.enabled": "Apprentissage, sans token.",
    "apprendre.declencheurs_auto": "Une tournure commune à deux messages qui ont chargé la même skill devient un "
                                   "déclencheur (annoncé, retirable).",
    "apprendre.notice": "La ligne 🎓 au démarrage (au plus une fois par jour).",
    "apprendre.min_items": "Points au dossier, au moins, pour la ligne 🎓.",
    # --- echange
    "echange.envoi": "Envoyer tes skills au cerveau commun : null tant que tu n'as pas répondu, puis « oui » ou « non » "
                     "(rien ne part sans ton oui).",
    "echange.reception": "Proposer le texte des skills de tes amis quand un message colle ; « non » : jamais.",
    "echange.declencheurs": "Accepter les déclencheurs que tes amis donnent à leurs skills ; « non » les retire d'un "
                            "coup.",
    "echange.partager": "Skills écrites à la main à envoyer quand même (`brain echange partager <nom>`).",
    "echange.garder": "Skills à ne jamais envoyer (`brain echange garder <nom>`).",
    "echange.proposees": "Tes skills partagées proposées pour le plugin (`brain echange proposer <nom>`) ; le "
                         "propriétaire décide.",
    "echange.scripts": "Empreintes des scripts de skills reçues que tu as approuvés : un script ne tourne jamais sans "
                       "ton accord. Se gère avec `brain echange`, pas à la main.",
    "echange.acceptees": "Skills d'amis que tu as adoptées. Se gère avec `brain echange`, pas à la main.",
    # --- hors des défauts
    "auto.enabled": "Veille automatique (`brain auto`, lancée toutes les 30 min par la tâche planifiée sous Windows). "
                    "false la coupe sans retirer la tâche.",
    "commun.repo": "Dépôt du cerveau commun, « proprietaire/depot » ou adresse git. Sans lui, rejoindre le cerveau "
                   "commun utilise le dépôt de l'auteur du plugin.",
    "publish.owner": "Ton prénom pour `brain publish` (auteur du plugin) : réglage local, jamais publié ; le wiki "
                     "s'adresse à toi par ce nom.",
    "publish.repo": "Dépôt GitHub du plugin publié, « proprietaire/depot ».",
    "publish.dir": "Dossier de publication retenu ; sans lui, `brain publish` publie sur place depuis un clone du même "
                   "dépôt.",
    "plugin.garder_classique": "true : le cerveau classique reste aux commandes et le plugin s'efface (au lieu de "
                               "prendre le relais).",
    "selfupdate.source": "Arbre de développement d'où `brain self-update` copie le code (retenu après la première "
                         "mise à jour).",
    "sujets": "Mots de ton domaine (ex. tes boutiques, tes sujets) : ils s'ajoutent aux sujets connus du graphe et aux "
              "termes de prompts.chat. Réglage local, jamais publié.",
}

# Types en clair quand le schéma ne suffit pas (réglages à plusieurs formes hors des défauts).
TYPES = {"inject.habit_tip": "oui/non ou texte", "sujets": "liste de mots (ou un mot)"}
# Défauts à dire en mots (réglages hors des défauts : absents de config.json tant qu'on ne les pose pas).
DEFAUTS = {"inject.max_chars": "absent", "inject.index_chars": "absent", "inject.index_chars_project": "absent",
           "inject.project_chars": "absent", "inject.digest_chars": "absent", "inject.compact_recall_chars": "absent",
           "inject.habit_tip": "absent", "sujets": "absent", "auto.enabled": "true", "commun.repo": "absent",
           "publish.owner": "absent", "publish.repo": "absent", "publish.dir": "absent",
           "plugin.garder_classique": "false", "selfupdate.source": "absent", "compact.filtres": "[]",
           "compact.oublies": "[]"}

# Exemples de `brain config` quand celui du schéma ne dit rien d'utile (None : aucun exemple, la clé ne se pose pas).
_OLD_CHARS = ("inject.max_chars", "inject.index_chars", "inject.index_chars_project", "inject.project_chars",
              "inject.digest_chars", "inject.compact_recall_chars")
EXEMPLES = {**{k: None for k in _OLD_CHARS}, "inject.habit_tip": "false", "sujets": "'[\"thé\", \"boutique\"]'",
            "inject.max_tokens": "2000", "recall.min_cov": "0.6", "recall.max_items": "2", "eco.alerte_contexte": "'[]'",
            "eco.cache": "1h", "skills.exclude": "'[\"brain\", \"ma-skill\"]'", "backup.keep": "30",
            "pc.orphan_patterns": None, "compact.filtres": None, "compact.oublies": None, "skills.triggers": None,
            "outils.triggers": None, "echange.scripts": None, "echange.acceptees": None, "echange.proposees": None,
            "delegation.modeles": "'{\"Explore\": \"haiku\"}'", "publish.owner": "Prénom", "publish.repo": "proprietaire/depot",
            "selfupdate.source": '"D:\\\\cerveau-claude"', "publish.dir": '"D:\\\\cerveau-claude"'}

# État tenu par le cerveau lui-même dans des sections réglables : à ne pas modifier à la main.
ETAT = {
    "journal.rattrapage_le": "Date du dernier contrôle quotidien des sessions des 7 derniers jours absentes du "
                             "journal (hooks muets) ; elles sont alors importées en arrière-plan.",
    "eco.avant": "L'état de settings.json d'avant le mode éco, pour le rétablir à l'identique (`brain eco --annuler`).",
    "eco.pose": "Ce que le mode éco a posé lui-même (jamais une valeur à toi).",
    "eco.applique_le": "Date de la première application du mode éco.",
    "eco.leviers": "Nombre de leviers déjà posés : une version qui en ajoute pose seulement les nouveaux.",
    "eco.propose": "Le dernier lot de plugins proposés à la désactivation (proposé une seule fois).",
    "eco.plugins_vus_le": "Date de la dernière veille des plugins.",
    "eco.cache_vu_le": "Date de la dernière simulation du cache adaptatif.",
    "eco.bilan": "Résultat de la dernière simulation du cache (gain, fenêtre).",
    "eco.annonce": "Annonce laissée par une tâche de fond, montrée une fois au démarrage puis effacée.",
    "eco.propositions": "Réglages sur accord posés par `brain eco --poser` (et de quoi les retirer, `--retirer`).",
    "garde": "Garde de consommation : dates du dernier passage (`le`) et du dernier lancement (`lance_le`), toutes les "
             "2 h au plus.",
    "auto": "Veille automatique : tâche planifiée posée (`tache`), coupée (`coupe`), dernière vérification "
            "(`verifie_le`). Seul auto.enabled est un réglage.",
    "plugin": "Passage au plugin : date (`migre_le`), archive du code classique (`archive`) et sa version "
              "(`version_classique`). Seul plugin.garder_classique est un réglage.",
    "selfupdate": "Dernière mise à jour (`last`, `version`). Seul selfupdate.source est un réglage.",
    "commun": "Cerveau commun : ton état (`etat` : membre, refuse, parti…), ton nom (`nom`), ton identifiant (`id`) et "
              "le dossier du dépôt (`path`). Seul commun.repo est un réglage.",
}

# Réglages de Claude Code (~/.claude/settings.json) que le mode éco pose : (clé, valeur posée, effet).
CLAUDE_CODE = [
    ("bashOutputMaxChars", "eco.bash_output_max_chars",
     "Une sortie de commande plus longue va dans un fichier : Claude en reçoit un aperçu et le chemin, rien n'est "
     "perdu, et elle n'est plus relue à chaque requête (30 000 par défaut dans Claude Code)."),
    ("autoCompactWindow", "eco.auto_compact_window",
     "La conversation est résumée plus tôt : avec un modèle à 1 M de tokens, Claude Code attendrait sinon ≈ 967 k."),
    ("skillListingBudgetFraction", "0,005",
     "La liste des skills est plafonnée à 0,5 % du contexte (1 % par défaut) ; au-delà, Claude Code retire d'abord "
     "les descriptions des skills les moins utilisées, tous les noms restent (décision E2)."),
    ("skillListingMaxDescChars", "250",
     "Chaque description de skill est coupée à 250 caractères dans cette liste (1 536 par défaut) ; pas posé si tu "
     "as réglé toi-même skillListingBudgetFraction (décision E2)."),
    ("autoMemoryEnabled", "false",
     "La mémoire automatique de Claude Code ferait double emploi avec le cerveau ; coupée seulement quand tout ce "
     "qu'elle contient est importé dans le cerveau, et jamais si tu as réglé CLAUDE_CODE_DISABLE_AUTO_MEMORY."),
    ("outputStyle", "style",
     "Le style de réponse cerveau:concis, jamais à la place d'un style que tu as choisi (`brain config style off`)."),
    ("promptCacheTtl", "5m ou 1h",
     "Cache adaptatif (eco.cache « auto ») : la durée choisie chaque jour d'après tes pauses réelles des 7 derniers "
     "jours, posée seulement si le gain est net."),
    ("enabledPlugins, syncClaudeAiSkills", "—",
     "Jamais touchés tout seuls : la veille (eco.plugins_auto) propose, et seul `brain eco --plugins` désactive, "
     "après ton accord (décision E6)."),
]


def _all_keys() -> list:
    """Clés réglables, dans l'ordre de la page : celles de common.DEFAULT_CONFIG, puis celles hors des défauts."""
    from .common import DEFAULT_CONFIG
    from .reglages import EXTRA, EXTRA_FORMS, _flat
    keys = [k for k, _ in _flat(DEFAULT_CONFIG) if k not in ETAT]
    return keys + [k for k in list(EXTRA) + list(EXTRA_FORMS) if k not in keys]


def keys() -> list:
    return _all_keys()


def _section(key) -> str:
    return key.split(".", 1)[0]


def _bounds(key) -> str:
    from .common import CONFIG_RANGES
    from .reglages import CHOICES
    if key in CHOICES:
        return "valeurs : " + ", ".join("null" if c is None else c for c in CHOICES[key])
    if key in CONFIG_RANGES:
        lo, hi = CONFIG_RANGES[key]
        return f"de {_num(lo)} à {_num(hi)}" if hi is not None else f"au moins {_num(lo)}"
    if key == "mcp.groupes":
        return "groupes : wiki, boutique, tout"
    return ""


def _num(x) -> str:
    return (f"{x:g}" if isinstance(x, float) else str(x)).replace(".", ",")


def _default_text(key) -> str:
    from .reglages import EXTRA, _default
    if key in DEFAUTS:
        return DEFAUTS[key]
    found, value = _default(key)
    value = value if found else EXTRA.get(key)
    return json.dumps(value, ensure_ascii=False)


def entry(key) -> str:
    """Le paragraphe d'un réglage : clé, type, défaut, bornes, explication, exemple."""
    from .reglages import EXTRA, _default, example, kind
    found, default = _default(key)
    head = [f"`{key}`", TYPES.get(key) or kind(key), f"défaut `{_default_text(key)}`"]
    bounds = _bounds(key)
    if bounds:
        head.append(bounds)
    if key in EXEMPLES:
        ex = EXEMPLES[key]
    else:
        ex = example(key, default if found else EXTRA.get(key))
        if ex == _default_text(key) and isinstance(default, (int, float)) and not isinstance(default, bool):
            ex = "<nombre>"  # l'exemple du schéma serait le défaut lui-même
    tail = f"\n  Ex. `brain config {key} {ex}`" if ex is not None else ""
    return f"- **{head[0]}** · " + " · ".join(head[1:]) + f"\n  {TEXTES[key]}" + tail


def _claude_code_rows() -> list:
    from .common import DEFAULT_CONFIG
    rows = ["| Réglage de Claude Code | Valeur posée | Effet |", "|---|---|---|"]
    for name, value, effect in CLAUDE_CODE:
        if value.startswith("eco."):
            value = f"{DEFAULT_CONFIG['eco'][value[4:]]:,}".replace(",", " ") + f" (`{value}`)"
        elif value == "style":
            value = f"`{DEFAULT_CONFIG['style']}` (`style`)"
        rows.append(f"| `{name}` | {value} | {effect} |")
    return rows


def page(only=None) -> str:
    """La page des réglages en Markdown. `only` : une clé ou une section (« recall ») → seulement ce morceau."""
    all_keys = _all_keys()
    if only:
        only = str(only).strip()
        chosen = [k for k in all_keys if k == only or k.startswith(only + ".")]
        state = [k for k in ETAT if k == only or k.startswith(only + ".") or only.startswith(k + ".")]
        if not chosen and not state:
            return ""
        out = [entry(k) for k in chosen]
        out += [f"- **`{k}`** · tenu par le cerveau, à ne pas modifier\n  {ETAT[k]}" for k in state]
        return "\n".join(out) + "\n"
    sections, order = {}, []
    for k in all_keys:
        s = _section(k)
        if s not in sections:
            sections[s] = []
            order.append(s)
        sections[s].append(k)
    out = ["# 🧠 Cerveau — les réglages", "",
           "Chaque réglage du cerveau, ce qu'il fait et quand le changer. Page générée depuis le code "
           "(brainkit/reglages_doc.py) par `brain publish` : ne pas la modifier à la main.", "",
           "- Lire : `brain config` (tout) · `brain config <clé>` (une valeur).",
           "- Changer : `brain config <clé> <valeur>` (JSON ou texte). La clé, le type et les bornes sont vérifiés "
           "avant d'écrire ; une valeur fausse déjà enregistrée reprend son défaut, et tu en es prévenu une fois.",
           "- Cette page : `brain config --page` ; un seul réglage ou une section : `brain config --page recall`.",
           "- `brain` = `python \"$HOME/.claude/brain/brain.py\"` (Bash et PowerShell).", "",
           f"{len(all_keys)} réglages, plus {len(ETAT)} entrées tenues par le cerveau lui-même (dernière section).", "",
           "## Sommaire", ""]
    out += [f"- {s} — {SECTIONS[s][0]}" for s in order]
    out += ["- Réglages de Claude Code posés par le mode éco", "- État tenu par le cerveau", ""]
    for s in order:
        title, intro = SECTIONS[s]
        out += [f"## {s} — {title}", "", intro, ""]
        out += [entry(k) for k in sections[s]]
        out.append("")
    out += ["## Réglages de Claude Code posés par le mode éco", "",
            "Écrits une fois dans ~/.claude/settings.json (jamais à la place d'une valeur que tu as posée), avec une "
            "copie du fichier (settings.json.bak-cerveau-eco) et l'état d'avant gardé dans eco.avant. "
            "`brain eco --annuler` remet tout comme avant, à l'identique, et coupe eco.auto ; `brain eco` dit ce qui "
            "est posé.", ""]
    out += _claude_code_rows()
    out += ["", "## État tenu par le cerveau", "",
            "Ces entrées de config.json sont écrites par le cerveau lui-même (dates, ce qu'il a posé) : à ne pas "
            "modifier à la main.", ""]
    out += [f"- **`{k}`** — {t}" for k, t in ETAT.items()]
    return "\n".join(out) + "\n"

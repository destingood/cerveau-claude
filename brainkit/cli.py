"""Ligne de commande du cerveau : python brain.py <commande> … (aide : -h, ou <commande> -h).

Ici : le parseur (build_parser) et main(). Les commandes sont rangées par thème — cli_memoire, cli_carte,
cli_entretien, cli_outils, cli_partage, cli_installation — et un module n'est chargé qu'au moment de lancer une de
ses commandes. Les aides communes (argparse en français, die, refresh_views…) sont dans cli_commun. Les anciens noms
(cli.cmd_consolidate, cli.die, cli.node_line…) restent accessibles depuis ce module."""
from __future__ import annotations

import argparse
import os

from . import __version__
from .cli_commun import Parser, _french_argparse, _number, _positive, die
from .common import BRAIN_DIR, CMD, LOG_FILE, LockBusy, log, network_reason, oserror_fr, setup_io, short
from .store import TYPES, clean_tags


def _plus_tard(module, names):
    """Commandes d'un module cli_* : des fonctions qui le chargent au premier appel (le parseur n'importe rien)."""
    def make(name):
        def run(a):
            from importlib import import_module
            return getattr(import_module(f"{__package__}.{module}"), name)(a)
        run.__name__ = run.__qualname__ = name
        return run
    return tuple(make(n) for n in names.split())


# Commandes, par module : chargé seulement quand une de ses commandes sert
(cmd_q, cmd_obs, cmd_fiche, cmd_add, cmd_supersede, cmd_edit, cmd_rm, cmd_link, cmd_unlink, cmd_show, cmd_ls,
 cmd_proj, cmd_index, cmd_context, cmd_recall, cmd_journal, cmd_todo, cmd_done) = _plus_tard("cli_memoire",
    "cmd_q cmd_obs cmd_fiche cmd_add cmd_supersede cmd_edit cmd_rm cmd_link cmd_unlink cmd_show cmd_ls cmd_proj "
    "cmd_index cmd_context cmd_recall cmd_journal cmd_todo cmd_done")
(cmd_map, cmd_where, cmd_deps, cmd_explain, cmd_impact, cmd_path, cmd_files, cmd_concept, cmd_report) = _plus_tard("cli_carte",
    "cmd_map cmd_where cmd_deps cmd_explain cmd_impact cmd_path cmd_files cmd_concept cmd_report")
(cmd_regroupe, cmd_consolidate, cmd_dream, cmd_export, cmd_viz, cmd_vues, cmd_stats, cmd_doctor, cmd_backup,
 cmd_history, cmd_restore) = _plus_tard("cli_entretien",
    "cmd_regroupe cmd_consolidate cmd_dream cmd_export cmd_viz cmd_vues cmd_stats cmd_doctor cmd_backup "
    "cmd_history cmd_restore")
(cmd_bench, cmd_neurone, cmd_tokens, cmd_optimize, cmd_eco, cmd_delegation, cmd_apprendre, cmd_compact,
 cmd_prompts, cmd_skill, cmd_outils, cmd_pc) = _plus_tard("cli_outils",
    "cmd_bench cmd_neurone cmd_tokens cmd_optimize cmd_eco cmd_delegation cmd_apprendre cmd_compact cmd_prompts "
    "cmd_skill cmd_outils cmd_pc")
(cmd_echange, cmd_wiki, cmd_auto, cmd_boutique, cmd_commun, cmd_import) = _plus_tard("cli_partage",
    "cmd_echange cmd_wiki cmd_auto cmd_boutique cmd_commun cmd_import")
(cmd_config, cmd_hook, cmd_mcp, cmd_publish, cmd_selfupdate, cmd_install) = _plus_tard("cli_installation",
    "cmd_config cmd_hook cmd_mcp cmd_publish cmd_selfupdate cmd_install")
# Autres noms d'avant le découpage (aides, fonctions internes), servis depuis leur nouveau module
_AILLEURS = {
    "_map_answer": "cli_carte", "map_for": "cli_carte", "Parser": "cli_commun", "_ARG_FR": "cli_commun",
    "_FR": "cli_commun", "_FR_ON": "cli_commun", "_french_argparse": "cli_commun", "_number": "cli_commun",
    "_positive": "cli_commun", "body_of": "cli_commun", "die": "cli_commun", "node_line": "cli_commun",
    "project_arg": "cli_commun", "refresh_views": "cli_commun", "types_of": "cli_commun", "wiki_meta": "cli_commun",
    "_doctor_fix": "cli_entretien", "_doctor_journal": "cli_entretien", "_doctor_plugin": "cli_entretien",
    "_doctor_python": "cli_entretien", "_search_sessions": "cli_memoire",
}


def __getattr__(name):
    module = _AILLEURS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    return getattr(import_module(f"{__package__}.{module}"), name)


def build_parser():
    _french_argparse()
    p = Parser(prog="brain", description="🧠 Cerveau persistant de Claude : mémoire en graphe + "
                                "cartes de projets (façon graphify) + hooks d'injection automatique.",
                                epilog=f"Exemples : {CMD} q \"shopify robots\" · {CMD} add -t learning -T \"…\" -b \"…\" · "
                                       f"{CMD} map . · {CMD} where login")
    p.add_argument("--version", action="version", version=f"brain {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<commande>")

    def cmd(name, func, help_, aliases=()):
        sp = sub.add_parser(name, aliases=list(aliases), help=help_)
        sp.set_defaults(func=func)
        return sp

    s = cmd("q", cmd_q, "chercher dans la mémoire (+ sessions passées et fichiers du projet courant)", ["query", "search", "cherche"])
    s.add_argument("text", nargs="+")
    s.add_argument("-k", type=_number(int, 1, 200, 8), default=8, help="nombre de résultats")
    s.add_argument("-p", "--project", help="projet (id/nom/chemin, « . » = courant)")
    s.add_argument("-t", "--type", help="types séparés par des virgules")
    s.add_argument("--only", action="store_true", help="seulement le projet")
    s.add_argument("--no-files", action="store_true")
    s.add_argument("--archived", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-graph", action="store_true", help="sans les voisins (explicites et déduits) du graphe")
    s.add_argument("--at", help="chercher dans le cerveau tel qu'il était à une date (15/10, hier…)")

    s = cmd("add", cmd_add, "mémoriser (anti-doublon automatique)", ["save", "retiens"])
    s.add_argument("-t", "--type", default="learning", help=f"type : {', '.join(TYPES)} (défaut learning)")
    s.add_argument("-T", "--title", required=True)
    s.add_argument("-b", "--body", help="contenu (« - » = lire stdin)")
    s.add_argument("--body-file")
    s.add_argument("--tags", type=lambda v: clean_tags(v))
    s.add_argument("-p", "--project", help="projet (défaut : projet courant, sauf user/feedback) ; « none » = global")
    s.add_argument("-i", "--importance", type=_number(int, 1, 5, 3), default=3, help="1 à 5 (défaut 3)")
    s.add_argument("--link", action="append", help="id[:relation] (répétable)")
    s.add_argument("--id")
    s.add_argument("--source", "--src", dest="source", default="claude",
                   help="provenance : utilisateur (dit par l'utilisateur), verifie, claude (défaut), deduit")
    s.add_argument("--keys", help="mots-clés, synonymes, questions types (indexés, pour retrouver le souvenir autrement)")
    s.add_argument("--force", action="store_true", help="créer même si un souvenir quasi identique existe")
    s.add_argument("--due", help="échéance (10/11, 10/11/2026, 3 novembre, demain, dans 2 semaines)")
    s.add_argument("--replaces", "--supersede", dest="replaces", help="id du souvenir que celui-ci remplace (l'ancien est archivé)")
    s.add_argument("--resume", help="page du wiki : une phrase qui dit l'essentiel (index, rappel)")
    s.add_argument("--commun", choices=["oui", "non", "auto"], help="cerveau commun : oui = partager, non = garder privé, "
                                                                 "auto = règles par défaut")
    s.add_argument("--sources", help="page du wiki : pages Sources qui l'appuient (« [[Titre]], [[Autre]] »)")
    s.add_argument("--domaine", help="page du wiki : domaines séparés par des virgules (business, recherche, perso, lecture…)")
    s = cmd("supersede", cmd_supersede, "« nouveau » remplace « ancien » : l'ancien est archivé avec sa date de fin", ["remplace"])
    s.add_argument("new")
    s.add_argument("old")

    s = cmd("edit", cmd_edit, "modifier un souvenir", ["maj"])
    s.add_argument("id")
    s.add_argument("-T", "--title")
    s.add_argument("-b", "--body")
    s.add_argument("--body-file")
    s.add_argument("-a", "--append", help="ajouter du texte à la fin")
    s.add_argument("-t", "--type")
    s.add_argument("--tags", type=lambda v: clean_tags(v))
    s.add_argument("--add-tags")
    s.add_argument("-i", "--importance", type=_number(int, 1, 5, 4), help="1 à 5")
    s.add_argument("-p", "--project")
    s.add_argument("--path", help="nouveau chemin (projets)")
    s.add_argument("--unarchive", action="store_true")
    s.add_argument("--due", help="échéance (« none » pour l'enlever)")
    s.add_argument("--keys", help="mots-clés indexés (« none » pour les enlever)")
    s.add_argument("--resume", help="page du wiki : son résumé (« none » pour l'enlever)")
    s.add_argument("--commun", choices=["oui", "non", "auto"], help="cerveau commun : oui = partager, non = garder privé, "
                                                                 "auto = règles par défaut")
    s.add_argument("--sources", help="page du wiki : pages Sources à ajouter (« [[Titre]] » ; « none » pour vider)")
    s.add_argument("--domaine", help="page du wiki : domaines (« none » pour les enlever)")

    s = cmd("rm", cmd_rm, "archiver un souvenir (--purge = supprimer définitivement)", ["archive"])
    s.add_argument("id")
    s.add_argument("--purge", action="store_true")

    s = cmd("link", cmd_link, "relier deux souvenirs (--suggest : liens déduits à confirmer)")
    s.add_argument("a", nargs="?")
    s.add_argument("b", nargs="?")
    s.add_argument("-r", "--rel", default="relates")
    s.add_argument("--suggest", action="store_true", help="lister les liens déduits du contenu")
    s.add_argument("-n", type=_positive(), default=12)
    s = cmd("unlink", cmd_unlink, "retirer un lien")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-r", "--rel")

    s = cmd("show", cmd_show, "afficher un souvenir et ses liens (--history : ses versions)", ["voir"])
    s.add_argument("id")
    s.add_argument("--history", action="store_true", help="versions successives (instantanés)")
    s = cmd("ls", cmd_ls, "lister", ["list"])
    s.add_argument("-t", "--type")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=_positive(int, 60), default=60)
    s.add_argument("--archived", action="store_true")

    s = cmd("proj", cmd_proj, "projets : ls | add <dossier> | show <id>", ["projects", "projet"])
    s.add_argument("action", nargs="?")
    s.add_argument("target", nargs="?")
    s.add_argument("-T", "--title")
    s.add_argument("-b", "--body")

    s = cmd("map", cmd_map, "cartographier un projet (incrémental) façon graphify", ["carte"])
    s.add_argument("path", nargs="?")
    s.add_argument("-p", "--project")
    s.add_argument("--full", action="store_true", help="tout ré-analyser (ignore le cache)")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--bg", action="store_true", help="en arrière-plan")
    s.add_argument("--max-files", type=_positive(int, 15000))

    s = cmd("where", cmd_where, "où est défini un symbole (fonction, classe, variable d'env, route)", ["ou"])
    s.add_argument("name")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=_positive(int, 30), default=30)
    s = cmd("deps", cmd_deps, "imports et importeurs d'un fichier")
    s.add_argument("file")
    s.add_argument("-p", "--project")
    s = cmd("explain", cmd_explain, "fiche d'un fichier ou d'un symbole", ["explique"])
    s.add_argument("target")
    s.add_argument("-p", "--project")
    s = cmd("impact", cmd_impact, "ce qui dépend d'un fichier ou d'une fonction (avant de modifier)", ["impacts"])
    s.add_argument("target", help="fichier, symbole, ou fichier:symbole")
    s.add_argument("-d", "--depth", type=_number(int, 1, 5, 2), default=2, help="niveaux d'appelants (1 à 5)")
    s.add_argument("-p", "--project")
    s = cmd("path", cmd_path, "chemin entre deux souvenirs (graphe de mémoire) ou deux fichiers (imports)", ["chemin"])
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-p", "--project")
    s = cmd("files", cmd_files, "trouver les fichiers liés à un sujet", ["fichiers"])
    s.add_argument("text", nargs="+")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=_positive(int, 10), default=10)

    s = cmd("index", cmd_index, "régénérer l'index BRAIN.md")
    s.add_argument("--print", action="store_true")
    s = cmd("context", cmd_context, "voir ce qui est injecté au démarrage d'une session ici")
    s.add_argument("--cwd")
    s = cmd("recall", cmd_recall, "tester le rappel automatique pour un message (--pourquoi : diagnostic)")
    s.add_argument("text", nargs="+")
    s.add_argument("--cwd")
    s.add_argument("--pourquoi", action="store_true", help="chaque étape du rappel : mots, candidats, filtre, choix")
    s.add_argument("--attendu", metavar="ID", help="souvenir attendu : pourquoi il n'est pas montré")
    s = cmd("journal", cmd_journal, "sessions passées (--backfill : importer l'historique)")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=_positive(int, 12), default=12)
    s.add_argument("--backfill", action="store_true")
    s.add_argument("-s", "--search", help="chercher dans le texte des sessions passées")
    s = cmd("todo", cmd_todo, "à-faire triés par échéance", ["taches"])
    s = cmd("done", cmd_done, "marquer un à-faire comme terminé", ["fait"])
    s.add_argument("id")
    s = cmd("consolidate", cmd_consolidate, "fusionner les doublons, archiver l'obsolète et le remplacé, masquer les secrets")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("regroupe", cmd_regroupe, "regrouper : doublons reformulés, souvenirs sans projet, sujets à réunir en fiche "
                                      "— montre d'abord, applique ensuite ce que tu acceptes", ["regroup"])
    s.add_argument("--appliquer", metavar="NUMEROS", help="appliquer ces numéros de la liste (1,3 · 2-4 · tout)")
    s.add_argument("--ecarter", metavar="NUMEROS", help="ne plus proposer ces numéros de la liste")
    s = cmd("dream", cmd_dream, "rêve : entretien hors conversation (dossier REVE.md : conflits, doublons, corrections "
                               "entendues…) — --done pour le clore", ["reve"])
    s.add_argument("--done", action="store_true", help="marquer le rêve comme traité")
    s.add_argument("--no-apply", action="store_true", help="ne rien appliquer, seulement préparer le dossier")
    s = cmd("backup", cmd_backup, "sauvegarde hors de ~/.claude (second disque, sinon dossier personnel) — --list, "
                                  "--restore <archive>", ["sauvegarde"])
    s.add_argument("--to", help="dossier de sauvegarde, pour cette fois (défaut : backup.dir, sinon D:\\Sauvegardes-cerveau-"
                                "Claude ou un autre disque sous Windows, sinon ~/Sauvegardes-cerveau-Claude)")
    s.add_argument("--list", action="store_true")
    s.add_argument("--restore", help="archive .zip à restaurer")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("bench", cmd_bench, "banc d'essai : qualité du rappel, faux rappels, tokens, vitesse des hooks")
    s.add_argument("--quick", action="store_true", help="sans la mesure de vitesse")
    s = cmd("neurone", cmd_neurone, "neurone du rappel (appris sur tes échanges, local) : état, apprendre (récolte les "
            "30 derniers jours puis apprend), entrainer, off (règle fixe seule), auto", ["neurones", "neuronal"])
    s.add_argument("action", nargs="?", default="etat", choices=["etat", "apprendre", "entrainer", "off", "auto"])
    s.add_argument("--jours", type=_positive(int, 30), default=30, help="période récoltée par « apprendre » (défaut 30 jours)")
    s.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    s = cmd("tokens", cmd_tokens, "où partent les tokens : contexte relu, 1res requêtes, coût fixe au démarrage, relances du cerveau, "
            "habitudes coûteuses (transcripts)")
    s.add_argument("--hours", type=_positive(float, 48), default=48, help="période mesurée (défaut 48 h)")
    s.add_argument("--garde", action="store_true", help="garde de consommation : sessions qui mangent les dernières 24 h "
                   "(fait tout seul en arrière-plan toutes les 2 h)")
    s = cmd("optimize", cmd_optimize, "optimiser le cerveau (tokens d'abord) : coût réel de l'injection/du rappel/du "
            "corpus + ce qu'on peut alléger — --apply applique le sûr et réversible", ["optimise", "opti"])
    s.add_argument("--apply", action="store_true", help="appliquer les actions sûres et réversibles (ménage du corpus, rappel d'habitude, mode éco)")
    s.add_argument("--all", action="store_true", help="tout détailler, sans troncature")
    s.add_argument("--hours", type=_positive(float, 48), default=48, help="période mesurée pour l'habitude la plus coûteuse (défaut 48 h)")
    s = cmd("eco", cmd_eco, "mode éco : moins de tokens sans rien perdre (sorties longues mises en fichier, résumé plus tôt, "
            "plugins inutilisés, skills, mémoire, cache) — --appliquer · --annuler · --poser ID · --cache auto", ["econome"])
    s.add_argument("--appliquer", action="store_true", help="écrire les leviers sûrs (bashOutputMaxChars, autoCompactWindow, "
                   "skillListingBudgetFraction, skillListingMaxDescChars, autoMemoryEnabled) dans "
                   "~/.claude/settings.json (retour exact possible) ; fait tout seul au 1er démarrage")
    s.add_argument("--annuler", action="store_true", help="remettre exactement les réglages d'avant et couper l'application automatique")
    s.add_argument("--forcer", action="store_true", help="remplacer une valeur que tu avais déjà réglée toi-même")
    s.add_argument("--sortie", type=_number(int, None, None, 10000), help="bashOutputMaxChars, de 4000 à 128000 (défaut 10000)")
    s.add_argument("--fenetre", type=_number(int, None, None, 200000), help="autoCompactWindow en tokens, de 100000 à 1000000 (défaut 200000)")
    s.add_argument("--desactiver", nargs="+", metavar="nom@marketplace",
                   help="désactiver ces plugins inutilisés (après accord de l'utilisateur ; --annuler les réactive)")
    s.add_argument("--plugins-auto", nargs="?", const="on", choices=["on", "off"],
                   help="veille quotidienne : PROPOSE de désactiver les plugins sans usage depuis 30 j et les skills "
                        "claude.ai si aucune n'a servi, sans rien désactiver (on : active et lance tout de suite ; off : coupe)")
    s.add_argument("--plugins", action="store_true",
                   help="désactiver maintenant ces plugins et skills claude.ai proposés (après accord de l'utilisateur)")
    s.add_argument("--poser", nargs="+", metavar="ID",
                   help="poser ces propositions (outils, connecteurs, git, effort, lecture, sous-agents) — seulement après accord de l'utilisateur")
    s.add_argument("--retirer", nargs="+", metavar="ID", help="retirer ces propositions (état d'avant rétabli)")
    s.add_argument("--refuser", nargs="+", metavar="OUTIL",
                   help="retirer ces outils du contexte (règle de refus), même déjà utilisés — choix de l'utilisateur")
    s.add_argument("--rendre", nargs="+", metavar="OUTIL", help="rendre ces outils (règle de refus du cerveau retirée)")
    s.add_argument("--cache", choices=["auto", "5m", "1h", "off"],
                   help="durée du cache de prompt : auto (choisie chaque jour d'après tes pauses), 5m, 1h, "
                        "off (le cerveau n'y touche plus)")
    s = cmd("compact", cmd_compact, "sorties de commandes compactes (hook après chaque commande bavarde) : statistiques, "
            "ou essai sur une sortie enregistrée — compact sortie.txt --cmd \"npm install\" · filtres appris : "
            "--decouvrir, puis --apprendre <cmd> --enregistrer · config compact.enabled false")
    s.add_argument("fichier", nargs="?", help="sortie enregistrée à compacter (« - » : entrée standard)")
    s.add_argument("--cmd", help="commande qui a produit la sortie (choisit les règles : installation, tests, build, git…)")
    s.add_argument("--stats", action="store_true", help="ce que les sorties compactées ont épargné")
    s.add_argument("--decouvrir", action="store_true", help="le bruit qui revient dans les sorties gardées (suggestions)")
    s.add_argument("--apprendre", metavar="COMMANDE", help="filtre proposé pour cette commande, appris de ses sorties")
    s.add_argument("--enregistrer", action="store_true", help="avec --apprendre : l'ajouter à compact.filtres")
    s.add_argument("--oublier", metavar="COMMANDE", help="retirer les filtres de cette commande (appris tout seuls ou "
                   "enregistrés) et ne plus en apprendre pour elle")
    s = cmd("history", cmd_history, "instantanés du cerveau (pour revenir en arrière) — --diff <n°|date>", ["historique"])
    s.add_argument("-n", type=_positive(int, 15), default=15)
    s.add_argument("--diff", help="ce qui a changé depuis un instantané (n°) ou une date")
    s = cmd("restore", cmd_restore, "restaurer un instantané (n° de `history` ou date) — réversible", ["restaurer"])
    s.add_argument("ref")
    s = cmd("export", cmd_export, "écrire MEMOIRES.md — ou --vault <dossier> : coffre Obsidian synchronisé dans les deux sens")
    s.add_argument("--vault", nargs="?", const="", help="dossier du coffre (retenu pour les fois suivantes)")
    s.add_argument("--push", action="store_true", help="écraser le coffre avec le cerveau, sans rapatrier les modifications")
    s = cmd("concept", cmd_concept, "concepts repérés (outils, sujets, sigles…) et les souvenirs qui en parlent", ["concepts"])
    s.add_argument("name", nargs="*")
    s = cmd("fiche", cmd_fiche, "fiches de synthèse des communautés (« où en est … ») : liste, ou fiche <n°|mot|id>",
            ["fiches", "synthese"])
    s.add_argument("name", nargs="*")
    s = cmd("obs", cmd_obs, "observations datées de la session : obs \"🔴 …\" \"🟡 …\" \"🟢 …\" (sans texte : les dernières)",
            ["observe", "observations"])
    s.add_argument("text", nargs="*", help="une observation par argument ; 🔴/🟡/🟢 (ou !!!/!!/!) et « 14:20 » en tête au besoin")
    s.add_argument("-p", "--project", help="projet (défaut : projet courant) ; « none » = global")
    s.add_argument("-n", type=_positive(int, 15), default=15)
    s.add_argument("--days", type=_positive(int, 7), help="seulement les N derniers jours")
    s = cmd("report", cmd_report, "rapport façon graphify : communautés, nœuds clés, liens surprenants, trous", ["rapport"])
    s.add_argument("--print", action="store_true", help="afficher le rapport complet")
    s.add_argument("--force", action="store_true", help="recalculer l'analyse")
    s = cmd("viz", cmd_viz, "générer cerveau.html (graphe 3D interactif) et cerveau-2d.html")
    s.add_argument("--open", action="store_true")
    s = cmd("vues", cmd_vues, "vues refaites après une écriture (BRAIN.md, MEMOIRES.md, cerveau.html) : tout de suite, "
            "ou --attendre celles en cours (elles se refont seules en arrière-plan)")
    s.add_argument("--attendre", action="store_true", help="attendre que les vues demandées soient refaites")
    s.add_argument("--delai", type=_number(float, 0, None, 120), default=120.0, help="--attendre : au plus tant de secondes (défaut 120)")
    s.add_argument("--fond", action="store_true", help=argparse.SUPPRESS)
    s = cmd("prompts", cmd_prompts, "prompts.chat : chercher des prompts/skills (FR traduit), get <id> = texte "
            "complet, --hook \"message\" = ce que le rappel automatique injecterait", ["prompt", "promptschat"])
    s.add_argument("query", nargs="*")
    s.add_argument("--skills", action="store_true", help="chercher des skills plutôt que des prompts")
    s.add_argument("-n", type=_positive(int, 8), default=8)
    s.add_argument("--hook", metavar="MESSAGE", help="simuler le rappel automatique sur ce message")
    s = cmd("skill", cmd_skill, "skills perso et des plugins : ls (+ stats), test \"message\" (laquelle se "
            "déclencherait), check, new <nom> -d \"description\" [--body-file f], trig <nom> \"déclencheur\" … "
            "(en ajouter sans toucher la skill)", ["skills"])
    s.add_argument("action", nargs="?", choices=["ls", "list", "test", "check", "new", "trig"])
    s.add_argument("args", nargs="*")
    s.add_argument("-d", "--description", default="")
    s.add_argument("-b", "--body", default="")
    s.add_argument("--body-file")
    s.add_argument("--force", action="store_true", help="remplacer une skill existante (trig : la liste)")
    s.add_argument("--no-memory", action="store_true", help="ne pas créer de fiche dans le cerveau")
    s = cmd("outils", cmd_outils, "connecteurs et serveurs MCP branchés (Gmail, Agenda, Shopify…) : ls (état), test "
            "\"message\" (lequel le réflexe proposerait), trig <connecteur> \"phrase\" … (en ajouter), scan [n] (relire "
            "les n derniers transcripts)", ["outil", "connecteurs", "connecteur"])
    s.add_argument("action", nargs="?", choices=["ls", "list", "test", "trig", "scan"])
    s.add_argument("args", nargs="*")
    s.add_argument("--force", action="store_true", help="trig : remplacer la liste (seul : la vider)")
    s = cmd("pc", cmd_pc, "RAM/CPU/GPU + ce qu'on peut libérer (sessions, serveurs MCP) — --clean [--oui], --history, --all", ["ram"])
    s.add_argument("--all", action="store_true", help="tout détailler, sans troncature")
    s.add_argument("--clean", action="store_true", help="lister les serveurs MCP orphelins (parent mort) ; --oui pour les fermer")
    s.add_argument("--oui", action="store_true", help="avec --clean : fermer vraiment les orphelins listés")
    s.add_argument("--history", nargs="?", type=_positive(float, 24), const=24, metavar="H",
                   help="historique des mesures de la veille sur H heures (défaut 24)")
    s.add_argument("--seconds", type=_number(float, 0.1, 60, 2), default=2.0, help="durée de mesure du CPU/GPU (défaut 2 s)")
    cmd("stats", cmd_stats, "statistiques")
    s = cmd("doctor", cmd_doctor, "diagnostic complet de l'installation (--fix : tout réparer)")
    s.add_argument("--fix", action="store_true", help="réinstaller, reconstruire, nettoyer et sauvegarder")
    s = cmd("wiki", cmd_wiki, "le cerveau en wiki (LLM Wiki, coffre Obsidian, dépôt git) : init <dossier> · add <fichier|url|-> · "
            "pending · lint · index · log [op titre lignes…] · status · sync · schema")
    s.add_argument("action", nargs="?", help="init, add, pending, lint, index, log, status (défaut), sync, schema, "
                                                "obsidian (règle le coffre : tableau de bord, modèles, signets)")
    s.add_argument("args", nargs="*", help="init : dossier · add : fichier, url ou « - » (stdin) · log : opération titre lignes…")
    s.add_argument("-T", "--title", help="add : titre de la source")
    s.add_argument("--url", help="add : adresse d'origine (texte reçu par stdin)")
    s.add_argument("--format", help="add : article, pdf, video, podcast, livre, note, conversation, donnees, image, document")
    s.add_argument("--author", "--auteur", dest="author", help="add : auteur")
    s.add_argument("--local", action="store_true", help="add : autoriser une adresse locale ou privée (127.0.0.1, réseau interne)")
    s.add_argument("-n", type=_positive(int, 12), default=12, help="nombre de lignes (lint, pending, log)")
    s.add_argument("--log", action="store_true", help="lint : noter le passage au journal")
    s.add_argument("--no-migrate", action="store_true", help="init : ne pas migrer le cerveau classique")
    s.add_argument("--no-push", action="store_true", help="init/sync : ne pas envoyer sur GitHub")
    s.add_argument("--no-pull", action="store_true", help="sync : ne pas récupérer")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("auto", cmd_auto, "veille automatique, zéro token : une passe (notes du jour, synchro du wiki, page Cerveau, "
            "entretien du jour) — --installer pose la tâche planifiée qui en lance une toutes les 30 min", ["veille"])
    s.add_argument("--installer", action="store_true", help="poser la tâche planifiée (Windows ; ailleurs : la ligne cron)")
    s.add_argument("--retirer", action="store_true", help="retirer la tâche planifiée")
    s.add_argument("--etat", action="store_true", help="tâche posée ? dernière passe et ses étapes")
    s.add_argument("--reparer", action="store_true",
                   help="reposer la tâche si elle a disparu ou pointe vers un Python absent (jamais après --retirer)")
    s.add_argument("--dry-run", action="store_true", help="avec --installer : montrer la tâche sans la poser")
    s = cmd("boutique", cmd_boutique, "boutiques en ligne suivies (données privées) : liste · ajouter \"Nom\" · plan · "
            "kpi (semaine) · audit · bilan · panel (clients simulés) · regler", ["boutiques", "shop"])
    s.add_argument("action", nargs="?", help="liste (défaut), ajouter, plan, kpi, audit, bilan, panel, regler")
    s.add_argument("args", nargs="*", help="la boutique (slug ou nom) ; ajouter : son nom ; regler : cle=valeur …")
    s.add_argument("--url", help="ajouter : adresse de la boutique")
    s.add_argument("--plateforme", help="ajouter : shopify, woocommerce, prestashop, site statique, marketplace…")
    s.add_argument("--chemin", help="ajouter : plateforme (abonnement accepté) ou 0euro (aucun coût fixe)")
    s.add_argument("--type", help="physique, mode, createur, occasion, niche, prevente, local, numerique, b2b")
    s.add_argument("--marge-commande", dest="marge_commande", help="marge de contribution par commande (€)")
    s.add_argument("--debut", help="plan : premier jour (défaut aujourd'hui ; demain, 20/10…)")
    s.add_argument("--court", action="store_true", help="plan : 72 h et 14 jours seulement")
    s.add_argument("--force", action="store_true", help="plan : recréer (l'ancien plan ouvert est archivé)")
    s.add_argument("--sessions", help="kpi : visites de la semaine")
    s.add_argument("--ajouts", help="kpi : sessions avec ajout au panier")
    s.add_argument("--checkouts", help="kpi : paiements commencés")
    s.add_argument("--commandes", help="kpi : commandes")
    s.add_argument("--ca", help="kpi : chiffre d'affaires TTC de la semaine (€)")
    s.add_argument("--heures", help="kpi : heures passées sur la boutique dans la semaine")
    s.add_argument("--marge", help="kpi : marge de contribution totale de la semaine (sinon : commandes × marge par commande)")
    s.add_argument("--canal", action="append", help="kpi : nom:sessions:commandes[:heures] (répétable)")
    s.add_argument("--semaine", help="kpi : une date de la semaine (défaut : la dernière semaine complète)")
    s.add_argument("--note", help="kpi : ce qui s'est passé (lancement, vidéo virale, rupture…)")
    s.add_argument("--semaines", type=_positive(int, 4), default=4, help="bilan : semaines affichées (défaut 4)")
    s.add_argument("--md", help="bilan : écrire aussi le bilan dans ce fichier Markdown")
    s.add_argument("--timeout", type=_number(float, 1, 300, 20), default=20.0, help="audit : délai par requête (s)")
    s.add_argument("--conformite", action="store_true", help="audit : pages légales et points de conformité")
    s.add_argument("--pages", type=_number(int, 0, 50, 5), help="audit : nombre de pages du sitemap à lire (doublons, erreurs, noindex)")
    s.add_argument("--vitesse", action="store_true", help="audit : Core Web Vitals (PageSpeed Insights, mobile)")
    s.add_argument("--complet", action="store_true", help="audit : conformité + 10 pages + vitesse")
    s.add_argument("--rapport", help="audit : écrire aussi le rapport dans ce fichier Markdown")
    s.add_argument("--importer", help="panel : dossier d'un panel simulé (ou son synthese.json) à garder dans le suivi")
    s.add_argument("--applique", help="panel : le panel (S1…) dont une variante vient d'être mise en ligne")
    s.add_argument("--variante", help="panel : la variante mise en ligne (défaut : celle que le panel préférait)")
    s.add_argument("--le", help="panel : date de la mise en ligne (défaut aujourd'hui ; 02/11, hier…)")
    s = cmd("commun", cmd_commun, "cerveau commun avec les amis (jamais rien de privé) : etat · apercu · rejoindre --oui · "
            "non · quitter · projet <id> · sync · liste", ["partage"])
    s.add_argument("action", nargs="?", help="etat (défaut), apercu, rejoindre, non, quitter, projet, sync, liste")
    s.add_argument("args", nargs="*")
    s.add_argument("--oui", action="store_true", help="rejoindre : accord donné (sinon : aperçu seulement)")
    s.add_argument("--nom", help="rejoindre : pseudo affiché aux amis")
    s.add_argument("--garder", action="store_true", help="quitter : laisser tes pages aux amis")
    s.add_argument("--non", action="store_true", help="projet : le rendre de nouveau privé")
    s.add_argument("--no-push", action="store_true", help="sync : récupérer seulement")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--delai", type=_number(float, 0), help=argparse.SUPPRESS)
    s = cmd("delegation", cmd_delegation, "délégation aux modèles moins chers (Haiku pour chercher et lire, Sonnet pour une "
            "modification cadrée) : état et économies — --mode auto|max|conseil|off · --modele eclaireur=sonnet",
            ["deleguer"])
    s.add_argument("--mode", choices=["auto", "max", "conseil", "off"],
                   help="auto : aiguillage prudent des sous-agents lancés sans modèle + conseils ; max : tout sous-agent "
                        "générique au moins sur Sonnet ; conseil : conseils seulement ; off")
    s.add_argument("--modele", action="append", metavar="NOM=MODELE",
                   help="modèle d'un agent du cerveau (eclaireur=sonnet), ou d'un type intégré (Explore=off, "
                        "general-purpose=haiku) ; NOM=defaut pour revenir")
    s.add_argument("--jours", type=_positive(int, 7), default=7, help="période mesurée (défaut 7 jours)")
    s = cmd("apprendre", cmd_apprendre, "ce que le cerveau apprend des sessions (erreurs résolues, déclencheurs manqués, "
            "méthodes répétées) : le dossier à trancher — --fait pour le clore · etat · skill <nom> -d \"…\" "
            "--body-file f · oublier <skill> \"déclencheur\" · retours", ["apprentissage"])
    s.add_argument("action", nargs="?", help="(rien : le dossier), etat, skill, oublier, retours")
    s.add_argument("args", nargs="*")
    s.add_argument("--fait", action="store_true", help="clore le dossier : les points montrés ne reviendront pas")
    s.add_argument("-d", "--description", default="", help="skill : sa description (quand l'utiliser, « déclencheurs »)")
    s.add_argument("-b", "--body", default="", help="skill : son corps")
    s.add_argument("--body-file", help="skill : fichier qui contient son corps")
    s.add_argument("--script", action="append", metavar="FICHIER",
                   help="skill : outil à joindre (copié dans scripts/ ; répétable). Chez un ami, il attend son accord")
    s.add_argument("--force", action="store_true", help="skill : remplacer une skill existante")
    s.add_argument("--jours", type=_positive(int, 14), default=14, help="retours : période (défaut 14 jours)")
    s.add_argument("--entretien", action="store_true", help=argparse.SUPPRESS)
    s = cmd("echange", cmd_echange, "échange de skills et d'outils avec les amis du cerveau commun (texte contrôlé, "
            "scripts sur accord) : etat · apercu · oui|non · liste · voir|adopter|approuver <ami/nom> · "
            "partager|garder|proposer <nom> · propositions · promouvoir <ami/nom> --vers <dossier> · retours · sync",
            ["skills-communes"])
    s.add_argument("action", nargs="?", help="etat (défaut), apercu, oui, non, recevoir, liste, voir, partager, garder, "
                                                "proposer, adopter, approuver, declencheurs, propositions, promouvoir, "
                                                "retours, sync")
    s.add_argument("args", nargs="*")
    s.add_argument("--oui", action="store_true", help="adopter / approuver : accord de l'utilisateur donné")
    s.add_argument("--scripts", action="store_true", help="adopter : approuver aussi ses scripts (après les avoir montrés)")
    s.add_argument("--empreinte", help="adopter / approuver : l'empreinte montrée par `voir` (l'accord ne vaut que pour "
                                       "ce contenu-là)")
    s.add_argument("--non", action="store_true", help="partager / garder / proposer : revenir en arrière")
    s.add_argument("--vers", help="promouvoir : arbre de développement ou clone du dépôt du plugin")
    s.add_argument("--force", action="store_true", help="promouvoir : remplacer, ou passer outre le contrôle après relecture")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("import", cmd_import, "importer la mémoire native de Claude Code (~/.claude/projects/*/memory)")
    s.add_argument("--force", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--max-ko", type=_number(int, 0, None, 64), help="taille maximale d'un fichier importé, en Ko (défaut 64 ; 0 : sans limite)")
    s = cmd("config", cmd_config, "lire/modifier la configuration (ex : config recall.enabled false ; serveur MCP : "
            "config mcp.groupes '[\"wiki\", \"boutique\"]' ajoute ces outils aux 6 de la mémoire, "
            "config mcp.max_car 8000 borne chaque résultat)")
    s.description = ("Lire ou modifier la configuration du cerveau (config.json). Sans clé : tout. Valeur en JSON ou en "
                     "texte. Serveur MCP : les 6 outils de la mémoire sont listés par défaut ; `config mcp.groupes "
                     "'[\"wiki\", \"boutique\"]'` (ou \"tout\") ajoute ceux du wiki et des boutiques ; `config mcp.max_car "
                     "8000` : un résultat plus long est coupé en pages (la suite avec « page: 2 »).")
    s.add_argument("key", nargs="?", help="clé à points, ex : recall.enabled, mcp.groupes")
    s.add_argument("value", nargs="?", help="nouvelle valeur (JSON ou texte)")
    s = cmd("hook", cmd_hook, "point d'entrée des hooks Claude Code (usage interne)")
    s.add_argument("event", choices=["session-start", "prompt", "stop", "pre-compact", "post-compact", "session-end",
                                     "post-bash", "pre-agent"])
    s = cmd("install", cmd_install, "installer/réparer : CLAUDE.md, skill /brain, hooks (--mcp : serveur MCP de l'app)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--uninstall", action="store_true")
    s.add_argument("--mcp", action="store_true", help="enregistrer le serveur MCP « cerveau » dans l'app Claude (chat, Cowork)")
    cmd("mcp", cmd_mcp, "serveur MCP (stdio) : la même mémoire dans le chat Claude, Cowork ou tout client MCP")
    s = cmd("publish", cmd_publish, "publier le plugin Claude Code « cerveau » pour les amis (code seul, jamais les "
                                    "souvenirs) dans le clone du dépôt GitHub", ["publier"])
    s.add_argument("dir", nargs="?", help="clone local du dépôt (retenu ensuite) ; sans lui, le dossier du code s'il "
                                          "est un clone git : publication sur place, sans rien effacer")
    s.add_argument("--repo", help="dépôt GitHub « proprietaire/depot » (retenu ensuite)")
    s.add_argument("--owner", help="nom public de l'auteur (défaut : le compte GitHub de --repo)")
    s.add_argument("--push", action="store_true", help="envoyer sur GitHub après le commit (publication)")
    s.add_argument("--no-check", action="store_true", help="sans validation ni essai chez un ami fictif")
    s = cmd("self-update", cmd_selfupdate, "déployer le code (brain.py, brainkit/, tests/, skills métier) de l'arbre "
            "de développement vers ~/.claude/brain : sauvegarde, vérifie, revient en arrière si besoin — jamais les "
            "données (souvenirs, config…)", ["autodeploy", "deploy", "maj-code"])
    s.add_argument("source", nargs="?", help="dossier de l'arbre de développement (retenu ensuite)")
    s.add_argument("--force", action="store_true", help="déployer même une version plus ancienne, identique, ou qui retire des fichiers")
    s.add_argument("--no-verify", action="store_true", help="ne pas lancer la suite de tests après la copie")
    s.add_argument("--dry-run", action="store_true", help="montrer ce qui serait fait, sans rien toucher")
    return p


def main(argv=None):
    setup_io()
    if os.environ.get("BRAIN_TASK") == "1" and not BRAIN_DIR.is_dir():
        return 0  # tâche de fond d'un cerveau effacé depuis son lancement (dossier de test) : surtout ne pas le recréer
    if os.environ.get("BRAIN_BG") == "1":  # tâche de fond lancée par un hook : CPU/disque/mémoire en priorité basse
        try:
            from . import pc
            pc.background_mode()
        except Exception as exc:
            log(f"mode arrière-plan : {exc!r}")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    from .store import ReadOnly
    from .wikistore import WikiMissing
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        return 130
    except LockBusy as exc:
        die(f"{exc} — une autre session écrit dans le cerveau, réessaie.")
    except WikiMissing as exc:  # wiki débranché ou déplacé : rien n'est écrit, le cache reste lisible
        die(str(exc))
    except ReadOnly as exc:  # page d'un ami (cerveau commun)
        die(str(exc))
    except RuntimeError as exc:  # graph.json illisible et rien pour le réparer… : un message, pas une trace Python
        die(f"{exc} — `brain doctor` pour le diagnostic, `brain history` pour revenir à un instantané.")
    except OSError as exc:  # dossier en lecture seule, disque plein, fichier ouvert ailleurs… ou réseau coupé
        net = network_reason(exc)
        if net:
            die(f"connexion impossible : {net} — vérifie le réseau (proxy, pare-feu), puis réessaie")
        where = exc.filename or "un fichier du cerveau"
        why = oserror_fr(exc).split(" : ", 1)[-1] if exc.filename else oserror_fr(exc)
        die(f"accès impossible à {where} ({why}) — vérifie que le dossier du cerveau n'est ni en "
            "lecture seule ni plein, puis réessaie ; `brain doctor` pour le diagnostic.")
    except Exception as exc:  # jamais une trace Python : le détail va au journal (BRAIN_DEBUG=1 : la trace, pour déboguer)
        if os.environ.get("BRAIN_DEBUG") == "1":
            raise
        import traceback
        log(f"commande {getattr(args, 'cmd', '?')} : {exc!r}\n{traceback.format_exc()}")
        die(f"erreur inattendue dans `brain {getattr(args, 'cmd', '')}` ({type(exc).__name__} : {short(str(exc), 160)}) — "
            f"rien d'autre n'a été touché ; détail dans {LOG_FILE} ; `brain doctor` pour le diagnostic.")

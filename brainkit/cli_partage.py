"""Commandes du partage et de la veille : wiki, cerveau commun, échange de skills, boutiques, veille automatique,
import de la mémoire native.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import os
import sys

from .cli_commun import die, node_line, refresh_views
from .common import fold, now_iso
from .store import Brain


def cmd_echange(a):
    """Échange de skills et d'outils avec les amis (cerveau commun), et promotion vers le plugin."""
    from . import echange
    act, args = fold(a.action or "etat"), list(a.args)
    said = []

    def say(text):  # ce que la commande dit : un « ✗ » en tête est un échec (sortie 1)
        said.append(str(text))
        print(text)

    def need(usage):
        if not args:
            die(f"usage : brain echange {usage}")
        return args[0]

    if act in ("etat", "status"):
        say(echange.status())
    elif act in ("apercu", "preview"):
        say(echange.preview())
    elif act in ("oui", "non"):
        say("\n".join(echange.consent(act)))
    elif act == "recevoir":
        say(echange.set_receiving(fold(need("recevoir oui|non"))))
    elif act == "declencheurs":
        if fold(need("declencheurs oui|non")) == "non":
            say(echange.drop_triggers())
        else:
            say(echange.allow_triggers())
    elif act in ("liste", "list"):
        say(echange.listing())
    elif act == "voir":
        say(echange.show(need("voir <ami/nom>")))
    elif act == "partager":
        say(echange.share(need("partager <nom> [--non]"), on=not a.non))
    elif act == "garder":
        say(echange.keep(need("garder <nom> [--non]"), on=not a.non))
    elif act == "proposer":
        say(echange.propose(need("proposer <nom> [--non]"), on=not a.non))
    elif act == "adopter":
        say("\n".join(echange.adopt(need("adopter <ami/nom> [--oui] [--scripts]"), oui=a.oui, scripts=a.scripts,
                                    sig=a.empreinte)))
    elif act == "approuver":
        say("\n".join(echange.approve(need("approuver <ami/nom> [--oui]"), oui=a.oui, sig=a.empreinte)))
    elif act == "propositions":
        rows = echange.proposals()
        say(f"Skills du cerveau commun candidates au plugin ({len(rows)}) :" if rows else
            "Aucune skill du cerveau commun n'est candidate au plugin pour l'instant (proposée par son auteur, ou suivie "
            "par 2 membres ou 3 fois).")
        for r in rows:
            why = "proposée par son auteur" if r["propose"] else f"suivie {r['suivies']} fois par {r['membres']} membre(s)"
            say(f"- {r['ref']} — {why} · contrôle : {r['etat']}"
                + (f"\n    son auteur la décrit ainsi : « {echange.quote(r['resume'], 160)} »" if r["resume"] else ""))
        if rows:
            say("→ `brain echange promouvoir <ami/nom> --vers <arbre de développement>` (après l'avoir relue)")
    elif act == "promouvoir":
        say("\n".join(echange.promote(need("promouvoir <ami/nom> [--vers dossier] [--force]"), dest=a.vers, force=a.force)))
    elif act in ("retours", "feedback"):
        say(echange.feedback_all())
    elif act in ("sync", "synchro"):
        say("\n".join(echange.sync(auto=a.auto)))
    elif act == "index":  # tâche de fond lancée par les hooks quand l'index des skills reçues est périmé
        idx = echange.index(build=True)
        say(f"✓ index des skills reçues : {len(idx.get('skills') or [])} skill(s) contrôlée(s)")
    else:
        die("action inconnue : " + str(a.action) + " — etat, apercu, oui, non, recevoir, liste, voir, partager, garder, "
            "proposer, adopter, approuver, declencheurs, propositions, promouvoir, retours, sync")
    first = next((x.strip() for x in "\n".join(said).splitlines() if x.strip()), "")
    return 1 if first.startswith("✗") else 0


def cmd_wiki(a):
    """Le cerveau en wiki (« LLM Wiki ») : squelette et migration, sources, index, journal, santé, synchronisation."""
    from . import wiki, wikistore as ws
    act = fold(a.action or "status")
    if act == "init":
        if not a.args:
            die("dossier du wiki manquant : brain wiki init <dossier> (idéalement le clone d'un dépôt GitHub privé)")
        try:
            for line in wiki.init(a.args[0], migrate=not a.no_migrate, push=not a.no_push):
                print(line)
        except RuntimeError as exc:
            die(str(exc))
        refresh_views()
        return
    if act in ("status", "etat"):
        print(wiki.status())
        return
    if act in ("schema", "schéma"):
        print(wiki.schema_text())
        return
    root = ws.root()
    if not root:
        die("pas de wiki : `brain wiki init <dossier>` (le cerveau y migre ses souvenirs)"
            if ws.resolve()[0] == "classic" else f"wiki introuvable : {ws.resolve()[1]}")
    if act in ("add", "ingest", "ajoute", "ingere"):
        src = a.args[0] if a.args else "-"
        text = sys.stdin.read() if src == "-" else None
        if src == "-" and not (text or "").strip():
            die("rien reçu sur l'entrée standard (texte de la source) — ou : brain wiki add <fichier|url>")
        try:
            info = wiki.add_source(src, title=a.title, fmt=a.format, url=a.url, author=a.author, text=text,
                                   allow_local=getattr(a, "local", False))
        except RuntimeError as exc:
            die(str(exc))
        print(wiki.ingest_plan(info))
        wiki.write_index()
    elif act in ("pending", "attente"):
        b = Brain.load()
        items = wiki.pending(b.data, root)
        if not items:
            print("✓ aucune source en attente")
        for p in items[: a.n]:
            print(f"- {p['raw']} — page « {p['page']['title']} » à remplir" if p["page"]
                  else f"- {p['raw']} — `brain wiki add {p['raw']}`")
        if len(items) > a.n:
            print(f"- … +{len(items) - a.n}")
    elif act == "lint":
        b = Brain.load()
        rep = wiki.lint(b, root, limit=a.n)
        print(wiki.lint_text(rep))
        wiki.write_index(b, root)
        if a.log:
            wiki.log_append("lint", f"{sum(len(v) for v in rep.values())} point(s)",
                            [f"{k} : {len(v)}" for k, v in rep.items()], root=root)
    elif act == "index":
        print("✓ index.md régénéré" if wiki.write_index() else "✓ index.md déjà à jour")
    elif act in ("log", "journal"):
        if not a.args:
            rows = wiki.log_entries(root, a.n)
            print("\n".join(rows) if rows else "(journal vide)")
            return
        try:
            head = wiki.log_append(a.args[0], a.args[1] if len(a.args) > 1 else "", a.args[2:], root=root)
        except (RuntimeError, TimeoutError) as exc:
            die(str(exc))
        wiki.write_index()
        print(f"✓ {head}")
    elif act in ("sync", "synchro"):
        lines = wiki.sync(root, push=not a.no_push, pull=not a.no_pull, auto=a.auto)
        for line in lines:
            print(line)
        if a.auto and not a.no_pull:
            wiki.mark_pulled()
        if any(line.startswith("✗") for line in lines):
            sys.exit(1)  # une étape ratée : la veille (`brain auto`) l'affiche ✗, jamais ✓
    elif act == "obsidian":
        from . import obsidian
        made = obsidian.setup(root, force=True)
        b = Brain.load()
        made += [f for f, ok in ((obsidian.STATUS, obsidian.write_status(b, root)),
                                 (obsidian.CARD, obsidian.write_canvas(b, root))) if ok]
        print("\n".join(f"✓ {m}" for m in made) + "\n→ redémarre Obsidian s'il est ouvert" if made
              else "✓ coffre Obsidian déjà réglé (rien ne manquait)")
    elif act in ("capture", "capturer"):
        from . import obsidian
        print("\n".join(obsidian.capture(root)) or "· rien à mémoriser dans les notes du jour")
    else:
        die(f"action inconnue : {a.action} — init, add, pending, lint, index, log, status, sync, schema, obsidian, "
            "capture")


def cmd_auto(a):
    """Veille automatique : une passe sans session de Claude, ou la tâche planifiée qui en lance une toutes les 30 min."""
    from . import auto
    lines = (auto.install(dry=a.dry_run) if a.installer else auto.uninstall() if a.retirer
             else (auto.heal() or ["✓ veille saine (ou jamais posée, ou retirée exprès)"]) if a.reparer
             else auto.state_lines() if a.etat else auto.main())
    if lines:
        print("\n".join(lines))


def cmd_boutique(a):
    """Boutiques en ligne suivies par le cerveau : fiche, plan daté, indicateurs de la semaine, audits, bilan."""
    from . import boutique
    act = fold(a.action or "liste")
    args = list(a.args or [])
    try:
        if act in ("liste", "list", "etat", "status"):
            lines = boutique.liste()
        elif act in ("ajouter", "add", "nouvelle", "creer"):
            if not args:
                die("nom manquant : brain boutique ajouter \"Nom\" [--url …] [--type …] [--chemin plateforme|0euro]")
            lines = boutique.ajouter(" ".join(args), url=a.url, plateforme=a.plateforme, chemin=a.chemin, type_=a.type,
                                     marge_commande=a.marge_commande)
        elif act in ("plan", "planifier"):
            lines = boutique.plan(args[0] if args else None, debut=a.debut, type_=a.type, court=a.court, force=a.force)
        elif act in ("kpi", "releve", "semaine", "chiffres"):
            lines = boutique.kpi(args[0] if args else None, sessions=a.sessions, ajouts=a.ajouts, commandes=a.commandes,
                                 ca=a.ca, checkouts=a.checkouts, heures=a.heures, marge=a.marge, canaux=a.canal or (),
                                 semaine=a.semaine, note=a.note)
        elif act in ("audit", "auditer"):
            pages = 10 if a.complet and not a.pages else (a.pages or 0)
            lines = boutique.audit(args[0] if args else None, timeout=a.timeout, legal=a.conformite or a.complet,
                                   pages=pages, vitesse=a.vitesse or a.complet, rapport=a.rapport)
        elif act in ("bilan", "revue", "point"):
            lines = boutique.bilan(args[0] if args else None, semaines=a.semaines, md=a.md)
        elif act in ("panel", "panels", "simulation", "simuler"):
            lines = boutique.panel(args[0] if args else None, importer=a.importer, applique=a.applique,
                                   variante=a.variante, le=a.le)
        elif act in ("regler", "reglage", "set"):
            if len(args) < 2:
                die("brain boutique regler <boutique> cle=valeur … (url, plateforme, nom, chemin, type, marge, "
                    "seuil.sessions|ajout|paiement|panier_commande)")
            lines = boutique.regler(args[0], args[1:])
        else:
            die(f"action inconnue : {a.action} (liste, ajouter, plan, kpi, audit, bilan, panel, regler)")
    except (LookupError, ValueError, RuntimeError) as exc:
        die(str(exc))
    for line in lines:
        print(line)
    if act in ("ajouter", "add", "nouvelle", "creer", "plan", "planifier"):
        refresh_views()


def cmd_commun(a):
    """Le cerveau commun : ce que chacun apprend nourrit le cerveau de tous, sans rien de privé."""
    from . import commun
    act = fold(a.action or "etat")
    try:
        if act in ("etat", "status"):
            print(commun.status())
        elif act in ("apercu", "preview"):
            print(commun.apercu_text(Brain.load()))
        elif act in ("rejoindre", "join"):
            for line in commun.join(nom=a.nom, oui=a.oui):
                print(line)
        elif act in ("non", "refuser", "decline"):
            print(commun.decline())
        elif act in ("quitter", "leave"):
            for line in commun.leave(keep=a.garder):
                print(line)
        elif act == "projet":
            if not a.args:
                die("projet manquant : brain commun projet <id> [--non]")
            print(commun.set_project(a.args[0], share=not a.non))
        elif act in ("sync", "synchro"):
            if a.delai and os.environ.get("BRAIN_COMMUN_FG") != "1":
                import time
                time.sleep(min(float(a.delai), 600))  # envoi différé (après un ajout) : les ajouts suivants partent avec
            for line in commun.sync(pull=True, push=not a.no_push, auto=a.auto):
                print(line)
        elif act in ("verifier", "check"):  # accès au dépôt commun (lancé en arrière-plan au démarrage)
            ok = commun.check_access(commun.repo_url(commun.settings().get("repo")))
            commun.save_state(access=ok, access_checked=now_iso())
            print("✓ accès au cerveau commun" if ok else "· pas (encore) d'accès au cerveau commun")
        elif act in ("liste", "list"):
            b = Brain.load()
            mine = [n for n in commun.preview(b)["shared"]]
            print(f"Ce que tu partages ({len(mine)}) :")
            for n in sorted(mine, key=lambda n: n["title"]):
                print(f"- {node_line(n, 80)}")
        else:
            die(f"action inconnue : {a.action} — etat, apercu, rejoindre, non, quitter, projet, sync, liste")
    except RuntimeError as exc:
        die(str(exc))


def cmd_import(a):
    from . import importer
    big, max_kb = [], importer.MAX_KB if a.max_ko is None else a.max_ko
    rep = importer.sync(force=a.force, dry=a.dry_run, max_kb=max_kb, skipped=big)
    for path, size in big:
        print(f"⚠ ignoré, fichier de {round(size / 1024)} Ko (plus de {max_kb} Ko) : {path} — "
              f"pour l'importer quand même : `brain import --max-ko 0`")
    if not rep and not big:
        print("✓ mémoire native déjà synchronisée")
    for item in rep:
        print("- " + " ".join(str(x) for x in item))
    if rep and not a.dry_run:
        refresh_views()

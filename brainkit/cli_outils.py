"""Commandes des outils et de la consommation : banc d'essai, neurone du rappel, tokens, optimisation, mode éco,
délégation, apprentissages, sorties compactes, prompts, skills, connecteurs, PC.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import journal
from .cli_commun import die
from .common import fold, load_config, log, short, update_config
from .store import Brain


def cmd_bench(a):
    from . import bench
    print(bench.run(quick=a.quick))


def cmd_neurone(a):
    from . import neurone
    out = neurone.run_cli(a.action, a.jours, a.quiet)
    if out:
        print(out)


def cmd_tokens(a):
    from . import tokens
    if a.garde:  # garde de consommation (lancée en arrière-plan au démarrage d'une session) + page Cerveau d'Obsidian
        g = tokens.guard()
        try:
            from . import obsidian
            b = Brain.load()
            obsidian.write_status(b, (b.data.get("wiki") or {}).get("root"))
        except Exception as exc:
            log(f"garde : page Cerveau : {exc!r}")
        cfg = {"garde": g}
        print("\n".join([tokens.guard_notice(cfg) or "✓ aucune session ne mange la journée", ""] + tokens.guard_lines(cfg)))
        return
    print(tokens.report(a.hours))


def cmd_optimize(a):
    from . import optimize
    if a.apply:
        print(optimize.apply())
    else:
        print(optimize.report(a.hours, show_all=a.all))


def cmd_eco(a):
    from . import eco
    code, text = eco.run(a.appliquer, a.annuler, a.forcer, a.sortie, a.fenetre, a.desactiver, a.plugins_auto,
                         a.poser, a.retirer, a.cache, a.refuser, a.rendre, a.plugins)
    print(text)
    return code


def cmd_delegation(a):
    """Délégation aux modèles moins chers : état, mode, modèle d'un agent."""
    from . import delegation
    lines = []
    if a.mode:
        lines.append(delegation.set_mode(a.mode))
    for spec in a.modele or []:
        lines.append(delegation.set_model(spec))
    print("\n".join(lines) if lines else delegation.report(a.jours))
    return 1 if any(x.startswith("✗") for x in lines) else 0


def cmd_apprendre(a):
    """Apprentissage : dossier à trancher, skill apprise, déclencheur à oublier, retours techniques."""
    from . import apprendre
    act, args = fold(a.action or ""), list(a.args)
    if a.entretien:
        print(apprendre.upkeep())
    elif a.fait:
        print(apprendre.done())
    elif act in ("", "dossier"):
        text, n = apprendre.dossier()
        apprendre._edit(lambda d: d.update(attente=n))
        print(text)
    elif act in ("etat", "status"):
        print(apprendre.status())
    elif act == "skill":
        if len(args) != 1:
            die('usage : brain apprendre skill <nom> -d "À utiliser quand… « déclencheur »… Ne pas utiliser pour…" '
                '[-b "corps" | --body-file fichier] [--script outil.py …] [--force]')
        # utf-8-sig : un fichier écrit par le Bloc-notes ou PowerShell commence par une marque d'encodage, à ne pas garder
        body = Path(a.body_file).read_text(encoding="utf-8-sig") if a.body_file else (a.body or "")
        try:
            for line in apprendre.learned_skill(args[0], a.description, body, force=a.force, scripts=a.script or ()):
                print(line)
        except (ValueError, FileExistsError, OSError) as exc:
            die(str(exc))
    elif act == "oublier":
        if len(args) != 2:
            die('usage : brain apprendre oublier <skill> "déclencheur"')
        trig = (load_config().get("skills") or {}).get("triggers") or {}
        if args[0] not in trig:  # ni déclencheur ajouté, ni skill connue : une faute dans le nom, rien à noter
            from . import skills
            names = {s["name"] for s in skills.index(os.getcwd(), load_config().get("skills") or {})}
            if args[0] not in names:
                import difflib
                near = difflib.get_close_matches(args[0], sorted(names), n=3, cutoff=0.6)
                die(f"skill inconnue : {args[0]}" + (f" — voulais-tu : {', '.join(near)} ?" if near else
                                                     " (liste : `brain skill ls`)") + " ; rien n'est noté")
        print(apprendre.forget(args[0], args[1]))
    elif act in ("retours", "feedback"):
        print(apprendre.feedback_text(a.jours))
    else:
        die("action inconnue : " + str(a.action) + " — (rien : le dossier), etat, skill, oublier, retours ; --fait pour clore")


def cmd_compact(a):
    from . import compact
    if a.decouvrir:
        print(compact.discover_text())
        return 0
    if a.apprendre:
        text = compact.learn_text(a.apprendre, [a.fichier] if a.fichier not in (None, "-") else (), a.enregistrer)
        if text.startswith("Aucune sortie"):  # rien à apprendre : la commande n'a rien pu faire
            die(text)
        print(text)
        return 0
    if a.oublier:
        print(compact.forget_filter(a.oublier))
        return 0
    if a.stats or not (a.fichier or a.cmd):
        print(compact.stats_text())
        return 0
    if not a.cmd:
        die("donne la commande qui a produit la sortie : --cmd \"npm install\" (elle choisit les règles)")
    text = sys.stdin.read() if a.fichier in (None, "-") else Path(a.fichier).read_text(encoding="utf-8", errors="replace")
    cfg = dict(load_config().get("compact") or {}, min_chars=0, min_gain=0, min_saved=0)
    if not compact.kind_of(a.cmd, text, cfg):
        print(f"« {a.cmd} » : commande non reconnue comme bavarde (ni filtre perso, ni JSON) — sa sortie resterait telle "
              "quelle.")
        return 0
    done = compact.compact_output(a.cmd, text, "", cfg)
    print(done[0] if done else text)
    return 0


def cmd_prompts(a):
    from . import promptlib
    words = list(a.query)
    if a.hook:
        found = promptlib.suggest(a.hook, {**load_config().get("promptlib", {}), "timeout": 10})
        print("\n".join([promptlib.HEADER] + [promptlib.line(p) for p in found]) if found
              else "Rien d'injecté pour ce message (pas une demande de prompt/contenu, ou rien d'assez proche).")
    elif words[:1] == ["get"] and len(words) == 2:
        print(promptlib.show(words[1]))
    elif words:
        text = promptlib.report(" ".join(words), skills=a.skills, n=a.n)
        print(text)
        return 1 if text.startswith("✗") else 0
    else:
        die('usage : brain prompts "sujet" | brain prompts get <id> | brain prompts --hook "message"')


def cmd_skill(a):
    from . import skills
    cwd, kc = os.getcwd(), load_config().get("skills", {})
    act, args = (a.action or "ls"), list(a.args)
    exclude = set(kc.get("exclude", []))
    if act in ("ls", "list"):
        cat, stats = skills.index(cwd, kc), skills.load_stats()
        if not cat:
            print(f"Aucune skill perso dans {skills.SKILLS_DIR}.")
        others = {}  # autres plugins et compte claude.ai : une ligne chacun, détail sur demande (`skill ls <plugin>`)
        for s in cat:
            src = s.get("plugin") or ""
            if src and src != skills.OWN_PLUGIN and src not in args and "tout" not in args:
                others.setdefault(src, []).append(s)
                continue
            n = stats.get(s["name"], {})
            src = (f" (plugin {s['plugin']}" + (", écartée du réflexe)" if s["name"] in exclude else ")")
                   if s.get("plugin") else "")
            print(f"- {s['name']}{src} — {len(s['triggers'])} déclencheur(s) · soufflée {n.get('hinted', 0)} fois · "
                  f"chargée {n.get('used', 0)} fois (dont {n.get('used_after_hint', 0)} juste après)")
            print(f"    {short(s['description'], 170)}")
        for src, group in sorted(others.items()):
            ncmd = sum(1 for s in group if s.get("kind") == "cmd")
            names = ", ".join(s["name"].partition(":")[2] for s in group[:10]) + (" …" if len(group) > 10 else "")
            print(f"- {src} : {len(group) - ncmd} skill(s)" + (f" + {ncmd} commande(s)" if ncmd else "") + f" — {names}")
        if others:
            print("Détail : `brain skill ls <plugin>` (ou `tout`).")
    elif act == "trig":
        if not args:
            die('usage : brain skill trig <nom> ["déclencheur" …] [--force : remplacer la liste ; seul, la vider]')
        name, phrases = args[0], [p.strip() for p in args[1:] if p.strip()]
        names = {s["name"] for s in skills.index(cwd, kc)}
        if name not in names:
            near = sorted(n for n in names if name in n)[:5]
            die(f"skill inconnue : {name}" + (f" — voulais-tu : {', '.join(near)} ?" if near else " (liste : `brain skill ls`)"))
        if phrases or a.force:
            def change(cfg):
                trig = cfg.setdefault("skills", {}).setdefault("triggers", {})
                cur = [] if a.force else list(trig.get(name, []))
                cur += [p for p in phrases if p not in cur]
                if cur:
                    trig[name] = cur
                else:
                    trig.pop(name, None)
            update_config(change)
            kc = load_config().get("skills", {})
        got = (kc.get("triggers") or {}).get(name, [])
        print(f"{name} : " + (" · ".join(f"« {p} »" for p in got) if got else "aucun déclencheur ajouté"))
        for lvl, n, m in skills.check(skills.index(cwd, kc), exclude=exclude, only={name}):
            print(f"  {lvl} {m}")
    elif act == "test":
        msg = " ".join(args) or die('usage : brain skill test "message tel que tu le taperais"')
        cat = skills.index(cwd, kc)
        found = skills.match(journal.clean_prompt(msg, 2000), cat, exclude=exclude, min_score=kc.get("min_score", 4.0))
        for r in found[:3]:
            print(skills.hint_line(r) + f"   [score {r['score']}]")
        pl = skills.paste_line(msg, {**kc, "paste": kc.get("paste") if kc.get("paste") != "off" else "propose"}, cat)
        if pl:
            print(pl)
        if not found and not pl:
            print("Aucune skill ne se déclencherait sur ce message.")
    elif act == "check":
        probs = skills.check(skills.index(cwd, kc), exclude=exclude)
        for lvl, n, m in probs:
            print(f"{lvl} {n} : {m}")
        if not any(lvl != "ℹ️" for lvl, _, _ in probs):
            print("✓ skills perso bien formées : chacune se déclenche sur ses propres mots.")
    elif act == "new":
        if len(args) != 1:
            die('usage : brain skill new <nom> -d "À utiliser quand… « déclencheur »… Ne pas utiliser pour…" '
                "[-b \"corps\" | --body-file fichier] [--force] [--no-memory]")
        body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else (a.body or "")
        try:
            path = skills.scaffold(args[0], a.description, body, force=a.force)
        except (ValueError, FileExistsError, OSError) as exc:
            die(str(exc))
        name = path.parent.name
        print(f"✓ skill créée : {path}")
        for lvl, n, m in skills.check(skills.index(cwd), only={name}):
            print(f"  {lvl} {m}")
        if not a.no_memory:
            with Brain.edit() as b:
                node = b.add("reference", f"Skill perso « {name} »",
                             f"{' '.join(a.description.split())} Fichier : {path}. Se déclenche seule (réflexe de "
                             "skills du cerveau) ; tester : `brain skill test \"…\"`.", tags=["skill", name])
            print(f"✓ fiche dans le cerveau : `{node['id']}`")
    else:
        die("usage : brain skill [ls | test \"message\" | check | new <nom> -d \"…\" | trig <nom> \"déclencheur\" …]")


def cmd_outils(a):
    import time
    from . import outils
    from .skills import phrase_groups
    oc = load_config().get("outils", {})
    act, args = (a.action or "ls"), list(a.args)
    reg, fresh = outils.load(), oc.get("fresh_days", outils.FRESH_DAYS)
    servers = {k: s for k, s in reg["servers"].items() if not outils.SKIP_RE.match(k)}
    if act in ("ls", "list"):
        if not servers:
            print("Aucun connecteur connu : la liste se remplit seule en fin de tour (tout de suite : `brain outils scan`).")
            return
        locked = []
        for key, s in sorted(servers.items(), key=lambda kv: (not outils.alive(kv[1], None, fresh), -kv[1].get("seen", 0))):
            state = outils.status(s, fresh_days=fresh)
            if state.startswith("🔒"):
                locked.append(outils.short_name(key, s))
                continue
            tools, n, ref = s.get("tools") or [], len(outils.phrases_of(key, s, oc)), outils.ref_of(key, s, servers)
            if not state.startswith("✅"):
                print(f"- {state} {outils.short_name(key, s)} · {len(tools)} outil(s)"
                      + (f" · vu branché le {outils.date_of(s['seen'])}" if s.get("seen") else ""))
                continue
            print(f"- {state} {outils.short_name(key, s)} · `{ref}` · {len(tools)} outil(s) · "
                  + (f"{n} phrase(s)" if n else f"aucune phrase ({outils.few(tools, 3)}) : `brain outils trig {ref} \"…\"`"))
        if locked:
            print(f"- 🔒 {len(locked)} à authentifier (/mcp, par l'utilisateur lui-même) : {outils.few(sorted(locked), 8)}")
        print("Phrases d'un connecteur : `brain outils trig <nom>` · essai : `brain outils test \"message\"`.")
    elif act == "trig":
        if not args:
            die('usage : brain outils trig <connecteur> ["phrase" …] [--force : remplacer la liste ; seul, la vider]')
        try:
            ck, s = outils.resolve(args[0], reg)
        except ValueError as exc:
            die(str(exc))
        phrases = [p.strip() for p in args[1:] if p.strip()]
        if phrases or a.force:
            def change(cfg):
                trig = cfg.setdefault("outils", {}).setdefault("triggers", {})
                cur = [] if a.force else list(trig.get(ck, []))
                cur += [p for p in phrases if p not in cur]
                if cur:
                    trig[ck] = cur
                else:
                    trig.pop(ck, None)
            update_config(change)
            oc = load_config().get("outils", {})
        got = (oc.get("triggers") or {}).get(ck, [])
        print(f"{ck} : " + (" · ".join(f"« {p} »" for p in got) if got else "aucune phrase ajoutée"))
        e = outils.BY_ID.get(ck) or {}
        base = outils.phrases_of(ck, s, {}) if s else list(e.get("trig", ())) + list(e.get("exact", ()))
        if base:
            print(f"  + {len(base)} par défaut : {outils.few(base, 6)}")
        for p in got:
            g = phrase_groups(p)
            if not g:
                print(f"  ⚠️ « {p} » : que des mots vides, ignorée (mets un nom ou un verbe distinctif)")
            elif len(g) == 1 and all(len(k[0]) < 5 for k in g[0]):
                print(f"  ℹ️ « {p} » : un seul mot court, se déclenchera souvent")
        if not s:
            print("  (pas encore vu branché : le réflexe le proposera dès qu'il le sera)")
    elif act == "test":
        msg = " ".join(args) or die('usage : brain outils test "message tel que tu le taperais"')
        found = outils.match(journal.clean_prompt(msg, 2000), oc, reg=reg)
        for r in found[:3]:
            print(outils.hint_line(r))
        if not found:
            print("Aucun connecteur branché ne se déclencherait sur ce message.")
    elif act == "scan":
        if args and not (args[0].isdigit() and int(args[0]) > 0):
            die(f"nombre de transcripts à relire : entier d'au moins 1, pas « {args[0]} » (ex. `brain outils scan 5`)")
        n = int(args[0]) if args else 5
        paths, t0 = outils.recent_transcripts(n), time.perf_counter()
        reg = outils.bootstrap(paths)
        live = [k for k, s in reg["servers"].items() if not outils.SKIP_RE.match(k) and outils.alive(s, None, fresh)]
        print(f"✓ {len(paths)} transcript(s) relu(s) en {time.perf_counter() - t0:.1f} s : {len(live)} connecteur(s) "
              "branché(s) — détail : `brain outils`")
    else:
        die('usage : brain outils [ls | test "message" | trig <connecteur> "phrase" … | scan [n]]')


def cmd_pc(a):
    if os.name != "nt" and a.history is None:  # mesure et nettoyage passent par l'API de Windows (ctypes.WinDLL)
        print("· `brain pc` mesure et nettoie un PC Windows : rien à faire sur ce système (`brain pc --history` "
              "reste lisible).")
        return 0
    from . import pc
    if a.clean or a.oui:
        print(pc.clean(oui=a.oui))
    elif a.history is not None:
        print(pc.history(a.history))
    else:
        print(pc.report(a.seconds, show_all=a.all))

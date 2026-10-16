"""Installation / réparation / désinstallation : bloc CLAUDE.md global, skill /brain, hooks dans settings.json.

Idempotent : relancer `brain install` remplace proprement les éléments du cerveau sans toucher au reste."""
from __future__ import annotations

import json
import os
import shutil
import sys

from .common import BRAIN_PY, CLAUDE_HOME, CMD, write_json, write_text

START, END = "<!-- BRAIN:START", "<!-- BRAIN:END -->"

CLAUDE_BLOCK = f"""<!-- BRAIN:START (géré par ~/.claude/brain — `brain install` le réécrit ; ne pas éditer entre ces balises) -->
# 🧠 Cerveau persistant (`~/.claude/brain`)
Injecté tout seul : index + fiche du projet au démarrage, souvenirs/fichiers pertinents à chaque message (blocs 🧠/📁).
S'en servir AVANT d'explorer ou de redemander. Outil : `{CMD} <cmd>` (Bash/PowerShell) — détail : skill `/brain`.
`q "sujet"` · `add -t <type> -T "titre" -b "fait + pourquoi + comment"` · `edit`/`show <id>` · `todo` · `files`/`where`/`explain <x>` · `map .`
1. Projet : carte (MAP.md) et `files`/`where`/`explain` avant tout Glob/Grep/Read en masse ; pas de carte → `map .`.
2. Mémoriser aussitôt le durable — feedback (préférence, correction), user, decision, fact (travail en cours),
   learning (piège, solution), reference, todo (`--due`) — après un `q` anti-doublon.
3. Jamais : secrets, mots de passe, paiement, santé ou vie privée de tiers, ce que le code ou git disent déjà.
4. Fait qui change → `add … --replaces <id>` ; erreur → `edit`/`rm` ; vérifier un souvenir ancien avant d'agir.
Tokens : filtrer les sorties Bash (`| tail -n 30`, `grep -c`, `-q`) ; gros fichier → `explain`/Grep puis Read offset/limit ; web : get_page_text/find plutôt que read_page entier ou capture ; sous-agent (repart de ~90 k) seulement pour une très large recherche ; pas de relecture ; réponses courtes, résultat vérifié.
<!-- BRAIN:END -->
"""

SKILL = f"""---
name: brain
description: Cerveau persistant de Claude : mémoire en graphe datée (souvenirs, concepts, liens), cartes de projets, à-faire, historique, coffre Obsidian, MCP, vue 3D. Pour retrouver ou mémoriser un souvenir, trouver un fichier ou un symbole sans explorer, reprendre une session, ou quand l'utilisateur dit « souviens-toi », « retiens », « cerveau », « /brain ».
---

# 🧠 Cerveau — référence

Commande : `{CMD} <commande>` (fonctionne dans Bash et PowerShell). Sortie compacte, pensée pour économiser les tokens.

## Ce qui se passe tout seul (hooks)
- **Démarrage de session** : index du cerveau + fiche du projet courant (souvenirs, 3 dernières sessions, fin de la
  dernière session, résumé de carte) injectés ; dans un projet, l'index global se resserre sur ce qui s'y rapporte ;
  les à-faire dont l'échéance approche (ou est dépassée) passent en tête (« ⏰ Échéances »). Dossier de projet inconnu → enregistré et cartographié en arrière-plan.
- **Chaque message** : rappel automatique des souvenirs/fichiers vraiment liés (filtre anti-bruit, jamais deux fois) ;
  la recherche tolère fautes, écriture phonétique et synonymes FR/EN (« boutik », « shopfy », « rdv » → agenda).
- **Fin de tâche importante** : rappel unique de noter 3 à 5 **observations datées** de la session (`obs "🔴 …" "🟡 …"`)
  et de mémoriser l'essentiel, avec les phrases de l'utilisateur qui ressemblent à une préférence ou une décision
  (« Candidats repérés… ») : juger, puis `add` ce qui est durable. Après une **compaction** du contexte, le Stop suivant
  demande les observations de la session (le détail n'est plus que résumé).
- **Usage réel** : un souvenir montré dont les termes ou les chiffres reviennent dans ta réponse ou tes commandes
  compte comme *utilisé* (montré ≠ utilisé) ; le classement de l'index en tient compte.
- **Fin de session** : journal, vue 3D, et une fois par jour consolidation prudente (doublons évidents, souvenirs
  remplacés via `supersedes`, secrets) puis **rêve** (dates relatives rendues absolues, observations de plus de 7 jours
  condensées en un résumé par semaine et par projet, dossier `REVE.md` des points à trancher ; s'il y en a assez, une
  ligne 🌙 au démarrage propose de le confier à un sous-agent en arrière-plan :
  `dream` → appliquer ce qui est sûr → `dream --done`), avec instantané pris avant, et sauvegarde hors du disque système
  (`D:\\Sauvegardes-cerveau-Claude` par défaut : une réinstallation de Windows n'efface plus le cerveau).
- **Auto-réparation** : si graph.json est illisible, le cerveau repart du dernier instantané valide (ou de la
  dernière sauvegarde) et garde le fichier abîmé à côté ; jamais d'écrasement par un graphe vide.
- **Sécurité** : clés, jetons et mots de passe sont masqués automatiquement à l'écriture ; chaque modification
  peut être annulée (`history` / `restore`).
- La mémoire native de Claude Code (`~/.claude/projects/*/memory`) est importée automatiquement.

## Mémoire
| But | Commande |
|---|---|
| Chercher (souvenirs + voisins du graphe + sessions passées + fichiers du projet) | `q "mots clés" [-p projet] [-t type] [--only] [--no-graph]` — comprend les dates (« hier », « le 12/11 », « il y a 3 semaines ») et le deuxième saut (« ← lien (sato) » : souvenir relié par un nom propre) ; « ≈ à vérifier » = confiance basse |
| Mémoriser | `add -t <type> -T "titre court" -b "fait + pourquoi + comment appliquer" [--tags a,b] [-i 1-5] [-p .\\|none\\|id] [--link id] [--due 10/11] [--replaces id] [--keys "synonymes, questions"] [--src utilisateur\\|verifie\\|deduit]` (étiquettes auto si absentes, liens suggérés affichés ; « hier », « dans 2 semaines » deviennent des dates réelles) |
| Question large (« où en est la boutique ? », « le point sur… ») | `q` place d'abord la **fiche de synthèse** de la communauté dominante (phrases les plus centrales de ses souvenirs, à-faire, ids), puis les souvenirs qu'elle ne cite pas · `fiche` liste les fiches · `fiche <n°\\|mot\\|id>` |
| Observations datées de la session (mémoire épisodique, façon Mastra) | `obs "🔴 décision, blocage" "🟡 avancée" "🟢 détail"` (« 14:20 » en tête au besoin ; « hier » devient une date) · `obs` les dernières · `obs -p projet --days 7` — retrouvées par `q` (texte ou date : « on a fait quoi hier ? »), condensées par le rêve après 7 jours ; jamais injectées au démarrage |
| Fait qui change (façon Zep / mem0) | `add … --replaces <ancien>` ou `supersede <nouveau> <ancien>` : l'ancien est archivé avec sa date de fin, la chaîne reste visible dans `show`. Un `add` sur le même sujet remplace tout seul l'ancien si une valeur change (chiffre, négation, « désormais », autre nom propre) ; jamais quand le titre vise une autre entité ou une autre date ; « ↻ remplace peut-être » = à confirmer |
| Voyage dans le temps | `q "sujet" --at 15/10\\|hier\\|"il y a 3 jours"` (le cerveau tel qu'il était) · `show <id> --history` (versions successives) · `history --diff <n°\\|date>` (ce qui a changé depuis) |
| À-faire et échéances | `todo` (triés par échéance) · `done <id>` · `edit <id> --due "10/11"\\|"demain"\\|"dans 2 semaines"\\|none` |
| Corriger / compléter | `edit <id> [-T …] [-b …] [-a "ajout"] [-i 4] [--add-tags x]` |
| Voir / lister | `show <id>` · `ls [-t type] [-p projet]` |
| Lier | `link <a> <b> [-r relates\\|depends_on\\|fixes\\|supersedes\\|contradicts]` (ou `[[id]]` dans un contenu) · `link --suggest` liens déduits à confirmer |
| Archiver | `rm <id>` (réversible : `edit <id> --unarchive`) · `--purge` = définitif (instantané pris avant) |
| Historique / annuler | `history` (instantanés) · `restore <n°>` (l'état courant est sauvegardé d'abord) |
| Sauvegardes (autre disque) | `backup` · `backup --list` · `backup --restore <archive.zip>` · `backup --to <dossier>` |

Types : `user` (qui est l'utilisateur), `feedback` (règle/préférence/correction), `project` (un dossier), `decision`,
`fact` (état/fait sur un travail en cours), `learning` (piège, solution, astuce), `reference` (lien, doc, ressource),
`entity` (outil, service, contact pro), `todo`.
Projet par défaut = projet du dossier courant (sauf `user`/`feedback`, globaux) ; `-p none` force le global.
Anti-doublon intégré : un `add` quasi identique complète le souvenir existant au lieu d'en créer un autre.

**Bon souvenir** : précis, actionnable, daté si utile. Ex. `add -t learning -T "Stats Shopify polluées par robots" -b "92 %
des sessions sont des bots US : filtrer session_country='France' avant tout calcul de conversion."`
**À ne pas stocker** : secrets, données sensibles ou de tiers, ce que le code/git disent déjà, l'éphémère.

## Ailleurs que dans l'onglet Code
| But | Commande |
|---|---|
| Coffre Obsidian / Markdown, synchronisé dans les deux sens (une note par souvenir, propriétés, liens `[[ ]]`) | `export --vault <dossier>` (dossier retenu ensuite : `export --vault`) — notes modifiées rapatriées champ par champ, nouvelle note dans « À trier » = nouveau souvenir, note supprimée = souvenir archivé, conflit = version Obsidian gardée dans « Conflits » · `--push` écrase le coffre |
| Serveur MCP (chat Claude, Cowork, tout client MCP) : outils memory_search / memory_add / memory_show / memory_todo / memory_context | `mcp` (stdio) · `install --mcp` l'enregistre dans l'app Claude (`--uninstall` le retire) |

## Graphe (façon graphify)
| But | Commande |
|---|---|
| Rapport : communautés, nœuds clés, liens surprenants, liens suggérés, doublons, trous, questions | `report [--print]` (→ `RAPPORT.md`) |
| Chemin entre deux souvenirs (liens explicites d'abord, puis déduits) | `path <id_a> <id_b>` |
| Communauté, centralité, concepts et liens déduits d'un souvenir | `show <id>` |
| Fiche de synthèse d'une communauté (extractive, régénérée seulement quand un membre change) | `fiche [n°\\|mot\\|id]` |
| Concepts repérés (outils, sujets, sigles, domaines, produits) et souvenirs liés | `concept [nom]` |
| Vue 3D interactive (mémoire, concepts, chronologie, Maj+clic = chemin, cartes de projets) | `viz --open` → `cerveau.html` (`cerveau-2d.html` hors ligne) |

Liens **déduits** = similarité du contenu (raison : mots communs ; confiance forte/moyenne/faible), jamais écrits
dans le graphe tant qu'ils ne sont pas confirmés par `link`. Analyse en cache (`state/analysis.json`), recalculée
seulement quand le savoir change.

## Projets (façon graphify)
| But | Commande |
|---|---|
| Cartographier / mettre à jour (incrémental) | `map [dossier] [--full] [--bg]` |
| Fichiers liés à un sujet | `files "paiement panier"` |
| Où est défini X (fonction, classe, variable d'env, route) | `where X` |
| Fiche d'un fichier ou symbole | `explain <fichier\\|symbole>` |
| Dépendances | `deps <fichier>` · chemin entre deux fichiers : `path <a> <b>` |
| Projets connus | `proj` · `proj add <dossier> -T "Nom" -b "description"` |

Carte complète : `~/.claude/brain/projects/<id>/MAP.md` (structure, fichiers clés par centralité, modules, routes,
variables d'env, documents, cycles, TODO, fichiers sensibles jamais lus).

## Entretien
`journal [-p projet]` sessions passées · `journal -s "mots"` chercher dans leur texte · `context` ce qui est injecté ici · `recall "message"` tester le rappel ·
`consolidate [--dry-run]` fusion doublons/obsolètes · `dream` rêve (entretien : conflits, doublons, corrections entendues ; `--done`) · `stats` · `doctor` diagnostic (`doctor --fix` répare tout) ·
`bench` banc d'essai (qualité du rappel, faux rappels, tokens par démarrage, vitesse des hooks) · `tokens [--hours 48]` où partent les tokens (contexte relu, habitudes coûteuses, mesuré sur les transcripts) · `report` rapport du graphe ·
`pc` état du PC (RAM/CPU/GPU) et ce qu'on peut libérer (sessions inactives, serveurs MCP) · `pc --clean` ferme les serveurs MCP orphelins (parent mort) · `pc --history [h]` mesures de la veille ·
`viz --open` vue 3D (`~/.claude/brain/cerveau.html`, régénérée en fin de session) · `export` (MEMOIRES.md lisible) ·
`config recall.enabled false` · `install` réparer.
"""

EVENTS = [
    ("SessionStart", "session-start", 20, "🧠 Chargement du cerveau…"),
    ("UserPromptSubmit", "prompt", 8, None),
    ("Stop", "stop", 10, None),
    ("PreCompact", "pre-compact", 15, None),
    ("PostCompact", "post-compact", 10, None),
    ("SessionEnd", "session-end", 15, None),
]


def launcher() -> str:
    """Commande des hooks. Python lancé directement (pas via le lanceur « py », qui crée un 2e processus) et en mode
    isolé sans site (-I -S : le cerveau n'utilise que la bibliothèque standard) → ~30 ms de moins par hook.
    Si Python change de version, `brain install` (ou `doctor --fix`) remet le bon chemin."""
    script = str(BRAIN_PY).replace("\\", "/")
    exe = sys.executable or ""
    if exe and os.path.exists(exe) and "windowsapps" not in exe.lower() and not exe.lower().endswith("pythonw.exe"):
        return f'"{exe.replace(chr(92), "/")}" -I -S "{script}"'
    if os.name == "nt" and shutil.which("py"):
        return f'py -3 "{script}"'
    return f'"{exe.replace(chr(92), "/")}" "{script}"'


def _is_ours(entry) -> bool:
    return any("brain.py" in str(h.get("command", "")) and " hook " in str(h.get("command", ""))
               for h in entry.get("hooks", []) if isinstance(h, dict))


def merged_settings(settings: dict, remove_only=False) -> dict:
    out = dict(settings)
    hooks = dict(out.get("hooks") or {})
    for event, arg, timeout, status in EVENTS:
        entries = [e for e in hooks.get(event, []) if not (isinstance(e, dict) and _is_ours(e))]
        if not remove_only:
            hook = {"type": "command", "command": f"{launcher()} hook {arg}", "timeout": timeout}
            if status:
                hook["statusMessage"] = status
            entries.append({"hooks": [hook]})
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    if hooks:
        out["hooks"] = hooks
    else:
        out.pop("hooks", None)
    return out


def merged_claude_md(text: str, remove_only=False) -> str:
    if START in text and END in text:
        before = text[: text.index(START)].rstrip()
        after = text[text.index(END) + len(END):].lstrip("\n")
        text = (before + ("\n\n" if before else "") + after).strip()
    if remove_only:
        return (text + "\n") if text else ""
    return (CLAUDE_BLOCK + ("\n" + text + "\n" if text else "")).rstrip() + "\n"


def run(dry=False, uninstall=False):
    from .common import PLUGIN
    if PLUGIN:
        print("🧩 Mode plugin : hooks, skill /brain et serveur MCP viennent du plugin « cerveau », que Claude Code met à "
              "jour tout seul ; les consignes sont injectées au démarrage de chaque session. Rien à installer ici.")
        return
    if not dry and not uninstall:
        from .store import ensure_usage_baseline
        if ensure_usage_baseline():
            print("✓ mesure de l'usage réel démarrée (montré ≠ utilisé)")
    settings_path = CLAUDE_HOME / "settings.json"
    claude_md = CLAUDE_HOME / "CLAUDE.md"
    skill_path = CLAUDE_HOME / "skills" / "brain" / "SKILL.md"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.exit(f"✗ {settings_path} n'est pas un JSON valide ({exc}) : corrige-le avant d'installer.")
    new_settings = merged_settings(settings, remove_only=uninstall)
    old_md = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    new_md = merged_claude_md(old_md, remove_only=uninstall)

    verb = "désinstaller" if uninstall else "installer"
    if dry:
        print(f"[simulation] {verb} :")
        print(f"- {settings_path} → hooks : " + json.dumps(new_settings.get("hooks", {}), ensure_ascii=False, indent=1))
        print(f"- {claude_md} → bloc cerveau {'retiré' if uninstall else 'présent'} ({len(new_md)} car.)")
        print(f"- {skill_path} → {'supprimé' if uninstall else 'écrit'}")
        return

    if new_settings != settings:
        if settings_path.exists():
            shutil.copy2(settings_path, settings_path.with_name("settings.json.bak-brain"))
        write_json(settings_path, new_settings, indent=2)
    if new_md != old_md:
        if new_md:
            write_text(claude_md, new_md)
        elif claude_md.exists():
            claude_md.unlink()
    if uninstall:
        if skill_path.exists():
            skill_path.unlink()
        print("✓ cerveau débranché (hooks, CLAUDE.md, skill). Les données restent dans ~/.claude/brain.")
    else:
        write_text(skill_path, SKILL)
        print(f"✓ hooks ({', '.join(e for e, *_ in EVENTS)}) → {settings_path}")
        print(f"✓ bloc « cerveau » → {claude_md}")
        print(f"✓ skill /brain → {skill_path}")
        print("→ hooks actifs tout de suite, même dans les sessions ouvertes ; l'injection de démarrage et CLAUDE.md "
              "s'appliquent au prochain démarrage de session.")

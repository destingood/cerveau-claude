"""Mode éco, plugins inutilisés : plugins installés et skills claude.ai synchronisées que les transcripts des 30 derniers
jours ne montrent jamais servir ; la veille quotidienne les PROPOSE, rien n'est désactivé sans la commande explicite.

Découpé de eco.py (étape 8 du plan) sans rien changer. `read_settings` est appelé à travers eco (e.read_settings) : un
test qui le remplace dans eco le voit remplacé ici aussi."""
from __future__ import annotations

import json
import re
import time

from . import eco as e
from .common import CHARS_PER_TOKEN, CLAUDE_HOME, CMD, days_since, load_config, log, now_iso, read_json, set_config
from .eco import CLAUDE_AI, OWN_PLUGIN, RECENT_DAYS, SYNC_KEY, UNUSED_DAYS, _announce, _tok, commit


# ------------------------------------------------------------------------------------------ plugins inutilisés
def installed_plugins() -> dict:
    """{« nom@marketplace » : [entrées]} d'après plugins/installed_plugins.json de Claude Code (vide s'il manque)."""
    data = read_json(CLAUDE_HOME / "plugins" / "installed_plugins.json", {}) or {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    out = {}
    for key, entries in (plugins.items() if isinstance(plugins, dict) else ()):
        entries = [entries] if isinstance(entries, dict) else entries
        out[str(key)] = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    return out


def _recent(entries) -> bool:
    return bool(entries) and min(days_since(e.get("installedAt")) for e in entries) < RECENT_DAYS


_COMMAND = re.compile(rb"<command-name>/?([^<\s\\]+)</command-name>")
_TOOL_USE = re.compile(rb'"type":\s*"tool_use",\s*(?:"id":\s*"[^"]*",\s*)?"name":\s*"([^"]+)"')
_SCANS = {}  # une seule lecture des transcripts par commande (et par nombre de jours)


def _refs_in(raw, refs):
    """Une ligne d'assistant qui appelle Skill ou un agent : ajoute à `refs` la skill (input.skill) ou l'agent
    (input.subagent_type) appelé."""
    try:
        o = json.loads(raw)
    except ValueError:
        return
    msg = o.get("message") if isinstance(o, dict) else None
    blocks = msg.get("content") if isinstance(msg, dict) else None
    for b in blocks if isinstance(blocks, list) else ():
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        name, inp = b.get("name"), b.get("input")
        inp = inp if isinstance(inp, dict) else {}
        ref = inp.get("skill") if name == "Skill" else inp.get("subagent_type") if name in ("Task", "Agent") else None
        if ref:
            refs.add(str(ref))


def _attachment(raw):
    try:
        o = json.loads(raw)
    except ValueError:
        return {}
    a = o.get("attachment") if isinstance(o, dict) else None
    return a if isinstance(a, dict) else {}


def _deferred_in(a, names):
    """Annonce d'outils différés (deferred_tools_delta) : met à jour l'ensemble `names` des outils annoncés."""
    for key in ("removedNames", "addedNames", "readdedNames"):
        vals = a.get(key)
        for n in vals if isinstance(vals, list) else ():
            if isinstance(n, str):
                (names.discard if key == "removedNames" else names.add)(n)


def _scan_all(days=UNUSED_DAYS) -> dict:
    """Une seule lecture des transcripts des `days` derniers jours (gardée pour les appels suivants) → {"tools": outils
    appelés, "refs": skills et agents appelés, "commands": commandes tapées par l'utilisateur, "listing": dernière liste
    de skills de la conversation principale, "deferred": outils différés annoncés dans la dernière session principale}."""
    if days in _SCANS:
        return _SCANS[days]
    root = CLAUDE_HOME / "projects"
    cut = time.time() - days * 86400
    files = []
    for f in root.rglob("*.jsonl") if root.is_dir() else ():
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if m >= cut:
            files.append((m, f))
    files.sort(key=lambda x: x[0], reverse=True)
    tools, refs, commands = set(), set(), set()
    listing, deferred = None, None
    for _, f in files:
        main = "subagents" not in f.parts
        try:
            fh = open(f, "rb")
        except OSError:
            continue
        found, names = None, None
        with fh:
            for raw in fh:
                if b'"tool_use"' in raw:
                    tools.update(h.group(1).decode("utf-8", "replace") for h in _TOOL_USE.finditer(raw))
                    if b'"Skill"' in raw or b"subagent_type" in raw:
                        _refs_in(raw, refs)
                if b"<command-name>/" in raw:  # commande tapée par l'utilisateur (« /plugin:commande »)
                    commands.update(h.group(1).decode("utf-8", "replace") for h in _COMMAND.finditer(raw))
                if not main:
                    continue
                if listing is None and b'"skill_listing"' in raw:
                    a = _attachment(raw)
                    if a.get("type") == "skill_listing" and isinstance(a.get("content"), str) \
                            and (a.get("isInitial") is not False or found is None):
                        found = a["content"]
                if deferred is None and b'"deferred_tools_delta"' in raw:
                    a = _attachment(raw)
                    if a.get("type") == "deferred_tools_delta":
                        names = set() if names is None else names
                        _deferred_in(a, names)
        if listing is None and found is not None:
            listing = found
        if deferred is None and names is not None:
            deferred = names
    res = {"tools": tools, "refs": refs, "commands": commands, "listing": listing or "",
           "deferred": sorted(deferred or ())}
    _SCANS[days] = res
    return res


def _scan(names, days=UNUSED_DAYS):
    """→ (plugins utilisés parmi `names` — et « anthropic-skills » si une skill de claude.ai a servi —, dernière liste
    de skills vue). Utilisé : une de ses skills, un de ses agents, une de ses commandes ou un de ses outils MCP a servi."""
    s = _scan_all(days)
    used = set()
    for n in set(names) | {CLAUDE_AI}:
        pre = (f"mcp__plugin_{n}_", f"mcp__plugin_{re.sub('[^A-Za-z0-9_-]', '_', n)}_")
        if any(r.startswith(f"{n}:") for r in s["refs"] | s["commands"]) or any(t.startswith(pre) for t in s["tools"]):
            used.add(n)
    return used, s["listing"]


def _weight(listing, name) -> int:
    """Caractères des lignes de la liste de skills qui reviennent à ce plugin (« - nom:skill : description »)."""
    chars, mine = 0, False
    for line in listing.split("\n"):
        if line.startswith("- "):
            mine = line.startswith(f"- {name}:")
        if mine:
            chars += len(line) + 1
    return chars


def _audit(settings, days=UNUSED_DAYS, cpt=CHARS_PER_TOKEN, ai=False) -> tuple:
    """→ ([(« nom@marketplace », tokens)] des plugins actifs sans aucun usage depuis `days` jours, du plus lourd au plus
    léger ; tokens des skills claude.ai listées dont aucune n'a servi, ou None). Jamais le cerveau lui-même ; poids = leurs
    lignes dans la dernière liste de skills. `ai` : chercher aussi les skills claude.ai (sinon, sans plugin candidat, les
    transcripts ne sont pas parcourus)."""
    enabled = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
    cands = {key: key.partition("@")[0] for key, entries in installed_plugins().items()
             if key.partition("@")[0] != OWN_PLUGIN and enabled.get(key) is not False and not _recent(entries)}
    if not cands and not ai:
        return [], None
    used, listing = _scan(set(cands.values()), days)
    rows = [(key, _weight(listing, name) / cpt) for key, name in cands.items() if name not in used]
    rows.sort(key=lambda r: (-r[1], r[0]))
    chars = _weight(listing, CLAUDE_AI)
    return rows, (chars / cpt if ai and chars and CLAUDE_AI not in used else None)


def unused_plugins(settings=None, days=UNUSED_DAYS, cpt=CHARS_PER_TOKEN) -> list:
    """[(« nom@marketplace », tokens estimés par session)] des plugins actifs sans aucun usage depuis `days` jours."""
    if settings is None:
        settings, err = e.read_settings()
        if err:
            return []
    return _audit(settings, days, cpt)[0]


def synced_plugins() -> dict:
    """{nom: dossier} des plugins synchronisés depuis le compte claude.ai (plugins/synced/<compte>/<nom>). Claude Code les
    charge sans les inscrire dans installed_plugins.json, et ni enabledPlugins ni skillOverrides ne les retirent (essai
    du 21/10/2026) : seule l'app le peut."""
    root = CLAUDE_HOME / "plugins" / "synced"
    out = {}
    for meta in sorted(root.glob("*/*.meta.json")) if root.is_dir() else ():
        name = meta.name[:-len(".meta.json")]
        if name != OWN_PLUGIN and (meta.parent / name).is_dir():
            out.setdefault(name, meta.parent / name)
    return out


def _mcp_count(folder) -> int:
    data = read_json(folder / ".mcp.json", {}) or {}
    servers = data.get("mcpServers", data) if isinstance(data, dict) else None
    return len(servers) if isinstance(servers, dict) else 0


def unused_synced(days=UNUSED_DAYS, cpt=CHARS_PER_TOKEN) -> list:
    """[(nom, tokens de skills listées, serveurs MCP)] des plugins du compte claude.ai sans aucun usage depuis `days`
    jours (skill, commande, agent ou outil MCP), du plus lourd au plus léger."""
    synced = synced_plugins()
    if not synced:
        return []
    used, listing = _scan(set(synced), days)
    rows = [(n, _weight(listing, n) / cpt, _mcp_count(d)) for n, d in synced.items() if n not in used]
    rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
    return rows


def _disable(keys) -> tuple:
    """enabledPlugins à false pour ces plugins (avec retour). → (ok, {clé: False posée}, lignes)."""
    installed = installed_plugins()
    wants, lignes = [], []
    for given in keys:
        found = [k for k in installed if k == given] or \
                [k for k in installed if "@" not in given and k.partition("@")[0] == given]
        if len(found) != 1:
            lignes.append(f"✗ {given} : " + ("plugin inconnu" if not found else "plusieurs marketplaces, précise nom@marketplace")
                          + f" (liste : `{CMD} eco`)")
        elif found[0].partition("@")[0] == OWN_PLUGIN:
            lignes.append(f"✗ {found[0]} : c'est le cerveau lui-même, je ne le désactive jamais")
        elif ("plugin", found[0], False) not in wants:
            wants.append(("plugin", found[0], False))
    ok, posees, more = commit(wants)
    return ok and not any(x.startswith("✗") for x in lignes), posees, lignes + more


def disable(keys) -> tuple:
    """`--desactiver nom@marketplace …` : enabledPlugins à false (avec retour). → (code, texte)."""
    ok, posees, lignes = _disable(keys)
    if posees:
        lignes.append(f"→ pris en compte au prochain démarrage de Claude Code · retour : `{CMD} eco --annuler`")
    return (0 if ok else 1), "\n".join(lignes)


def auto_plugins(force=False, apply=False) -> str:
    """Veille des plugins inutilisés (`eco.plugins_auto`), au plus une fois par jour sauf `force`. Elle PROPOSE seulement
    (décision de l'utilisateur) : une annonce, dite une fois, liste les plugins dont aucune skill n'a servi depuis 30 jours
    et les skills claude.ai (`syncClaudeAiSkills`) si aucune n'a servi, avec la commande qui les coupe. `apply` (commande
    `--plugins`) les désactive pour de bon, comme `--desactiver`. Seuls les plugins qui listent des skills sont concernés :
    sans skill, ils agissent peut-être par hooks. Copie de sécurité et retour par `--annuler` ; la valeur de l'utilisateur
    est respectée. → l'annonce (gardée dans eco.annonce pour le prochain démarrage), ou ''."""
    if not force and days_since((load_config().get("eco") or {}).get("plugins_vus_le")) < 1:
        return ""
    settings, err = e.read_settings()
    if err:
        log(f"éco (veille des plugins) : {err}")
        return ""
    rows, ai = _audit(settings, ai=True)
    rows = [r for r in rows if r[1] > 0]
    if not apply:
        return _propose_plugins(rows, ai if SYNC_KEY not in settings else None)  # valeur de l'utilisateur : respectée
    gone, saved = [], 0.0
    if rows:
        _, posees, _ = _disable([k for k, _ in rows])
        gone = [k for k, t in rows if k in posees]
        saved = sum(t for k, t in rows if k in posees)
    skills = False
    if ai:
        _, posees, _ = commit([("cle", SYNC_KEY, False)])
        skills = SYNC_KEY in posees
        saved += ai if skills else 0
    set_config("eco.plugins_vus_le", now_iso())
    parts = ([f"{len(gone)} plugin(s) inutilisé(s) depuis {UNUSED_DAYS} jours désactivé(s) ({', '.join(gone)})"] if gone else []) \
        + (["skills claude.ai non chargées"] if skills else [])
    if not parts:
        return ""
    if saved:
        parts.append(f"≈{_tok(saved)} tokens de moins par session")
    line = f"⚡ Mode éco : {' · '.join(parts)} · retour : `{CMD} eco --annuler`"
    set_config("eco.propose", "")  # fait : une nouvelle proposition pourra venir
    return line


def _propose_plugins(rows, ai) -> str:
    """La proposition (rien n'est désactivé) : une annonce courte, gardée une seule fois pour ce même lot."""
    set_config("eco.plugins_vus_le", now_iso())
    keys = [k for k, _ in rows] + ([SYNC_KEY] if ai else [])
    sig = ",".join(sorted(keys))
    if not keys or sig == (load_config().get("eco") or {}).get("propose"):
        set_config("eco.propose", sig)
        return ""
    saved = sum(t for _, t in rows) + (ai or 0)
    parts = ([f"{len(rows)} plugin(s) sans usage depuis {UNUSED_DAYS} jours ({', '.join(k for k, _ in rows)})"] if rows else []) \
        + (["les skills claude.ai (aucune n'a servi)"] if ai else [])
    line = f"⚡ Mode éco : je te propose de désactiver {' et '.join(parts)}"
    if saved:
        line += f" · ≈{_tok(saved)} tokens de moins par session"
    line += f" · pour le faire : `{CMD} eco --plugins` (retour : `{CMD} eco --annuler`)"
    set_config("eco.propose", sig)
    _announce(line)
    return line


def watch_plugins(mode) -> tuple:
    """`--plugins-auto [on|off]` → (code, texte) : « on » active la veille et la lance tout de suite."""
    if mode == "off":
        set_config("eco.plugins_auto", False)
        return 0, f"✓ veille quotidienne des plugins coupée (ce qui est déjà désactivé le reste : `{CMD} eco --annuler`)"
    settings, err = e.read_settings()
    if err:
        return 1, f"⚠ {err}"
    set_config("eco.plugins_auto", True)
    note = auto_plugins(force=True)
    return 0, f"{note}\n→ rien n'est désactivé tant que tu ne lances pas `{CMD} eco --plugins`" if note else \
        "✓ veille quotidienne des plugins activée : rien à proposer pour l'instant"


def apply_plugins() -> tuple:
    """`--plugins` → (code, texte) : désactive maintenant les plugins et skills claude.ai proposés par la veille."""
    settings, err = e.read_settings()
    if err:
        return 1, f"⚠ {err}"
    note = auto_plugins(force=True, apply=True)
    if not note:
        return 0, "✓ rien à désactiver : tous les plugins ont servi ces 30 derniers jours"
    return 0, f"{note}\n→ pris en compte au prochain démarrage de Claude Code"

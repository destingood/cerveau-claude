"""Mode éco, sur accord de l'utilisateur : outils et serveurs MCP jamais utilisés, consignes git, plafonds (propositions
chiffrées, `--poser`), et le cache adaptatif (5 min ou 1 h d'après les pauses réelles).

Découpé de eco.py (étape 8 du plan) sans rien changer. `read_settings` est appelé à travers eco (e.read_settings) : un
test qui le remplace dans eco le voit remplacé ici aussi."""
from __future__ import annotations

import os

from . import eco as e
from .common import CHARS_PER_TOKEN, CMD, load_config, log, now_iso, set_config
from .eco import (ABSENT, CACHE_CHOICES, CACHE_DAYS, CACHE_ENVS, CACHE_GAIN_NEW, CACHE_GAIN_SWITCH, CACHE_KEY,
                  CACHE_MIN_REQS, DENY, GIT_TOKENS, KEEP_SERVERS, PROPOSALS, TOOL_WEIGHTS, UNUSED_DAYS, _UUID, _announce,
                  _env_value, _get, _protected, _restore, _same, _section, _server, _ttl, _unset, commit)
from .eco_plugins import _scan_all


def _idle_servers(scan, deny) -> dict:
    """Serveurs MCP différés jamais appelés → {serveur: [outils]} (ni ceux de KEEP_SERVERS, ni ceux déjà refusés)."""
    servers = {}
    for name in scan["deferred"]:
        server = name[5:].partition("__")[0] if name.startswith("mcp__") else ""
        if server and not server.startswith(KEEP_SERVERS) and f"mcp__{server}" not in deny:
            servers.setdefault(server, []).append(name)
    return {s: v for s, v in servers.items() if not any(t.startswith(f"mcp__{s}__") for t in scan["tools"])}


def _servers_detail(servers) -> tuple:
    """→ (tokens de leurs noms différés, « serveur (n outils), … »)."""
    tok = sum(len(n) + 1 for v in servers.values() for n in v) / CHARS_PER_TOKEN
    return tok, ", ".join(f"{_server(s)} ({len(v)} outils)" for s, v in sorted(servers.items(), key=lambda x: (-len(x[1]), x[0])))


def proposals(settings=None, days=UNUSED_DAYS) -> list:
    """Leviers posés seulement sur accord de l'utilisateur, avec ce qu'il reste à poser → [(id, wants, tokens de moins
    à chaque requête ou None, détail)]. Rien pour un levier déjà posé ou réglé par l'utilisateur."""
    if settings is None:
        settings, err = e.read_settings()
        if err:
            return []
    scan = _scan_all(days)
    used = scan["tools"]
    deny = _get(settings, DENY)
    deny = deny if isinstance(deny, list) else []
    out = []
    rules = [r for r in TOOL_WEIGHTS if r not in deny and not _protected(r)
             and not any(t == r or t.startswith(f"{r}__") for t in used)]
    if rules:
        out.append(("outils", [("refus", r, True) for r in rules], sum(TOOL_WEIGHTS[r] for r in rules),
                    ", ".join(rules)))
    servers = {s: v for s, v in _idle_servers(scan, deny).items() if not _UUID.match(s)}
    if servers:
        tok, detail = _servers_detail(servers)
        out.append(("connecteurs", [("refus", f"mcp__{s}", True) for s in sorted(servers)], tok, detail))
    for pid, key, value, gain in (("git", "includeGitInstructions", False, GIT_TOKENS),
                                  ("effort", "maxEffortLevel", "high", None),
                                  ("lecture", "env.CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS", "12000", None),
                                  ("sous-agents", "env.CLAUDE_CODE_SUBAGENT_MODEL", "sonnet", None)):
        if _get(settings, key) is ABSENT and not (key.startswith("env.") and os.environ.get(key[4:])):
            out.append((pid, [("cle", key, value)], gain, PROPOSALS[pid]))
    return out


def pose_proposals(ids) -> tuple:
    """`--poser ID…` (après accord de l'utilisateur) : pose ces leviers, avec retour (`--retirer ID…`). → (code, texte)."""
    ids = list(dict.fromkeys(ids))
    bad = [i for i in ids if i not in PROPOSALS]
    if bad:
        return 1, f"✗ proposition inconnue : {', '.join(bad)} (au choix : {', '.join(PROPOSALS)})"
    settings, err = e.read_settings()
    if err:
        return 1, f"⚠ {err}"
    avail = {pid: wants for pid, wants, _, _ in proposals(settings)}
    wants, owner, lignes = [], {}, []
    for i in ids:
        if i not in avail:
            lignes.append(f"✓ {i} : rien à poser (déjà posé, réglé par toi, ou plus rien d'inutilisé)")
        for w in avail.get(i, ()):
            wants.append(w)
            owner[w[1]] = i
    ok, posees, more = commit(wants)
    lignes += more
    known = (load_config().get("eco") or {}).get("propositions")
    known = known if isinstance(known, dict) else {}
    done = []
    for i in ids:
        names = {n for n in posees if owner.get(n) == i}
        if names:
            old = known.get(i) if isinstance(known.get(i), list) else []
            set_config(f"eco.propositions.{i}", sorted(set(old) | names))
            done.append(i)
    if done:
        lignes.append(f"→ pris en compte au prochain démarrage de Claude Code · retour : `{CMD} eco --retirer {' '.join(done)}`")
    return (0 if ok else 1), "\n".join(lignes)


# ------------------------------------------------------------------------------------------ cache adaptatif
def _pct(x) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def cache_auto() -> str:
    """Cache adaptatif (eco.cache « auto », une fois par jour en arrière-plan) : simule un cache de 5 min et de 1 h sur
    les pauses réelles des 7 derniers jours (`tokens.weigh`) et pose `promptCacheTtl` quand le gain est net (5 % du poids
    total pour le poser, 2 % pour changer une valeur que le cerveau avait posée). Jamais sur une valeur de l'utilisateur,
    ni quand une variable d'environnement du cache est réglée. → l'annonce (gardée pour le prochain démarrage), ou ''."""
    set_config("eco.cache_vu_le", now_iso())
    cfg = load_config()
    eco = cfg.get("eco") or {}
    if not eco.get("auto", True) or (eco.get("cache") or "auto") != "auto":
        return ""
    settings, err = e.read_settings()
    if err:
        log(f"éco (cache) : {err}")
        return ""
    cur = _get(settings, CACHE_KEY)
    mine = cur is not ABSENT and _same(_section(cfg, "pose")["cles"].get(CACHE_KEY, ABSENT), cur)
    if any(_env_value(settings, e) for e in CACHE_ENVS) or (cur is not ABSENT and not mine):
        return ""
    from . import tokens
    b = tokens.weigh(CACHE_DAYS * 24)
    sim, total = b.get("ttl") or {}, b.get("total") or 0
    if (sim.get("reqs") or 0) < CACHE_MIN_REQS or not total or not all(c in sim for c in CACHE_CHOICES):
        return ""
    ref = cur if cur in CACHE_CHOICES else sim.get("regime") if sim.get("regime") in CACHE_CHOICES else "1h"
    best = min(CACHE_CHOICES, key=lambda c: (sim[c], c != ref))
    gain = (sim[ref] - sim[best]) / total
    set_config("eco.bilan", {"le": now_iso(), "regime": ref, "meilleur": best, "gain": round(gain, 4),
                             "fenetre": b.get("fenetre")})
    if best == ref or gain < (CACHE_GAIN_SWITCH if mine else CACHE_GAIN_NEW):
        return ""
    ok, posees, lignes = commit([("cle", CACHE_KEY, best)])
    if not ok or CACHE_KEY not in posees:
        log("éco (cache) : " + " | ".join(lignes))
        return ""
    line = (f"⚡ Mode éco : cache gardé {_ttl(best)} (simulé sur tes pauses des {CACHE_DAYS} derniers jours : "
            f"−{_pct(gain)} du poids des tokens) · retour : `{CMD} eco --cache off`")
    _announce(line)
    return line


def _cache_line(eco, settings, waiting=False) -> str:
    """La ligne « cache » de `brain eco` ; `waiting` : dire quand la simulation manque encore de requêtes."""
    cur = _get(settings, CACHE_KEY)
    head = f"  {CACHE_KEY} : " + ("non réglé (Claude Code : 1 h pour la conversation, 5 min pour le reste)"
                                 if cur is ABSENT else _ttl(cur))
    mode = eco.get("cache") or "auto"
    envs = [e for e in CACHE_ENVS if _env_value(settings, e)]
    mine = cur is not ABSENT and _same(((eco.get("pose") or {}).get("cles") or {}).get(CACHE_KEY, ABSENT), cur)
    if envs:
        return head + f" · réglé par variable d'environnement ({', '.join(envs)}) : cache adaptatif en pause"
    if mode == "off":
        return head + f" · cache adaptatif coupé (`{CMD} eco --cache auto` pour le reprendre)"
    if mode in CACHE_CHOICES:
        return head + f" · fixé par toi (`{CMD} eco --cache auto` pour le choix automatique)"
    if not eco.get("auto", True):
        return head + " · cache adaptatif en pause (mode éco annulé)"
    if cur is not ABSENT and not mine:
        return head + " · réglé par toi, gardé (cache adaptatif en pause)"
    b = eco.get("bilan") if isinstance(eco.get("bilan"), dict) else None
    if not b:
        return head + f" · cache adaptatif : simulation chaque jour sur tes pauses des {CACHE_DAYS} derniers jours" + (
            f" — pas encore assez de requêtes (≥ {CACHE_MIN_REQS} sur {CACHE_DAYS} jours)" if waiting else "")
    try:
        g = float(b.get("gain") or 0)
    except (TypeError, ValueError):
        g = 0.0
    if b.get("meilleur") == b.get("regime"):
        verdict = f"{_ttl(b.get('regime'))} est le meilleur"
    elif cur is not ABSENT and _same(cur, b.get("meilleur")):
        verdict = f"{_ttl(cur)} posé, −{_pct(g)} du poids des tokens"
    else:
        verdict = f"{_ttl(b.get('meilleur'))} ferait gagner {_pct(g)} (posé à partir de {CACHE_GAIN_NEW * 100:.0f} %)"
    return head + f" · cache adaptatif, simulé le {str(b.get('le'))[:10]} sur {CACHE_DAYS} j : {verdict}"


def set_cache(mode) -> tuple:
    """`--cache auto|5m|1h|off` → (code, texte). auto : cache adaptatif (par défaut) ; 5m / 1h : valeur fixée par
    l'utilisateur ; off : cache adaptatif coupé et état d'avant rétabli."""
    settings, err = e.read_settings()
    if err:
        return 1, f"⚠ {err}"
    envs = [f"{e}={_env_value(settings, e)}" for e in CACHE_ENVS if _env_value(settings, e)]
    lignes = [f"⚠ {', '.join(envs)} (variable d'environnement) : c'est elle qui décide du cache"] if envs else []
    if mode in CACHE_CHOICES:
        ok, _, more = commit([("cle", CACHE_KEY, mode)], force=True)
        if not ok:
            return 1, "\n".join(lignes + more)
        set_config("eco.cache", mode)
        return 0, "\n".join(lignes + more + [f"✓ cache fixé à {_ttl(mode)} : plus de choix automatique "
                                             f"(`{CMD} eco --cache auto` pour le reprendre)"])
    if mode == "off":
        ok, more = _restore(only={CACHE_KEY})
        if not ok:
            return 1, "\n".join(more)
        set_config("eco.cache", "off")
        _unset("eco.bilan")
        return 0, "\n".join(more + [f"✓ cache adaptatif coupé (`{CMD} eco --cache auto` pour le reprendre)"])
    set_config("eco.cache", "auto")
    eco = load_config().get("eco") or {}
    if not eco.get("auto", True):
        return 0, "\n".join(lignes + [f"⚠ mode éco annulé : le cache adaptatif reprendra avec `{CMD} eco --appliquer`"])
    note = cache_auto()
    settings, _ = e.read_settings()
    tail = _cache_line(load_config().get("eco") or {}, settings or {}, waiting=not note).strip()
    return 0, "\n".join(lignes + ([note] if note else []) + [f"✓ cache adaptatif actif · {tail}"])

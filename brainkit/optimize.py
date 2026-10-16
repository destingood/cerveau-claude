"""Optimiser tous les aspects du cerveau — les tokens d'abord.

Le pendant « tokens » de `brain pc` : on mesure en **vrais tokens** ce que le cerveau coûte vraiment —
l'injection de démarrage (relue à chaque requête jusqu'à la compaction, donc « portée » comme une habitude),
le rappel par message, la taille du corpus — puis on liste, chiffré, ce qu'on peut alléger.

Comme `brain pc` : rapport seul par défaut ; `--apply` applique ce qui est **sûr et réversible**
(ménage du corpus via la consolidation, qui pose sa propre sauvegarde ; rappel ciblé de l'habitude la plus coûteuse
au démarrage). Ce qui touche au contenu des souvenirs ou aux habitudes est listé et chiffré, jamais fait tout seul.
"""
from __future__ import annotations

import argparse

from . import index as idx
from .common import CHARS_PER_TOKEN, days_since, est_tokens, load_config, log, set_config
from .store import Brain

OVERSIZE = 220   # tokens : au-delà, le corps d'un souvenir est anormalement long (la mémoire doit être dense)
STALE_DAYS = 180
TODO_DAYS = 45


def _tok(s) -> int:
    return est_tokens(s or "")


def _m(x) -> str:
    return f"{x / 1e6:.1f} M" if x >= 1e6 else (f"{x / 1e3:.1f} k" if x >= 1000 else str(int(x)))


def habit(hours=48.0):
    """(habitude la plus coûteuse mesurée sur les transcripts, requêtes/session) — levier externe au cerveau."""
    try:
        from . import tokens as tk
        d = tk.measure(hours)
        total = sum(d["reqs"]) or 1
        best = None
        for key, label, tip in tk.HABITS:
            if d["habits"].get(key):
                n, carried = d["habits"][key]
                if not best or carried > best["carried"]:
                    best = {"key": key, "label": label, "tip": tip, "n": n,
                            "carried": carried, "pct": 100 * carried / total}
        rps = len(d["reqs"]) / max(1, d["files"])
        return best, rps
    except Exception as exc:  # jamais bloquer l'optimiseur sur la lecture des transcripts
        log(f"optimize.habit : {exc!r}")
        return None, 0.0


def measure(cfg=None) -> dict:
    """Coût réel en tokens de chaque surface du cerveau + ce qui pourrait être allégé."""
    cfg = cfg or load_config()
    b = Brain.load()
    inj, rc = cfg["inject"], cfg["recall"]
    cap = int(inj["max_tokens"] * CHARS_PER_TOKEN)

    gtext, _, _ = idx.session_context(b, None, cfg)
    projs = []
    for p in b.projects():
        path = (p.get("meta") or {}).get("path")
        if not path:
            continue
        t, _, _ = idx.session_context(b, path, cfg)
        projs.append({"id": p["id"], "tok": _tok(t), "truncated": len(t) >= cap - 2})

    active = [n for n in b.active() if n["type"] != "project"]
    body_tok = {n["id"]: _tok(n.get("body", "")) for n in active}
    title_tok = {n["id"]: _tok(n["title"]) for n in active}
    oversize = sorted(((n, body_tok[n["id"]]) for n in active if body_tok[n["id"]] > OVERSIZE),
                      key=lambda x: -x[1])

    # Doublons quasi identiques encore actifs. Seuil fusion auto = 0.9 (comme la consolidation auto) : seuls ces
    # tokens-là sont promis au gain « sûr ». Entre 0.82 et 0.9 : seulement signalé, fusion à confirmer.
    seen, dup_auto, dup_sugg, dup_auto_tok = set(), 0, 0, 0
    for n in active:
        if n["id"] in seen:
            continue
        for score, m in b.similar(n["title"], n.get("body", ""), n["type"], limit=3, threshold=0.82, exclude=n["id"]):
            if m["id"] in seen or m["id"] == n["id"]:
                continue
            seen.add(m["id"])
            if score >= 0.9:
                dup_auto += 1
                dup_auto_tok += body_tok.get(m["id"], 0) + title_tok.get(m["id"], 0)
            else:
                dup_sugg += 1

    superseded = [e for e in b.edges if e["rel"] == "supersedes" and e["to"] in b.nodes
                  and b.nodes[e["to"]].get("status", "active") == "active"
                  and e["from"] in b.nodes and b.nodes[e["from"]].get("status", "active") == "active"]
    sup_tok = sum(body_tok.get(e["to"], 0) + title_tok.get(e["to"], 0) for e in superseded)
    stale = [n for n in active if n["type"] in ("learning", "reference", "todo", "entity")
             and n.get("importance", 3) <= 2 and not n.get("hits") and days_since(n.get("updated")) > STALE_DAYS]
    stale_tok = sum(body_tok[n["id"]] + title_tok[n["id"]] for n in stale)
    todos_old = [n for n in active if n["type"] == "todo" and days_since(n.get("updated")) > TODO_DAYS]

    hb, rps = habit()
    return {
        "cfg": cfg,
        "startup_global": _tok(gtext), "startup_global_truncated": len(gtext) >= cap - 2,
        "startup_projects": projs, "max_budget": int(inj["max_tokens"]),
        "recall_mem_tok": int(rc.get("max_chars", 1200) / CHARS_PER_TOKEN),
        "recall_items": rc.get("max_items", 3), "recall_files": rc.get("max_files", 4),
        "recall_enabled": rc.get("enabled", True),
        "nodes": len(active),
        "corpus_tok": sum(body_tok.values()) + sum(title_tok.values()),
        "oversize": oversize,
        "dup_auto": dup_auto, "dup_sugg": dup_sugg, "dup_auto_tok": dup_auto_tok,
        "superseded": len(superseded), "superseded_tok": sup_tok,
        "stale": stale, "stale_tok": stale_tok, "todos_old": todos_old,
        "habit": hb, "reqs_per_session": rps, "habit_tip_on": bool(inj.get("habit_tip")),
    }


def plan(m) -> list:
    """Liste rangée du plus gros gain au plus petit : {saved, auto, text}. saved = tokens, estimé (« ≈ »)."""
    out = []
    # 1. Ménage sûr du corpus (consolidation) : moins de souvenirs à indexer et à départager au rappel.
    corpus_cut = m["superseded_tok"] + m["stale_tok"] + m["dup_auto_tok"]
    n_safe = m["superseded"] + len(m["stale"]) + m["dup_auto"]
    if n_safe:
        out.append({"saved": corpus_cut, "auto": True,
                    "text": f"Ménage sûr du corpus : {n_safe} souvenir(s) (remplacés, obsolètes, doublons évidents) "
                            f"→ −{_m(corpus_cut)} tok de corpus relu à chaque recherche et rappel "
                            f"(déjà fait seul en fin de session ; tout de suite : `brain optimize --apply`)"})
    # 2. Boucle d'habitude : rappeler au démarrage le plus gros gaspillage mesuré. Ce n'est PAS un gain direct de
    #    tokens (saved = 0, donc exclu du « gain sûr ») : c'est un nudge comportemental qui coûte même ~30 tok/session ;
    #    son intérêt est indirect (réduire dans le temps le plus gros poste externe, hors cerveau).
    hb = m["habit"]
    if hb and not m["habit_tip_on"]:
        out.append({"saved": 0, "auto": True,
                    "text": f"Rappel au démarrage de ton plus gros poste mesuré ({hb['label']}, {hb['pct']:.0f} % du "
                            f"contexte relu sur 48 h) : nudge comportemental, pas un gain direct (coûte ≈ 30 tok/session, "
                            f"bénéfice indirect) → `brain optimize --apply` ; `brain config inject.habit_tip false` pour l'enlever"})
    # 3. Souvenirs trop longs : à résumer (sensible, jamais touché seul).
    if m["oversize"]:
        gain = sum(t - OVERSIZE for _, t in m["oversize"])
        ids = ", ".join(f"`{n['id']}`" for n, _ in m["oversize"][:4]) + (" …" if len(m["oversize"]) > 4 else "")
        out.append({"saved": gain, "auto": False,
                    "text": f"{len(m['oversize'])} souvenir(s) trop longs (> {OVERSIZE} tok) → les résumer "
                            f"(`brain edit <id> -b …`) : {ids} — jusqu'à −{_m(gain)} tok"})
    # 4. Doublons à relire (0.82–0.9) : fusion à confirmer.
    if m["dup_sugg"]:
        out.append({"saved": 0, "auto": False,
                    "text": f"{m['dup_sugg']} paire(s) de souvenirs proches à relire → `brain consolidate` "
                            f"(fusion à confirmer, non faite automatiquement)"})
    # 5. Vieilles tâches : à clore.
    if m["todos_old"]:
        out.append({"saved": 0, "auto": False,
                    "text": f"{len(m['todos_old'])} tâche(s) de plus de {TODO_DAYS} j → `brain todo` puis "
                            f"`brain done <id>` ou `brain rm <id>`"})
    # 6. Injection qui sature son budget : budget plus serré (réglage, réversible, à valider).
    if m["startup_global_truncated"]:
        out.append({"saved": 0, "auto": False,
                    "text": f"L'injection de démarrage sature son budget ({m['startup_global']}/{m['max_budget']} tok) "
                            f"→ `brain config inject.index_tokens 1300` l'allège à chaque requête (réversible)"})
    out.sort(key=lambda a: (-a["saved"], not a["auto"]))
    return out


def notice(cfg=None) -> str:
    """Ligne injectée au démarrage quand `inject.habit_tip` est activé : l'habitude la plus coûteuse + son correctif."""
    cfg = cfg or load_config()
    tip = (cfg.get("inject") or {}).get("habit_tip")
    return tip if isinstance(tip, str) and tip.strip() else ""


def report(hours=48.0, show_all=False, cfg=None) -> str:
    cfg = cfg or load_config()
    m = measure(cfg)
    L = ["🧠 Optimisation — ce que le cerveau coûte en tokens, et ce qu'on peut alléger"]
    rps = m["reqs_per_session"]
    carried = f" · ≈ {_m(m['startup_global'] * rps)} sur une session de {rps:.0f} requêtes" if rps else ""
    L.append(f"Démarrage : {m['startup_global']} tok injectés (budget {m['max_budget']})"
             + (" — saturé" if m["startup_global_truncated"] else "")
             + ", relus à chaque requête" + carried)
    if m["startup_projects"]:
        best = max(m["startup_projects"], key=lambda p: p["tok"])
        L.append(f"  avec fiche projet : jusqu'à {best['tok']} tok (projet « {best['id']} »)"
                 + (" — saturé" if best["truncated"] else ""))
    L.append(f"Par message : jusqu'à {m['recall_items']} souvenir(s) (~{m['recall_mem_tok']} tok) + "
             f"{m['recall_files']} fichier(s)" + ("" if m["recall_enabled"] else " — rappel DÉSACTIVÉ"))
    L.append(f"Corpus : {m['nodes']} souvenirs actifs, {_m(m['corpus_tok'])} tok "
             f"(candidats à chaque recherche et rappel)")

    acts = plan(m)
    L.append("")
    if acts:
        L.append("Ce qu'on peut alléger (du plus gros gain au plus petit) :")
        for i, a in enumerate(acts[: None if show_all else 8], 1):
            tag = "[auto] " if a["auto"] else "[à valider] "
            L.append(f"  {i}. {tag}{a['text']}")
        auto_gain = sum(a["saved"] for a in acts if a["auto"])
        if auto_gain:
            L.append(f"  → gain sûr applicable maintenant : ≈ {_m(auto_gain)} tok (`brain optimize --apply`, réversible)")
    else:
        L.append("Rien à alléger : le cerveau est déjà au plus serré. ✓")

    hb = m["habit"]
    if hb:
        L += ["", f"Levier le plus lourd, hors cerveau (mesuré sur {hours:g} h) : {hb['label']} — "
                  f"porté {_m(hb['carried'])} = {hb['pct']:.0f} % du contexte relu (exposition cumulée, "
                  f"pas un gain direct) → {hb['tip']}"]
    L += ["", "Détail de tous les tokens : `brain tokens` · matériel (RAM/CPU/GPU) : `brain pc`"]
    return "\n".join(L)


def apply(cfg=None) -> str:
    """Applique SEULEMENT le sûr et réversible, mesure le vrai avant/après. Le sensible reste des suggestions."""
    from . import history
    cfg = cfg or load_config()
    before = measure(cfg)
    done = []
    history.snapshot("avant-optimisation", force=True)

    # 1. Ménage sûr du corpus : on réutilise la consolidation (mode auto = fusions évidentes seulement, sa propre
    #    sauvegarde) plutôt que de la réécrire.
    if before["superseded"] or before["stale"] or before["dup_auto"]:
        try:
            from . import cli
            cli.cmd_consolidate(argparse.Namespace(dry_run=False, auto=True))
            done.append("corpus consolidé (remplacés/obsolètes/doublons évidents)")
        except Exception as exc:
            log(f"optimize.apply consolidate : {exc!r}")

    # 2. Boucle d'habitude : stocker la ligne de rappel, injectée au démarrage par le hook (réversible).
    hb = before["habit"]
    if hb and not before["habit_tip_on"]:
        tip = f"⚡ Tokens — ton plus gros poste mesuré : {hb['label']}. {hb['tip']}"
        set_config("inject.habit_tip", tip)
        cfg = load_config()
        done.append(f"rappel d'habitude activé au démarrage ({hb['key']})")

    after = measure(cfg)
    L = ["🔧 Optimisation appliquée (sûr et réversible) :" if done else "Rien de sûr à appliquer pour l'instant."]
    for d in done:
        L.append(f"  ✓ {d}")
    dc = before["corpus_tok"] - after["corpus_tok"]
    dn = before["nodes"] - after["nodes"]
    if dn or dc:
        L.append(f"  → corpus : {before['nodes']} → {after['nodes']} souvenirs (−{dn}), "
                 f"−{_m(max(0, dc))} tok relus à chaque recherche et rappel")
    rest = [a for a in plan(after) if not a["auto"]]
    if rest:
        L += ["", "À valider (jamais fait tout seul) :"]
        for a in rest[:6]:
            L.append(f"  - {a['text']}")
    if done:
        L += ["", "Réversible : `brain restore 1` (corpus) · `brain config inject.habit_tip false` (rappel)"]
    return "\n".join(L)

"""Rêve : l'entretien de la mémoire sort de la conversation (façon Letta « sleep-time », « Auto Dream » de Claude Code).

- Chaque jour (fin de session, en arrière-plan, avec la consolidation), la partie SÛRE s'applique toute seule :
  « hier », « dans 2 semaines »… d'un souvenir jamais retouché deviennent des dates réelles, calculées d'après sa
  date d'écriture (instantané pris avant) ; les observations datées de plus de 7 jours sont condensées en un résumé
  par semaine et par projet (le « Reflector » de Mastra ; originales archivées, rien n'est perdu).
- Le reste demande du jugement et part dans un dossier compact (REVE.md) : corrections entendues mais jamais
  mémorisées, observations 🔴 qu'aucun souvenir ne reflète, conflits et doublons probables, règles proches à
  fusionner, souvenirs montrés sans jamais servir, décisions sans « pourquoi », à-faire en retard.
- Au démarrage suivant (au plus une fois par jour, et seulement s'il y a assez à faire), une ligne propose de le
  confier à un sous-agent en arrière-plan. `brain dream --done` le clôt."""
from __future__ import annotations

import datetime as _dt
import re

from .common import (BRAIN_DIR, CMD, SESSIONS_DIR, STATE_DIR, fmt_date, fold, load_config, now_iso, parse_iso,
                     read_json, short, write_json, write_text)
from .store import Brain

DREAM_FILE = BRAIN_DIR / "REVE.md"
STATE_FILE = STATE_DIR / "dream.json"
WIKI_DREAM = ("Pages à créer (liens vers rien)", "Sources à ingérer", "Pages peut-être dépassées", "Sources abîmées",
              "Conflits git non résolus (<<<<<<<)", "Secrets à retirer",
              "Souvenirs à verser dans une page de savoir (concept, sujet, entité)")
WHY_RX = re.compile(r"(pourquoi|parce qu|\bcar\b|afin|pour que|sinon|\bwhy\b|because|comment l'appliquer|raison)", re.I)


def _state() -> dict:
    return read_json(STATE_FILE, {}) or {}


def _save(st):
    write_json(STATE_FILE, st)


def heard_corrections(brain, since=None, limit=8):
    """Phrases de l'utilisateur (sessions récentes) qui ressemblent à une préférence, une correction ou une décision,
    et qu'aucun souvenir ne reflète encore."""
    from .hooks import CAPTURE_RX
    out, seen = [], set()
    files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime) if SESSIONS_DIR.exists() else []
    for f in files:
        if since and f.stat().st_mtime < since.timestamp():
            continue
        st = read_json(f, {}) or {}
        for p in (st.get("tx") or {}).get("recent", []):
            t = " ".join(str(p.get("t", "")).split())
            if len(t) < 15 or not CAPTURE_RX.search(t):
                continue
            key = fold(t)[:80]
            if key in seen:
                continue
            seen.add(key)
            if brain.similar(t[:120], t, None, limit=1, threshold=0.3):
                continue  # déjà reflété par un souvenir
            out.append(t)
    return out[-limit:]


def pairs(brain, limit=8):
    """Conflits (même sujet, valeur différente) et doublons probables, dans le même projet."""
    from . import reconcile
    dups, conflicts, seen = [], [], set()
    for n in [x for x in brain.active() if x["type"] != "project"]:
        for s, m in brain.similar(n["title"], n.get("body", ""), None, limit=4, threshold=0.5, exclude=n["id"]):
            key = tuple(sorted((n["id"], m["id"])))
            if key in seen or (n.get("project") or None) != (m.get("project") or None) or n["type"] != m["type"]:
                continue
            seen.add(key)
            old, new = sorted((n, m), key=lambda x: x.get("created") or "")
            sig = reconcile.signals(old, new["title"], new.get("body", ""))
            if sig.get("autre sujet") or sig.get("autre événement"):
                continue
            value = [k for k in reconcile.VALUE_SIGNALS if sig.get(k)]
            if value and old["type"] in reconcile.UPDATABLE:
                conflicts.append((s, old, new, value))
            elif s >= 0.6:
                dups.append((s, old, new))
    return dups[:limit], conflicts[:limit]


def fix_relative_dates(brain):
    """Partie sûre : dates relatives d'un souvenir jamais retouché → dates réelles, d'après sa date d'écriture."""
    from .dates import absolutize, has_relative
    fixed = []
    for n in brain.active():
        if n["type"] in ("feedback", "user") or not has_relative(f"{n['title']}\n{n.get('body', '')}"):
            continue
        created = parse_iso(n.get("created"))
        if not created or (n.get("created") or "")[:10] != (n.get("updated") or "")[:10]:
            continue  # retouché depuis : on ne sait pas de quand date chaque phrase → laissé tel quel
        day = created.date()
        n["title"] = " ".join(absolutize(n["title"], day).split())
        n["body"] = absolutize(n.get("body", ""), day)
        brain.dirty = True
        fixed.append(n["id"])
    return fixed


def unused(brain, min_shown=6):
    from .store import shown_since
    if not brain.data.get("usage_since"):
        return []  # mesure d'usage pas encore commencée
    return [n for n in brain.active() if n["type"] not in ("project", "user")
            and shown_since(n) >= min_shown and not n.get("used")]


def no_why(brain):
    return [n for n in brain.active(("decision", "feedback"))
            if not WHY_RX.search(n.get("body") or "") and len(n.get("body") or "") < 160]


def overdue(brain):
    from .dates import days_until, due_of
    out = []
    for n in brain.active(("todo",)):
        d = due_of(n)
        if d and (days_until(d) or 0) < 0:
            out.append((n, d))
    return out


def repeated_rules(brain, limit=4):
    """Règles proches entre elles : à fusionner en une seule règle forte (mémoire procédurale)."""
    groups, seen = [], set()
    for n in brain.active(("feedback",)):
        if n["id"] in seen:
            continue
        sims = [m for s, m in brain.similar(n["title"], n.get("body", ""), "feedback", limit=4, threshold=0.4,
                                            exclude=n["id"]) if m["id"] not in seen]
        if sims:
            group = [n] + sims
            seen.update(x["id"] for x in group)
            groups.append(group)
    return groups[:limit]


def prepare(apply_safe=True):
    """→ (texte du dossier, nombre de points demandant du jugement). La partie sûre est appliquée (instantané avant)."""
    from .dates import has_relative
    from .store import shown_since
    from . import observations
    st = _state()
    since = parse_iso(st.get("done"))
    fixed, condensed = [], (0, 0)
    if apply_safe:
        b0 = Brain.load()
        if any(n["type"] not in ("feedback", "user") and has_relative(f"{n['title']}\n{n.get('body', '')}")
               for n in b0.active()):
            from . import history
            history.snapshot("avant-reve", force=True)
            with Brain.edit() as b:
                fixed = fix_relative_dates(b)
        try:  # observations de plus de 7 jours → un résumé par semaine et par projet (originales archivées d'abord)
            condensed = observations.condense()
        except Exception as exc:
            from .common import log
            log(f"rêve : condensation des observations : {exc!r}")
    brain = Brain.load()
    heard = heard_corrections(brain, since)
    dups, conflicts = pairs(brain)
    rules = repeated_rules(brain)
    idle = unused(brain)[:6]
    why = no_why(brain)[:6]
    late = overdue(brain)
    try:
        red = observations.unsaved(brain, since)
    except Exception:
        red = []
    wiki_rows = []
    if (brain.data.get("wiki") or {}).get("root") and not brain.data["wiki"].get("missing"):
        try:  # le wiki : sa santé fait partie de l'entretien (pages à créer, sources en attente, pages dépassées…)
            from . import wiki
            rep = wiki.lint(brain, limit=5)
            wiki_rows = [(f"Wiki — {title}", rows) for title, rows in rep.items() if title in WIKI_DREAM]
        except Exception as exc:
            from .common import log
            log(f"rêve : lint du wiki : {exc!r}")
    items = len(heard) + len(dups) + len(conflicts) + len(rules) + len(idle) + len(why) + len(late) + len(red) \
        + sum(len(r) for _, r in wiki_rows)
    lines = [f"# 🌙 Rêve du cerveau — {fmt_date(now_iso())}", "",
             f"_{items} point(s) demandant du jugement. Appliquer ce qui est sûr avec les commandes indiquées, demander "
             f"à l'utilisateur en cas de doute, ne jamais inventer un fait ; terminer par `{CMD} dream --done`._", ""]
    if fixed:
        lines += [f"✓ Déjà appliqué : dates relatives rendues absolues dans {len(fixed)} souvenir(s) "
                  f"({', '.join(f'`{i}`' for i in fixed[:6])}).", ""]
    if condensed[0]:
        lines += [f"✓ Déjà appliqué : {condensed[0]} observation(s) de plus de {observations.KEEP_DAYS} jours condensée(s) en "
                  f"{condensed[1]} résumé(s) de semaine (originales dans journal/observations-archive.jsonl).", ""]
    sections = [
        ("Entendu mais jamais mémorisé (préférences, corrections, décisions)",
         [f"« {short(t, 200)} » → si c'est durable : `add -t feedback|decision -T … -b … --src utilisateur`" for t in heard]),
        ("Observations 🔴 qu'aucun souvenir ne reflète",
         [f"{fmt_date(o['at'])} « {short(o['t'], 180)} » → si c'est durable : `add -t decision|fact|learning -T … -b … "
          f"-p {o.get('proj') or 'none'}`" for o in red]),
        ("Conflits probables (même sujet, valeur différente)",
         [f"`{o['id']}` ({short(o['title'], 60)}) puis `{n['id']}` ({short(n['title'], 60)}) — {', '.join(v)} → "
          f"si le second remplace le premier : `supersede {n['id']} {o['id']}`" for s, o, n, v in conflicts]),
        ("Doublons probables",
         [f"`{o['id']}` ≈ `{n['id']}` (similarité {s}) → compléter l'un (`edit -a`), archiver l'autre (`rm`)"
          for s, o, n in dups]),
        ("Règles proches à fusionner en une règle forte",
         [" · ".join(f"`{x['id']}`" for x in g) + " → une seule règle (`edit … -i 5`), archiver les autres"
          for g in rules]),
        ("Montrés souvent, jamais utilisés",
         [f"`{n['id']}` ({short(n['title'], 70)}) — montré {shown_since(n)}× sans servir → titre plus précis, importance plus basse, "
          f"ou `rm` s'il est obsolète" for n in idle]),
        ("Décisions et règles sans « pourquoi »",
         [f"`{n['id']}` ({short(n['title'], 70)}) → `edit {n['id']} -a \"Pourquoi : …\"` si la raison est connue"
          for n in why]),
        ("À-faire en retard",
         [f"`{n['id']}` ({short(n['title'], 70)}) — échéance {fmt_date(d)} → `done`, nouvelle date (`edit --due`) "
          f"ou demander à l'utilisateur" for n, d in late]),
    ]
    sections += [(t, [f"{r} → voir le schéma du wiki (CLAUDE.md), `brain wiki lint`" for r in rows]) for t, rows in wiki_rows]
    for title, rows in sections:
        if rows:
            lines += [f"## {title}", ""] + [f"- {r}" for r in rows] + [""]
    if not items:
        lines.append("Rien à trancher : la mémoire est propre.")
    text = "\n".join(lines).rstrip() + "\n"
    write_text(DREAM_FILE, text)
    st.update({"prepared": now_iso(), "pending": items})
    _save(st)
    return text, items


def done():
    st = _state()
    st.update({"done": now_iso(), "pending": 0, "notified": None})
    _save(st)


def notice() -> str:
    """Ligne pour le démarrage quand un rêve attend (au plus une fois par jour, et s'il y a assez à faire)."""
    cfg = load_config().get("dream", {})
    st = _state()
    if not cfg.get("notice", True) or (st.get("pending") or 0) < cfg.get("min_items", 3):
        return ""
    last = parse_iso(st.get("notified"))
    if last and (_dt.datetime.now() - last).total_seconds() < 86400:
        return ""
    st["notified"] = now_iso()
    _save(st)
    return (f"🌙 Entretien du cerveau : {st['pending']} point(s) en attente (conflits, doublons, corrections entendues…). "
            f"Quand la tâche le permet, le confier à un sous-agent en arrière-plan : `{CMD} dream`, appliquer ce qui "
            f"est sûr, puis `{CMD} dream --done`.")

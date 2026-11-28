"""`brain oublier-session <id>` : retirer ce qu'une session a écrit et qui ne reposait que sur elle (façon
`remove_episode` de graphiti), d'après la provenance des souvenirs et le journal de leurs textes (provenance.py).

Montre d'abord, n'agit qu'avec --oui (accord de l'utilisateur) :
- créés par cette seule session → archivés comme `brain rm` (--purge : supprimés pour de bon, comme `rm --purge`) ;
  un lien qui y mène depuis un autre souvenir est dit ;
- modifiés par cette session, et par personne depuis → remis comme avant (titre, contenu, statut, dates…) ;
- le reste est gardé et listé avec la raison : créé ici mais repris par une autre session, modifié ensuite ailleurs
  (autre session, Obsidian, rêve), projet, ou rien au journal de ce PC pour revenir en arrière.
Un instantané est pris avant (`brain restore 1` annule), et ce qui est fait est lui-même noté au journal."""
from __future__ import annotations

from . import provenance
from .cli_commun import die, refresh_views
from .common import CMD, fmt_date, short
from .store import Brain, _foreign

HERE = (".", "celle-ci", "courante", "cette-session")


def known(brain, rows) -> dict:
    """Sessions qui ont écrit : {id: {"ajout": n, "modif": n, "de": date, "a": date, "ids": {souvenirs}}}."""
    out = {}
    for r in rows:
        sid = r.get("s")
        if not sid:
            continue
        k = out.setdefault(sid, {"ajout": 0, "modif": 0, "purge": 0, "de": r["le"], "a": r["le"], "ids": set()})
        k[r["op"]] += 1
        k["a"] = max(k["a"], r["le"])
        k["de"] = min(k["de"], r["le"])
        k["ids"].add(r["id"])
    for nid, n in brain.nodes.items():
        if _foreign(nid):
            continue
        for sid in provenance.sessions_of(n):
            out.setdefault(sid, {"ajout": 0, "modif": 0, "purge": 0, "de": "", "a": "", "ids": set()})["ids"].add(nid)
    return out


def resolve(ref, sessions):
    """Id complet, début d'id (4 caractères au moins) ou « . » (la session courante) → id, ou un message d'erreur."""
    if str(ref).strip().lower() in HERE:
        sid = provenance.current()
        return (sid, None) if sid else (None, "pas de session courante ici (hors de Claude Code, ou Claude Code trop "
                                               "ancien pour CLAUDE_CODE_SESSION_ID) : donne son id")
    sid = provenance.clean_id(ref)
    if not sid:
        return None, f"id de session illisible : « {ref} »"
    if sid in sessions:
        return sid, None
    hits = [s for s in sessions if s.startswith(sid)] if len(sid) >= 4 else []
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f"« {sid} » désigne {len(hits)} sessions ({', '.join(sorted(hits))}) : donne plus de l'id"
    return sid, None  # inconnue : le plan dira qu'elle n'a rien écrit


def _who(rows_, sessions):
    names = []
    for s in [r.get("s") for r in rows_] + list(sessions):
        name = f"la session {provenance.short_id(s)}" if s else "une écriture sans session (terminal, Obsidian, rêve)"
        if name not in names:
            names.append(name)
    return ", ".join(names) or "une autre session"


def plan(brain, sid, rows, purge=False) -> dict:
    """Ce que ferait l'oubli de `sid` : {"retirer": [(id, note)], "annuler": [(id, champs d'avant, note)],
    "garder": [(id, raison)], "partis": [ids supprimés depuis]}. Ce qu'un oubli précédent de `sid` a déjà fait (lignes
    « oubli » du journal) n'est pas refait."""
    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    own = {nid: n for nid, n in brain.nodes.items() if not _foreign(nid)}
    touched = {nid for nid, n in own.items() if sid in provenance.sessions_of(n)}
    touched |= {r["id"] for r in rows if r.get("s") == sid}
    out = {"retirer": [], "annuler": [], "garder": [], "partis": []}
    for nid in sorted(touched):
        n, hist = own.get(nid), by_id.get(nid, [])
        if n is None:
            if not any(r["op"] == "purge" and r.get("oubli") == sid for r in hist):
                out["partis"].append(nid)
            continue
        others = [s for s in provenance.sessions_of(n) if s != sid]
        if any(r["op"] == "ajout" and r.get("s") == sid for r in hist):
            later = [r for r in hist if r.get("s") != sid and r.get("oubli") != sid]
            if later or others:
                out["garder"].append((nid, f"créé par cette session, repris ensuite par {_who(later, others)}"))
            elif n.get("type") == "project":
                out["garder"].append((nid, f"projet créé par cette session : gardé (`{CMD} rm {nid}` si tu n'en veux "
                                           "plus)"))
            elif n.get("status", "active") == "active" or purge:  # déjà archivé : rien à refaire, sauf --purge
                out["retirer"].append((nid, ""))
            continue
        cur = provenance.snap(n)
        done = max((i for i, r in enumerate(hist) if r.get("oubli") == sid and r["op"] == "modif"  # oubli toujours en
                    and all(cur.get(k) == v for k, v in r["apres"].items())), default=-1)  # place (pas de restore depuis)
        if done >= 0:  # déjà oublié une fois : seulement ce que la session a écrit depuis
            hist = hist[done + 1:]
        hist = [r for r in hist if r.get("oubli") != sid]  # un oubli défait depuis (restore) ne compte pas
        mine = [r for r in hist if r.get("s") == sid]
        if not mine and done >= 0:
            continue
        if not mine:
            out["garder"].append((nid, "écrit par cette session, mais rien au journal de ce PC (autre PC, journal "
                                       "effacé) : à revoir à la main"))
            continue
        last_other = max((i for i, r in enumerate(hist) if r.get("s") != sid), default=-1)
        block = [r for r in hist[last_other + 1:] if r["op"] == "modif"]
        if not block:
            out["garder"].append((nid, f"modifié par cette session, puis par {_who(hist[last_other:last_other + 1], ())}"))
            continue
        before, after = {}, {}
        for r in block:
            for k, v in r["avant"].items():
                before.setdefault(k, v)
            after.update(r["apres"])
        changed = [k for k in after if cur.get(k) != after[k]]
        if any(r.get("coupe") for r in block) or changed:
            why = "texte trop long pour le journal" if any(r.get("coupe") for r in block) else \
                f"changé depuis hors du cerveau ({', '.join(provenance.LABELS.get(k, k) for k in changed)} : Obsidian, rêve…)"
            out["garder"].append((nid, f"modifié par cette session, {why}"))
            continue
        restore = {k: v for k, v in before.items() if cur.get(k) != v}
        if not restore:
            continue
        note = " (ses modifications plus anciennes, reprises ensuite par d'autres, restent)" if last_other >= 0 and \
            any(r.get("s") == sid for r in hist[:last_other]) else ""
        out["annuler"].append((nid, restore, note))
    gone = {nid for nid, _ in out["retirer"]}
    for i, (nid, _) in enumerate(out["retirer"]):  # un autre souvenir y mène : on le dit
        inbound = sorted({e["from"] for e in brain.edges if e["to"] == nid and e["from"] not in gone})
        if inbound:
            out["retirer"][i] = (nid, "  ← lié depuis " + ", ".join(f"`{x}`" for x in inbound[:4])
                                 + (f" (+{len(inbound) - 4})" if len(inbound) > 4 else ""))
    return out


def _fields(node, restore) -> dict:
    """Valeurs d'avant (snap) → arguments de Brain.update."""
    fields, meta = {}, None
    for k, v in restore.items():
        if k.startswith("meta."):
            meta = meta if meta is not None else dict(node.get("meta") or {})
            if v in (None, "", []):
                meta.pop(k[5:], None)
            else:
                meta[k[5:]] = v
        elif k == "project":
            fields["project"] = v or ""
        elif v is not None:
            fields[k] = v
    if meta is not None:
        fields["meta"] = meta
    return fields


def apply(brain, sid, p, purge=False) -> None:
    """Fait le plan. Les écritures sont notées au journal comme l'oubli de `sid` : la session qui le lance n'en devient
    pas l'auteur, et un souvenir remis comme avant ne porte plus `sid`."""
    brain._oubli = sid
    for nid, _ in p["retirer"]:
        brain.remove(nid, purge=purge)
    for nid, restore, _ in p["annuler"]:
        n = brain.update(nid, **_fields(brain.nodes[nid], restore))
        meta = dict(n.get("meta") or {})
        meta["sessions"] = [x for x in provenance.sessions_of(n) if x != sid]
        if not meta["sessions"]:
            meta.pop("sessions")
        n["meta"] = meta


def _title(brain, nid) -> str:
    n = brain.nodes.get(nid) or {}
    return short(n.get("title") or "?", 70)


def show_plan(brain, sid, p, purge) -> None:
    if p["retirer"]:
        print(f"À retirer — créés par cette seule session ({'supprimés définitivement' if purge else 'archivés, réversible'}) :")
        for nid, note in p["retirer"]:
            print(f"  - `{nid}` — {_title(brain, nid)}{note}")
    if p["annuler"]:
        print("À remettre comme avant — seule cette session les a changés, personne depuis :")
        for nid, restore, note in p["annuler"]:
            cur = provenance.snap(brain.nodes[nid])
            print(f"  - `{nid}` — {_title(brain, nid)} : {provenance.change_text(cur, restore)}{note}")
    if p["garder"]:
        print("Gardés — une autre écriture s'en sert, ou le journal ne permet pas de revenir :")
        for nid, why in p["garder"]:
            print(f"  - `{nid}` — {_title(brain, nid)} : {why}")
    if p["partis"]:
        print("Supprimés définitivement depuis (plus rien à remettre ; un instantané : `brain history`) : "
              + ", ".join(f"`{x}`" for x in p["partis"]))


def list_sessions(brain, sessions) -> None:
    if not sessions:
        print("Aucune session notée : la session qui écrit (CLAUDE_CODE_SESSION_ID, donné par Claude Code) n'est notée "
              "que depuis cette version ; rien d'avant, ni rien d'écrit hors de Claude Code, n'est attribué à une session.")
        return
    here = provenance.current()
    print("Sessions qui ont écrit dans le cerveau (les plus récentes d'abord) :")
    for sid, k in sorted(sessions.items(), key=lambda x: x[1]["a"] or "", reverse=True)[:12]:
        when = f"{fmt_date(k['de'])[:5]} {k['de'][11:16]} → {fmt_date(k['a'])[:5]} {k['a'][11:16]}" if k["a"] else \
            "rien au journal de ce PC"
        print(f"  {sid} · {when} · {k['ajout']} créé(s), {k['modif']} modification(s), {len(k['ids'])} souvenir(s)"
              + ("  (celle-ci)" if sid == here else ""))
    print(f"`{CMD} oublier-session <id>` (le début de l'id suffit, « . » = celle-ci) montre ce qui serait retiré.")


def cmd_oublier_session(a):
    rows = provenance.rows()
    b = Brain.load()
    sessions = known(b, rows)
    if not a.id:
        return list_sessions(b, sessions)
    sid, err = resolve(a.id, sessions)
    if err:
        die(err)
    p = plan(b, sid, rows, a.purge)
    if not any(p.values()):
        print(f"Rien d'écrit par la session {sid} dans ce cerveau (ou déjà oublié). "
              f"`{CMD} oublier-session` liste les sessions notées.")
        return
    print(f"Session {sid} :")
    if not a.oui:
        show_plan(b, sid, p, a.purge)
        if p["retirer"] or p["annuler"]:
            print(f"Rien n'est fait sans accord : `{CMD} oublier-session {sid} --oui{' --purge' if a.purge else ''}` "
                  f"(un instantané est pris avant : `{CMD} restore 1` annule).")
        return
    if not (p["retirer"] or p["annuler"]):
        show_plan(b, sid, p, a.purge)
        print("Rien à retirer ni à remettre : tout ce qu'elle a écrit est gardé.")
        return
    from . import history
    history.snapshot("avant-oubli-session", force=True)
    with Brain.edit() as b:
        p = plan(b, sid, provenance.rows(), a.purge)  # sous verrou : l'état a pu changer depuis l'aperçu
        show_plan(b, sid, p, a.purge)
        apply(b, sid, p, purge=a.purge)
    refresh_views()
    print(f"✓ {len(p['retirer'])} {'supprimé(s) définitivement' if a.purge else 'archivé(s)'}, "
          f"{len(p['annuler'])} remis comme avant, {len(p['garder'])} gardé(s) — annulable : `{CMD} restore 1`")

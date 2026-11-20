"""Apprentissage — le cerveau apprend de ce qui se passe dans les sessions. La détection ne coûte aucun token (lecture
locale des transcripts, du journal et des compteurs) ; seul ce qui demande du jugement arrive devant un modèle.

Quatre sources :
- **erreurs résolues** : une commande qui échoue, puis la même commande lancée autrement qui réussit. Jointe au rappel
  de fin de tâche quand il a lieu (Claude juge sur le moment si c'est un piège durable), sinon gardée pour le dossier ;
- **usage des skills** : une skill chargée sans que le réflexe l'ait soufflée → le message d'avant est un déclencheur
  manqué. Deux messages qui partagent une tournure : le déclencheur est appris tout seul (`skills.triggers`), annoncé une
  fois, retirable (`brain apprendre oublier`). Une skill soufflée souvent et jamais suivie est signalée ;
- **méthodes répétées** : la même demande dans plusieurs sessions, sur plusieurs jours → skill candidate ;
- **retours pour le plugin** : pannes des hooks, hooks lents, précision du réflexe — des compteurs, jamais de texte de
  session (`brain apprendre retours` ; partagés avec le propriétaire du plugin si l'utilisateur l'a accepté).

Le dossier d'apprentissage (`brain apprendre`) réunit ce qui reste à trancher, avec la commande de chaque point ; une
ligne 🎓 au démarrage (au plus une fois par jour, à partir de `apprendre.min_items` points) le confie à l'agent
`cerveau:archiviste` (modèle moins cher, contexte à part). `brain apprendre --fait` le clôt.

Python seul, sur toutes les plateformes (voir plus.py)."""
from __future__ import annotations

import json
import os
import re
import sys
import time

from .common import (CMD, LOG_FILE, SESSIONS_DIR, STATE_DIR, FileLock, days_since, fmt_date, fold, load_config, log,
                     now_iso, read_json, short, tokenize, update_config, write_json)

FILE = STATE_DIR / "apprendre.json"
MARK = ".cerveau-appris"  # dans ~/.claude/skills/<nom>/ : skill rédigée par le cerveau (partageable après accord)
WINDOW = 12   # une réussite compte pour une erreur vue au plus 12 appels d'outils avant
KEEP = 40     # entrées gardées par liste
# Échecs qui n'apprennent rien : commandes d'exploration (leur code de sortie non nul est une réponse, pas une panne).
_PROBE = {"ls", "dir", "cat", "type", "head", "tail", "grep", "rg", "find", "test", "[", "which", "where", "command",
          "wc", "stat", "diff", "cd", "echo", "true", "false", "file", "pwd", "sed", "awk", "sort", "uniq", "cut", "tr",
          "get-content", "gc", "select-string", "get-childitem", "test-path", "get-command", "timeout", "sleep", "kill"}
_PROBE_GIT = ("git status", "git diff", "git log", "git show", "git grep", "git branch", "git rev-parse", "git ls-files",
              "git remote", "git config", "git tag", "git blame", "git merge-base", "git check-ignore")
_DENIED = re.compile(r"doesn't want to proceed|was rejected|permission to use|user denied|interrupted by user|"
                     r"request interrupted|requires approval|hook (?:blocked|denied)|operation was aborted", re.I)
_EXIT = re.compile(r"^\s*(?:error:\s*)?exit code \d+\s*$", re.I)
# Mots trop courants dans une demande pour désigner une skill à eux seuls.
_COMMON = {fold(w) for w in """aide aider besoin nouveau nouvelle nouveaux petit petite grand grande cree creer ecris ecrire
genere generer ajoute ajouter modifie modifier projet projets fichier fichiers code version exemple moment rapide
rapidement simple possible faudrait voudrais aimerais peux pourrais regarde regarder montre montrer prends prendre
utilise utiliser lance lancer travail travailler suite ensuite maintenant help need create make write want would could
please using with from that this""".split()}


# ------------------------------------------------------------------------------------------ fichier d'état
def load() -> dict:
    d = read_json(FILE, {}) or {}
    return d if isinstance(d, dict) else {}


def _edit(change) -> dict:
    """Relit, modifie et réécrit state/apprendre.json sous verrou (hooks et tâches de fond l'écrivent en même temps)."""
    with FileLock(str(FILE) + ".lock", timeout=2.0, stale=15.0, strict=False):
        d = load()
        change(d)
        write_json(FILE, d)
    return d


def settings(cfg=None) -> dict:
    d = (cfg or load_config()).get("apprendre")
    return d if isinstance(d, dict) else {}


def enabled(cfg=None) -> bool:
    return bool(settings(cfg).get("enabled", True))


# ------------------------------------------------------------------------------------------ lecture du transcript
def _clean(text, n=160) -> str:
    """Texte gardé : sans secret ni coordonnées, sur une ligne."""
    from .privacy import redact_contacts
    return short(redact_contacts(" ".join(str(text or "").split())), n)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") \
        if isinstance(content, list) else ""


def _error_line(text) -> str:
    """La première ligne qui dit l'erreur (pas « Exit code 1 »)."""
    for line in str(text or "").splitlines():
        if line.strip() and not _EXIT.match(line):
            return line.strip()
    return ""


def _programs(command) -> list:
    """Programmes d'une ligne de commande (« npm install && npm run build » → npm install, npm run build), sans les
    commandes d'exploration : leur code de sortie non nul est une réponse, pas une panne."""
    from .compact import _SPLIT, program
    out = []
    for part in _SPLIT.split(str(command or "")):
        name = program(part)
        low = name.lower()
        words = low.split()
        if words and os.path.basename(words[0]).removesuffix(".exe") not in _PROBE and not low.startswith(_PROBE_GIT) \
                and name not in out:
            out.append(name)
    return out


def _is_human(o, text) -> bool:
    from .journal import AUTO_RE
    turn = o.get("turnOrigin")
    human = turn == "human" if turn else (o.get("origin") or {}).get("kind", "human") == "human"
    return human and not AUTO_RE.match(text)


def _consume(st, o, found) -> None:
    if not isinstance(o, dict) or o.get("isSidechain"):
        return
    typ = o.get("type")
    content = (o.get("message") or {}).get("content")
    calls = st.setdefault("ap_calls", {})
    if typ == "assistant":
        for b in content if isinstance(content, list) else ():
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            st["ap_i"] = st.get("ap_i", 0) + 1
            name, inp = b.get("name") or "", b.get("input") if isinstance(b.get("input"), dict) else {}
            if name in ("Bash", "PowerShell") and isinstance(inp.get("command"), str) and b.get("id"):
                calls[b["id"]] = [inp["command"][:600], st["ap_i"]]
                for k in list(calls)[:-30]:  # appels restés sans résultat (interrompus) : pas gardés indéfiniment
                    calls.pop(k, None)
            elif name == "Skill" and inp.get("skill"):
                found["skills"].append((str(inp["skill"])[:80], st.get("ap_last") or ""))
            elif name == "Read" and "/skills/" in str(inp.get("file_path") or "").replace("\\", "/"):
                found["lues"].append(str(inp["file_path"]).replace("\\", "/"))
        return
    if typ != "user" or o.get("isMeta"):
        return
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        fails = st.setdefault("ap_fails", [])
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            call = calls.pop(b.get("tool_use_id"), None)
            if not call:
                continue
            cmd, i = call
            progs = _programs(cmd)
            if not progs:
                continue
            if b.get("is_error"):
                text = _result_text(b.get("content"))
                if not _DENIED.search(text[:600]):
                    fails.append({"p": progs, "c": cmd, "e": _error_line(text), "i": i})
                    del fails[:-10]
                continue
            for f in reversed(fails):  # réussite : résout l'échec récent d'un même programme, lancé autrement
                shared = [x for x in f["p"] if x in progs]
                if shared and i - f["i"] <= WINDOW and " ".join(f["c"].split()) != " ".join(cmd.split()):
                    found["erreurs"].append({"p": shared[0], "a": _clean(f["c"], 150), "err": _clean(f["e"], 140),
                                             "b": _clean(cmd, 150)})
                    fails.remove(f)
                    break
        return
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if isinstance(content, str) and content.strip() and not o.get("isCompactSummary"):
        from .journal import clean_prompt
        text = clean_prompt(content, 300, pasted=False)
        if text and _is_human(o, text):
            st["ap_last"] = text


def scan(path, st) -> dict:
    """Lecture incrémentale du transcript (reprend à st["ap_off"]) → {"erreurs": [paires échec → réussite], "skills":
    [(skill chargée, message d'avant)], "lues": [SKILL.md lus avec Read]}. `st` : état « plus » de la session."""
    found = {"erreurs": [], "skills": [], "lues": []}
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return found
    if size < st.get("ap_off", 0):  # transcript réécrit : on repart du début
        for k in ("ap_off", "ap_calls", "ap_fails", "ap_i", "ap_last"):
            st.pop(k, None)
    try:
        fh = open(path, "rb")
    except OSError:
        return found
    with fh:
        fh.seek(st.get("ap_off", 0))
        for raw in fh:
            if not raw.endswith(b"\n"):
                break  # ligne en cours d'écriture
            st["ap_off"] = st.get("ap_off", 0) + len(raw)
            if b'"tool_use"' not in raw and b'"tool_result"' not in raw and b'"user"' not in raw:
                continue
            try:
                _consume(st, json.loads(raw), found)
            except Exception:  # ligne inattendue : jamais bloquer la lecture
                continue
    return found


def _key(pair) -> str:
    return fold(pair["p"]) + "|" + re.sub(r"[\d/\\:.\-_'\"]+", " ", fold(pair["err"]))[:60].strip()


def _hinted(sid) -> set:
    """Skills que le réflexe principal a soufflées dans cette session (état du hook principal, lu seulement)."""
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "-_")[:80] or "anon"
    st = read_json(SESSIONS_DIR / f"{safe}.json", {}) or {}
    return set(st.get("skills_hinted") or [])


def _absorb(sid, st, found) -> None:
    """Range ce que la lecture vient de trouver : erreurs résolues en attente dans la session, déclencheurs manqués et
    skills reçues suivies dans les fichiers d'état."""
    seen = set(st.get("ap_vues") or [])
    for pair in found["erreurs"]:
        k = _key(pair)
        if k not in seen:
            seen.add(k)
            st.setdefault("ap_attente", []).append(pair)
    st["ap_vues"] = sorted(seen)[-60:]
    if found["skills"]:
        hinted = _hinted(sid) | set(st.get("recues") or [])
        missed = []
        for skill, msg in found["skills"]:
            typed = fold(msg).lstrip().startswith("/") or fold(skill.rpartition(":")[2]) in fold(msg)
            if skill in hinted or not msg or typed or skill.rpartition(":")[2] == "brain":
                continue  # soufflée, tapée en commande, ou nommée par l'utilisateur : rien à apprendre
            missed.append({"skill": skill, "msg": _clean(msg, 220), "le": now_iso()})
        if missed:
            def change(d):
                rows = d.setdefault("declencheurs", [])
                have = {(r.get("skill"), fold(r.get("msg", ""))) for r in rows}
                rows += [m for m in missed if (m["skill"], fold(m["msg"])) not in have]
                del rows[:-KEEP]
            _edit(change)
    if found["lues"]:
        try:
            from . import echange
            echange.followed(found["lues"])
        except Exception as exc:
            log(f"apprendre (skills reçues suivies) : {exc!r}")


# ------------------------------------------------------------------------------------------ hooks (via plus.py)
def stop_phrase(pairs) -> str:
    rows = " · ".join(f"`{p['a']}` échouait" + (f" (« {p['err']} »)" if p["err"] else "") + f" → `{p['b']}` a marché"
                      for p in pairs)
    return (f"Erreur(s) résolue(s) repérée(s) dans cette session : {rows}. Si c'est un piège durable, l'enregistrer "
            "(`add -t learning`, cause et solution) ; sinon ne rien noter.")


def on_stop(data, cfg=None, blocking=False) -> str:
    """Fin de tour : lecture de ce qui s'est ajouté au transcript. `blocking` : le rappel de fin de tâche a lieu → la
    phrase des erreurs résolues à lui joindre (elles ne seront pas redites), sinon ''."""
    cfg = cfg or load_config()
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not enabled(cfg) or not sid or not tp:
        return ""
    from . import plus
    st = plus.load_state(sid)
    _absorb(sid, st, scan(tp, st))
    out = ""
    if blocking and st.get("ap_attente"):
        out = stop_phrase(st["ap_attente"][:2])
        st["ap_attente"] = st["ap_attente"][2:]
    plus.save_state(sid, st)
    return out


def on_session_end(data, cfg=None) -> None:
    """Fin de session : dernière lecture ; les erreurs résolues jamais montrées vont au dossier ; entretien du jour en
    arrière-plan (déclencheurs appris, compte du dossier)."""
    cfg = cfg or load_config()
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not enabled(cfg):
        return
    if sid and tp:
        from . import plus
        st = plus.load_state(sid)
        _absorb(sid, st, scan(tp, st))
        left = st.pop("ap_attente", None) or []
        plus.save_state(sid, st)
        if left:
            def change(d):
                rows = d.setdefault("erreurs", [])
                have = {r.get("k") for r in rows}
                rows += [{**p, "k": _key(p), "le": now_iso()} for p in left if _key(p) not in have]
                del rows[:-KEEP]
            _edit(change)
    if days_since(load().get("entretien_le")) >= 1:
        _edit(lambda d: d.update(entretien_le=now_iso()))  # jour réservé : une autre session n'en lance pas un 2e
        from .hooks import spawn_background
        spawn_background(["apprendre", "--entretien"])


# ------------------------------------------------------------------------------------------ déclencheurs appris
def _words(msg) -> list:
    """[(mot d'origine, sa forme cherchable)] des mots porteurs d'un message, dans l'ordre."""
    from .lexicon import root
    out = []
    for w in re.findall(r"[^\W\d_]{3,}", str(msg or "")):
        t = tokenize(w)
        if t and len(t[0]) >= 4 and t[0] not in _COMMON:
            r = root(t[0])  # « relance » et « relancer », « facture » et « factures » : le même mot
            out.append((w.lower(), r if len(r) >= 4 else t[0]))
    return out


def common_phrase(msgs) -> str:
    """La tournure que partagent au moins deux messages : 2 ou 3 mots porteurs communs, dans l'ordre du premier message
    qui les contient tous ('' s'il n'y en a pas deux)."""
    sets = [dict((t, w) for w, t in _words(m)) for m in msgs]
    best = ""
    for i, a in enumerate(sets):
        for b in sets[i + 1:]:
            shared = [t for t in a if t in b]
            if len(shared) >= 2:
                phrase = " ".join(a[t] for t in shared[:3])
                if len(phrase) > len(best):
                    best = phrase
    return best


def learn_triggers(cfg=None) -> list:
    """Pour chaque skill chargée au moins deux fois sans avoir été soufflée : si ses messages partagent une tournure qui
    ne désigne aucune autre skill, elle devient un déclencheur (config `skills.triggers`). → [(skill, tournure)]."""
    cfg = cfg or load_config()
    if not enabled(cfg) or not settings(cfg).get("declencheurs_auto", True):
        return []
    d = load()
    refused = {(r.get("skill"), fold(r.get("phrase", ""))) for r in d.get("oublies") or []}
    groups = {}
    for r in d.get("declencheurs") or []:
        if not r.get("fait"):
            groups.setdefault(r.get("skill"), []).append(r.get("msg") or "")
    if not any(len(set(v)) >= 2 for v in groups.values()):
        return []
    from . import skills
    kc = cfg.get("skills") or {}
    catalog = skills.index(None, kc)
    names = {s["name"] for s in catalog}
    learned = []
    for skill, msgs in sorted(groups.items()):
        msgs = list(dict.fromkeys(msgs))
        if skill not in names or len(msgs) < 2:
            continue
        phrase = common_phrase(msgs)
        g = skills.phrase_groups(phrase) if phrase else []
        if not phrase or (skill, fold(phrase)) in refused or len(g) < 2 or not skills.usable(g):
            continue
        trig = skills._trigger(phrase, g)
        if sum(1 for m in msgs if skills.trigger_hit(trig, skills.Query(m))) < 2:
            continue
        if any(r["strong"] and r["name"] != skill for r in skills.match(phrase, catalog)):
            continue  # la tournure désigne déjà une autre skill : pas de déclencheur ambigu
        learned.append((skill, phrase))
    if not learned:
        return []

    def change(c):
        trig = c.setdefault("skills", {}).setdefault("triggers", {})
        for skill, phrase in learned:
            cur = trig.setdefault(skill, [])
            if phrase not in cur:
                cur.append(phrase)
    update_config(change)

    def note(d):
        rows = d.setdefault("appris", [])
        for skill, phrase in learned:
            rows.append({"skill": skill, "phrase": phrase, "le": now_iso()})
            for r in d.get("declencheurs") or []:
                if r.get("skill") == skill:
                    r["fait"] = True
        del rows[:-KEEP]
    _edit(note)
    for skill, phrase in learned:
        announce(f"🎓 Déclencheur appris pour la skill `{skill}` : « {phrase} » (deux de tes messages l'ont chargée sans "
                 f"que le cerveau la propose) · le retirer : `{CMD} apprendre oublier {skill} \"{phrase}\"`")
    return learned


def forget(skill, phrase) -> str:
    """`brain apprendre oublier <skill> "tournure"` : retire un déclencheur appris et ne le réapprend plus."""
    phrase = " ".join(str(phrase or "").split())
    gone = []

    def change(c):
        trig = (c.get("skills") or {}).get("triggers") or {}
        cur = trig.get(skill) or []
        keep = [p for p in cur if fold(p) != fold(phrase)]
        if len(keep) != len(cur):
            gone.append(phrase)
            if keep:
                trig[skill] = keep
            else:
                trig.pop(skill, None)
    update_config(change)

    def note(d):
        rows = d.setdefault("oublies", [])
        if not any(r.get("skill") == skill and fold(r.get("phrase", "")) == fold(phrase) for r in rows):
            rows.append({"skill": skill, "phrase": phrase, "le": now_iso()})
        d["appris"] = [r for r in d.get("appris") or []
                       if not (r.get("skill") == skill and fold(r.get("phrase", "")) == fold(phrase))]
    _edit(note)
    return (f"✓ « {phrase} » retiré des déclencheurs de `{skill}`" if gone else f"· « {phrase} » n'était pas un déclencheur "
            f"de `{skill}`") + " ; il ne sera plus appris pour cette skill"


# ------------------------------------------------------------------------------------------ skills jamais suivies
def idle_skills(min_hints=5) -> list:
    """Skills soufflées au moins `min_hints` fois et jamais chargées ensuite → [(nom, soufflée)]."""
    from .skills import load_stats
    return sorted(((n, s.get("hinted", 0)) for n, s in load_stats().items()
                   if isinstance(s, dict) and s.get("hinted", 0) >= min_hints and not s.get("used")
                   and not s.get("used_after_hint")), key=lambda x: -x[1])


# ------------------------------------------------------------------------------------------ méthodes répétées
def methods(days=30, min_sessions=3, catalog=None) -> list:
    """Demandes qui reviennent : même première demande (mots proches) dans au moins `min_sessions` sessions de travail
    (8 appels d'outils et plus), sur au moins deux jours, et qu'aucune skill ne couvre déjà.
    → [{"exemple", "sessions": n, "jours": [dates], "projet"}], les plus fréquentes d'abord."""
    from . import journal
    rows = []
    for s in journal.load()["sessions"].values():
        text = s.get("first") or ""
        toks = set(tokenize(text))
        if days_since(s.get("end")) > days or (s.get("tools") or 0) < 8 or len(toks) < 3 or text.startswith("/"):
            continue
        rows.append((s.get("end") or "", text, toks, s.get("project")))
    rows.sort()
    clusters = []
    for end, text, toks, proj in rows:
        for c in clusters:
            if len(toks & c["toks"]) / len(toks | c["toks"]) >= 0.5:
                c["items"].append((end, text, proj))
                c["toks"] &= toks  # le cœur commun de la demande
                break
        else:
            clusters.append({"toks": set(toks), "items": [(end, text, proj)]})
    out = []
    for c in clusters:
        days_seen = sorted({e[:10] for e, _, _ in c["items"] if e})
        if len(c["items"]) < min_sessions or len(days_seen) < 2 or len(c["toks"]) < 2:
            continue
        example = c["items"][-1][1]
        if catalog is not None:
            from . import skills
            if any(r["strong"] for r in skills.match(example, catalog)):
                continue  # une skill s'en charge déjà
        projs = [p for _, _, p in c["items"] if p]
        out.append({"exemple": example, "sessions": len(c["items"]), "jours": days_seen[-4:],
                    "projet": max(set(projs), key=projs.count) if projs else None,
                    "mots": " ".join(sorted(c["toks"])[:5])})
    return sorted(out, key=lambda m: -m["sessions"])


# ------------------------------------------------------------------------------------------ dossier d'apprentissage
def _open(rows):
    return [r for r in rows or [] if isinstance(r, dict) and not r.get("fait")]


def dossier(cfg=None, with_methods=True) -> tuple:
    """→ (texte du dossier, nombre de points à trancher)."""
    cfg = cfg or load_config()
    d = load()
    errs, trigs = _open(d.get("erreurs")), _open(d.get("declencheurs"))
    idle = [r for r in idle_skills() if r[0] not in set(d.get("idle_vues") or [])]
    meths = []
    if with_methods:
        try:
            from . import skills
            done = {fold(x) for x in d.get("methodes_vues") or []}
            meths = [m for m in methods(catalog=skills.index(None, cfg.get("skills") or {})) if fold(m["mots"]) not in done]
        except Exception as exc:
            log(f"apprendre (méthodes) : {exc!r}")
    n = len(errs) + len(trigs) + len(idle) + len(meths)
    L = [f"# 🎓 Apprentissage du cerveau — {fmt_date(now_iso())}", "",
         f"_{n} point(s). Appliquer ce qui est sûr avec la commande indiquée, laisser un doute et le citer, ne jamais "
         f"inventer un fait ; terminer par `{CMD} apprendre --fait`._", ""]
    sections = [
        ("Erreurs résolues (pièges à mémoriser s'ils sont durables)",
         [f"{fmt_date(r.get('le'))} `{r['a']}` échouait" + (f" (« {r['err']} »)" if r.get("err") else "")
          + f" → `{r['b']}` a marché → si c'est un piège qui reviendra : `add -t learning -T \"…\" -b \"cause + solution\"`"
          for r in errs]),
        ("Déclencheurs manqués (skill chargée sans que le cerveau la propose)",
         [f"`{r['skill']}` après « {r['msg']} » → si une tournure de 2 à 5 mots du message la désigne : "
          f"`skill trig {r['skill']} \"tournure\"`" for r in trigs]),
        ("Skills soufflées sans jamais servir (déclencheur trop large ?)",
         [f"`{name}` soufflée {k} fois, jamais chargée → voir ses phrases (`skill trig {name}`) ; si elle gêne, l'écarter "
          f"du réflexe (`config skills.exclude`, en gardant « brain »)" for name, k in idle]),
        ("Méthodes répétées (à transformer en skill)",
         [f"« {short(m['exemple'], 160)} » — {m['sessions']} sessions ({', '.join(fmt_date(x) for x in m['jours'])})"
          + (f", projet `{m['projet']}`" if m["projet"] else "")
          + f" → si c'est bien la même méthode : étapes d'après `journal -s \"{m['mots']}\"`, puis "
            f"`apprendre skill <nom> -d \"À utiliser quand… « déclencheur »… Ne pas utiliser pour…\" --body-file <fichier>`"
          for m in meths]),
    ]
    for title, rows in sections:
        if rows:
            L += [f"## {title}", ""] + [f"- {r}" for r in rows] + [""]
    if not n:
        L.append("Rien à trancher : le cerveau n'a rien appris de nouveau qui demande un avis.")
    return "\n".join(L).rstrip() + "\n", n


def done() -> str:
    """`brain apprendre --fait` : les points montrés sont clos (ils ne reviendront pas)."""
    cfg = load_config()
    idle = [n for n, _ in idle_skills()]
    try:
        from . import skills
        meths = [m["mots"] for m in methods(catalog=skills.index(None, cfg.get("skills") or {}))]
    except Exception:
        meths = []

    def change(d):
        for key in ("erreurs", "declencheurs"):
            for r in d.get(key) or []:
                if isinstance(r, dict):
                    r["fait"] = True
        d["idle_vues"] = sorted(set(d.get("idle_vues") or []) | set(idle))
        d["methodes_vues"] = (list(d.get("methodes_vues") or []) + meths)[-KEEP:]
        d.update(fait_le=now_iso(), attente=0, notifie_le=None)
    _edit(change)
    return "✓ dossier d'apprentissage clos"


def upkeep() -> str:
    """Entretien du jour (arrière-plan, zéro token) : déclencheurs appris, puis compte du dossier pour la ligne 🎓."""
    cfg = load_config()
    learned = learn_triggers(cfg)
    _, n = dossier(cfg)
    _edit(lambda d: d.update(attente=n, entretien_le=now_iso()))
    return f"✓ entretien de l'apprentissage : {len(learned)} déclencheur(s) appris, {n} point(s) au dossier"


def notice(cfg=None, take=None) -> str:
    """Lignes 🎓 du démarrage : annonces en attente, et — au plus une fois par jour — le dossier quand il compte assez
    de points. `take(ligne)` : la ligne tient-elle sous le plafond de contexte du hook ? Une ligne refusée n'est pas
    notée comme montrée : elle attend le prochain démarrage."""
    cfg = cfg or load_config()
    a = settings(cfg)
    if not enabled(cfg) or not a.get("notice", True):
        return ""
    take = take or (lambda line: True)
    d = load()
    lines = take_annonces(take)
    n = int(d.get("attente") or 0)
    if n >= int(a.get("min_items", 3)) and days_since(d.get("notifie_le")) >= 1:
        from . import delegation
        agent = "archiviste" in delegation.available() and delegation.mode(cfg) != "off"
        who = (f"confie-le en arrière-plan à l'agent `{delegation.call_name('archiviste')}` (modèle moins cher, contexte à part)"
               if agent else "traite-le toi-même")
        line = (f"🎓 Apprentissage du cerveau : {n} point(s) à trancher (erreurs résolues, déclencheurs manqués, "
                f"méthodes répétées). Après la première demande de l'utilisateur, {who} : `{CMD} apprendre`, appliquer "
                f"ce qui est sûr, laisser un doute et le citer, terminer par `{CMD} apprendre --fait` ; dire en une "
                "ligne ce qui a été fait.")
        if take(line):
            _edit(lambda x: x.update(notifie_le=now_iso()))
            lines.append(line)
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------ annonces
def announce(text) -> None:
    def change(d):
        rows = d.setdefault("annonces", [])
        if text not in rows:
            rows.append(text)
        del rows[:-6]
    _edit(change)


def take_annonces(take=None) -> list:
    """Les annonces en attente (déclencheur appris, skill reçue…), montrées une seule fois → celles que `take` accepte
    (place sous le plafond de contexte du hook) ; les autres attendent le prochain message."""
    rows = [x for x in load().get("annonces") or [] if isinstance(x, str) and x]
    if not rows:
        return []
    shown = []
    for text in rows:
        line = f"{text} (dis-le à l'utilisateur en une phrase au début de ta réponse)"
        if take is None or take(line):
            shown.append((text, line))
    if shown:
        gone = {text for text, _ in shown}
        _edit(lambda d: d.update(annonces=[x for x in d.get("annonces") or [] if x not in gone]))
    return [line for _, line in shown]


# ------------------------------------------------------------------------------------------ skill apprise
def learned_skill(name, description, body="", force=False, memory=True, scripts=()) -> list:
    """`brain apprendre skill <nom> -d … --body-file … [--script outil.py]` : skill personnelle rédigée par le cerveau
    (marquée « apprise » : elle part dans l'échange avec les amis si l'utilisateur a accepté d'envoyer). `scripts` :
    fichiers copiés dans son dossier `scripts/` — ses outils ; chez un ami, ils attendront son accord.
    → lignes de compte rendu."""
    import shutil
    from pathlib import Path
    from . import skills
    from .echange import MAX_FILE, SCRIPT_EXT, safe_rel
    files = [Path(x) for x in scripts or ()]
    for f in files:  # tout est vérifié avant de créer quoi que ce soit
        if not f.is_file():
            raise ValueError(f"script introuvable : {f}")
        if f.suffix.lower() not in SCRIPT_EXT:
            raise ValueError(f"{f.name} : type de script non pris en charge ({', '.join(SCRIPT_EXT)})")
        if not safe_rel(f.name):
            raise ValueError(f"{f.name} : nom de fichier à simplifier (lettres sans accent, chiffres, tirets, points ; "
                             "pas un nom réservé par Windows)")
        if f.stat().st_size > MAX_FILE:
            raise ValueError(f"{f.name} : script trop gros ({f.stat().st_size // 1000} k, {MAX_FILE // 1000} k au plus)")
    path = skills.scaffold(name, description, (body or "").replace("\ufeff", ""), force=force)
    write_json(path.parent / MARK, {"le": now_iso()})
    out = [f"✓ skill apprise : {path}"]
    for f in files:
        (path.parent / "scripts").mkdir(exist_ok=True)
        shutil.copyfile(f, path.parent / "scripts" / f.name)
        out.append(f"✓ outil : scripts/{f.name}")
    for lvl, _n, m in skills.check(skills.index(None), only={path.parent.name}):
        out.append(f"  {lvl} {m}")
    if memory:
        try:
            from .store import Brain
            with Brain.edit() as b:
                node = b.add("reference", f"Skill apprise « {path.parent.name} »",
                             f"{' '.join(description.split())} Fichier : {path}. Rédigée par le cerveau d'après des "
                             "sessions ; se déclenche seule (réflexe de skills).", tags=["skill", path.parent.name],
                             source="auto")
            out.append(f"✓ fiche dans le cerveau : `{node['id']}`")
        except Exception as exc:
            log(f"apprendre (fiche de la skill) : {exc!r}")
    try:
        from . import echange
        line = echange.after_learned(path.parent.name)
        if line:
            out.append(line)
    except Exception as exc:
        log(f"apprendre (échange) : {exc!r}")
    return out


# ------------------------------------------------------------------------------------------ retours pour le plugin
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} ")
_FRAME = re.compile(r'File "[^"]*brainkit[/\\]([\w.]+)", line (\d+), in (\w+)')


def feedback(days=14) -> dict:
    """Compteurs techniques des `days` derniers jours, sans aucun texte de session ni chemin : version, système, pannes
    des hooks (événement, classe d'erreur, endroit dans le code du cerveau), hooks lents, précision du réflexe pour les
    skills du plugin, délégation."""
    from . import __version__
    cut = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    errors, slow = {}, {}
    records, cur = [], None
    for name in (LOG_FILE.with_suffix(".old.log"), LOG_FILE):
        try:
            with open(name, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if _STAMP.match(line):
                        cur = [line[:19], line[20:].rstrip("\n")]
                        records.append(cur)
                    elif cur is not None and len(cur) < 40:
                        cur.append(line.rstrip("\n"))
        except OSError:
            continue
    for rec in records:
        if rec[0] < cut:
            continue
        head = rec[1]
        m = re.match(r"hook ([\w-]+) lent", head)
        if m:
            slow[m.group(1)] = slow.get(m.group(1), 0) + 1
            continue
        m = re.match(r"hook ([\w-]+) ERREUR (\w+)", head) or re.match(r"(plus) \(([^)]{1,30})\)(?: ERREUR)? ?:? ?(\w+)?", head)
        if not m:
            continue
        frames = _FRAME.findall("\n".join(rec[2:]))
        where = f" ({frames[-1][0]}:{frames[-1][1]}:{frames[-1][2]})" if frames else ""
        sig = ":".join(x for x in m.groups() if x)[:80] + where
        errors[sig] = errors.get(sig, 0) + 1
    reflex = {}
    try:
        from .skills import OWN_PLUGIN, load_stats
        for name, s in load_stats().items():
            if isinstance(s, dict) and name.startswith(f"{OWN_PLUGIN}:") and s.get("hinted"):
                reflex[name] = [int(s.get("hinted") or 0), int(s.get("used_after_hint") or 0)]
    except Exception as exc:
        log(f"apprendre (retours, réflexe) : {exc!r}")
    try:
        from . import delegation
        deleg = {k: v for k, v in delegation.counters(days).items() if k != "types"}
    except Exception:
        deleg = {}
    system = "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"
    from .common import CODE_DIR
    engine = "rust" if os.name == "nt" and (CODE_DIR / "brain.exe").is_file() and os.environ.get("BRAIN_IMPL") == "rust" \
        else "python"  # brain.exe seulement sur demande (brain.py, rust_exe)
    return {"v": 1, "version": __version__, "systeme": system, "python": "%d.%d" % sys.version_info[:2], "moteur": engine,
            "jours": days, "le": now_iso()[:10], "pannes": dict(sorted(errors.items(), key=lambda x: -x[1])[:25]),
            "lents": slow, "reflexe": reflex, "delegation": deleg}


def clean_feedback(data) -> dict:
    """Retours techniques écrits par un autre cerveau, avant de les afficher : seulement des champs connus, des nombres
    bornés et des libellés au format attendu (jamais de texte libre) ; {} si ce n'en est pas."""
    if not isinstance(data, dict) or not data:
        return {}

    def num(v, top=1_000_000):
        return max(0, min(v, top)) if isinstance(v, int) and not isinstance(v, bool) else 0

    def text(v, rx, default="?"):
        return v if isinstance(v, str) and re.fullmatch(rx, v) else default

    def counts(v, rx, n):
        return {k: num(x) for k, x in list(v.items())[:n] if isinstance(k, str) and re.fullmatch(rx, k)} \
            if isinstance(v, dict) else {}

    reflex = {}
    for k, v in (list(data["reflexe"].items())[:60] if isinstance(data.get("reflexe"), dict) else ()):
        if isinstance(k, str) and re.fullmatch(r"[a-z0-9-]{1,64}:[a-z0-9-]{1,64}", k) and isinstance(v, (list, tuple)) and len(v) == 2:
            reflex[k] = [num(v[0]), num(v[1])]
    return {"v": 1, "version": text(data.get("version"), r"\d{1,3}\.\d{1,3}\.\d{1,3}"),
            "systeme": text(data.get("systeme"), r"windows|macos|linux"), "python": text(data.get("python"), r"\d\.\d{1,2}"),
            "moteur": text(data.get("moteur"), r"rust|python"), "jours": num(data.get("jours"), 365),
            "le": text(data.get("le"), r"\d{4}-\d{2}-\d{2}", None),
            "pannes": counts(data.get("pannes"), r"[\w-]{1,30}(?::[\w-]{1,40}){0,2}(?: \([\w.]{1,40}:\d{1,6}:\w{1,60}\))?", 25),
            "lents": counts(data.get("lents"), r"[\w-]{1,30}", 20), "reflexe": reflex,
            "delegation": counts(data.get("delegation"), r"[a-z_]{1,20}", 12)}


def feedback_text(days=14, data=None, who="") -> str:
    f = data or feedback(days)
    L = [f"🛠 Retours techniques{who} — cerveau {f.get('version')} · {f.get('systeme')} · Python {f.get('python')} · moteur "
         f"{f.get('moteur')} · {f.get('jours')} j (au {fmt_date(f.get('le'))})"]
    L.append("  pannes des hooks : " + (" · ".join(f"{k} ×{v}" for k, v in (f.get("pannes") or {}).items()) or "aucune"))
    if f.get("lents"):
        L.append("  hooks lents (> 2 s) : " + " · ".join(f"{k} ×{v}" for k, v in f["lents"].items()))
    weak = [(n, h, u) for n, (h, u) in (f.get("reflexe") or {}).items() if h >= 4 and u == 0]
    if weak:
        L.append("  skills soufflées jamais suivies : " + " · ".join(f"{n} ({h}×)" for n, h, _ in sorted(weak, key=lambda x: -x[1])[:8]))
    d = f.get("delegation") or {}
    if d.get("vus"):
        L.append(f"  délégation : {d.get('vus')} sous-agent(s) lancé(s), {d.get('haiku', 0)} envoyé(s) sur Haiku, "
                 f"{d.get('sonnet', 0)} sur Sonnet")
    return "\n".join(L)


# ------------------------------------------------------------------------------------------ commande
def status(cfg=None) -> str:
    cfg = cfg or load_config()
    d = load()
    L = [f"🎓 Apprentissage — {'actif' if enabled(cfg) else 'coupé (`config apprendre.enabled true`)'} · "
         f"{len(_open(d.get('erreurs')))} erreur(s) résolue(s) en attente · {len(_open(d.get('declencheurs')))} déclencheur(s) "
         f"manqué(s) · {len(d.get('appris') or [])} déclencheur(s) appris"]
    for r in (d.get("appris") or [])[-8:]:
        L.append(f"  + `{r.get('skill')}` : « {r.get('phrase')} » (appris le {fmt_date(r.get('le'))})")
    L.append(f"Dossier à trancher : `{CMD} apprendre` · retours techniques : `{CMD} apprendre retours` · skill apprise : "
             f"`{CMD} apprendre skill <nom> -d \"…\" --body-file f` · retirer un déclencheur : `{CMD} apprendre oublier <skill> \"…\"`")
    return "\n".join(L)

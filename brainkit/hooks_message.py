"""Hook UserPromptSubmit : alertes de taille du contexte, « retiens… » enregistré par le hook lui-même, puis le rappel
(hooks_rappel).

Découpé de hooks.py (étape 8 du plan) sans rien changer ; chargé seulement par un message."""
from __future__ import annotations

import json
import os
import re
import time

from . import journal
from .common import (CMD, commun_member, fold, log, now_iso, parse_iso, short, tokenize)
from .hooks import (CAPTURE_RX, REM_BLOCK_RX, REMEMBER_RX, TODO_PREFIX, _DEADLINE, _Later, _Rx, emit, load_state,
                    save_state)
from .hooks_rappel import recall_context
from .store import TYPES, Brain

search = _Later("search", "search", globals())  # chargé au premier usage, comme dans hooks


# ------------------------------------------------------------------------------------------ UserPromptSubmit
TAIL_BYTES = 256 * 1024  # fin du transcript lue pour la taille du contexte (élargie si la dernière réponse est plus grosse)


PAUSE_MIN_CTX = 100_000  # en dessous, relire la conversation après une pause coûte peu : pas d'alerte


def _epoch(value) -> float:
    d = parse_iso(value)
    return d.timestamp() if d else 0.0


def last_request(path) -> tuple:
    """Dernière requête de la conversation principale, lue dans la FIN du transcript → (taille du contexte en tokens :
    entrée + cache créé + cache lu, heure en secondes epoch ou 0, durée du cache vue dans les dernières écritures — 300
    ou 3600 s — ou 0). Les lignes d'une même réponse portent le même usage : jamais additionnées. (0, 0, 0) si
    introuvable ; aucune erreur ne remonte."""
    ctx, ts = 0, 0.0
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            for tail in (TAIL_BYTES, 4 * TAIL_BYTES, 16 * TAIL_BYTES):
                fh.seek(max(0, size - tail))
                lines = fh.read().split(b"\n")
                if size > tail:
                    lines = lines[1:]  # la première ligne est coupée
                for raw in reversed(lines):
                    if b'"usage"' not in raw or b'"assistant"' not in raw:
                        continue
                    try:
                        o = json.loads(raw)
                        u = o["message"]["usage"] if o.get("type") == "assistant" and not o.get("isSidechain") else None
                        total = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                   "cache_read_input_tokens")) if u else 0
                        cc = u.get("cache_creation") if total else None
                        h1 = int(cc.get("ephemeral_1h_input_tokens") or 0) if isinstance(cc, dict) else 0
                        m5 = int(cc.get("ephemeral_5m_input_tokens") or 0) if isinstance(cc, dict) else 0
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                    if not total:
                        continue
                    if not ctx:
                        ctx, ts = total, _epoch(o.get("timestamp"))
                    if h1 or m5:  # durée du cache : celle des dernières écritures
                        return ctx, ts, 3600 if h1 >= m5 else 300
                if ctx or size <= tail:
                    break
    except (OSError, TypeError, ValueError):
        pass
    return ctx, ts, 0


def last_context(path) -> int:
    """Taille du contexte (tokens) à la dernière requête de la conversation ; 0 si introuvable."""
    return last_request(path)[0]


def _cache_ttl() -> int:
    """Durée du cache de prompt (s) d'après les réglages, quand le transcript ne la montre pas : 1 h par défaut
    (abonnement, conversation principale), 5 min quand c'est demandé (variables d'environnement, promptCacheTtl)."""
    if os.environ.get("FORCE_PROMPT_CACHING_5M", "").strip().lower() not in ("", "0", "false"):
        return 300
    v = os.environ.get("CLAUDE_CODE_PROMPT_CACHE_TTL", "").strip().lower()
    if not v:
        try:
            from . import eco
            settings, _ = eco.read_settings()
            v = str(settings.get("promptCacheTtl") or "").strip().lower()
        except Exception:
            v = ""
    return 300 if v == "5m" else 3600


def _duree(sec) -> str:
    return f"{round(sec / 86400)} j" if sec >= 86400 else f"{round(sec / 3600)} h" if sec >= 3600 else f"{round(sec / 60)} min"


def pause_alert(size, ts, ttl=0, now=None) -> str:
    """Retour après une pause plus longue que la durée du cache, sur une grosse conversation : ce message relit tout au
    prix fort. Un message pour l'UTILISATEUR (zéro token pour Claude), ou ''."""
    if size < PAUSE_MIN_CTX or not ts:
        return ""
    gap = (now or time.time()) - ts
    if gap <= 300 or gap <= (ttl or _cache_ttl()):
        return ""
    return (f"⏸ Reprise après {_duree(gap)} : le cache a expiré, ce message relit toute la conversation "
            f"(≈{round(size / 1000)} k tokens) au prix fort. Après une pause, nouveau sujet → /clear d'abord (le cerveau "
            "garde l'essentiel).")


def context_alert(data, cfg) -> str:
    """Un message pour l'UTILISATEUR (`systemMessage`), jamais pour Claude — chaque message relit toute la conversation :
    reprise après une pause qui a vidé le cache (`eco.alerte_pause`), sinon palier suivant de `eco.alerte_contexte`
    (signalé une fois par session)."""
    ecfg = cfg.get("eco") or {}
    steps = sorted(int(x) for x in ecfg.get("alerte_contexte") or [] if isinstance(x, (int, float)))
    pause = ecfg.get("alerte_pause", True)
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not (steps or pause) or not sid or not tp:
        return ""
    size, ts, ttl = last_request(tp)
    note = pause_alert(size, ts, ttl) if pause else ""
    if not steps:
        return note
    reached = max((x for x in steps if size >= x), default=0)
    st = load_state(sid)
    done = st.get("eco_alerte", 0)
    if reached != done:
        st["eco_alerte"] = reached  # plus bas qu'avant (compaction, /clear) : les paliers se réarment
        save_state(sid, st)
        if reached > done and not note:
            note = (f"💡 Conversation à ≈{round(size / 1000)} k tokens : chaque message la relit en entier. Nouveau "
                    "sujet ? Tape /clear (le cerveau garde l'essentiel) ou /compact.")
    return note


# Demande explicite (« retiens que… ») : le hook l'enregistre lui-même.
REM_LEAD_RX = _Rx(r"(?:(?:ok|okay|bon|alors|donc|et|puis|aussi|dis|[ée]coute|stp|svp|please)\b[\s,;:!.\-–—]*)*", re.I)
REM_LINK_RX = _Rx(r"[\s,;:!\-–—]*(?:(?:bien|[çc]a|cela|ceci)\b[\s,;:!\-–—]*)*(?:(?:que\b|qu['’]|that\b|to\b)\s*)?", re.I)
REM_STATEMENT_RX = _Rx(r"\s*(?:qu(?:e\b|['’])|that\b|:)", re.I)  # « n'oublie pas que… » : un fait, pas un rappel
REM_OBJECT_RX = _Rx(r"\s*(?:qu(?:e\b|['’])|that\b|[çc]a\b|cela\b|ceci\b|bien\b|:)", re.I)
REM_ANAPHORA_RX = _Rx(r"(?:tout\s+)?ce\s+(?:que|qu['’]|qui)\b[^:]*:?", re.I)  # « retiens ce que je viens de dire »
REM_PRONOUN_RX = _Rx(r"\s*-\s*(?:le|la|les|moi|nous|lui|leur|y|en)\b", re.I)  # « retiens-le » : un pronom, pas un fait
REM_TITLE, REM_BODY, REM_MAX = 80, 600, 3  # car. du titre, du texte gardé ; phrases enregistrées par message


def remember_texts(raw) -> list:
    """Les phrases à retenir d'un message « retiens… » : celle du déclencheur, sans lui ni ses liaisons (« retiens que… »,
    « n'oublie pas de… »). Rien (Claude, lui, voit de quoi il s'agit) si le déclencheur n'ouvre pas la phrase (« ne retiens
    pas… »), si c'est une question, si rien ne suit ou si ça renvoie à autre chose (« retiens ça », « ce que je viens de
    dire »), si « n'oublie pas de… » ou « souviens-toi de… » ne sont qu'un rappel ou un appel au souvenir (il faut « que… »
    ou une règle : « toujours », « jamais »…), ou si « mémorise les résultats » parle de code.
    Un déclencheur suivi de « : » prend la suite du paragraphe (liste)."""
    out = []
    for para in re.split(r"\n\s*\n", REM_BLOCK_RX.sub(" ", str(raw)[:20000])):
        sents = [re.sub(r"^\s*(?:[-*•>]+|\d+[.)])\s*", "", x).strip() for x in re.split(r"(?<=[.!?…])\s+|\n", para)]
        sents = [x for x in sents if x]
        for i, sent in enumerate(sents):
            m = REMEMBER_RX.search(sent)
            head = sent[:m.start()].strip() if m else ""
            if not m or sent.endswith("?") or (head and not head.endswith((",", ";", ":")) and not REM_LEAD_RX.fullmatch(head)):
                continue
            end = m.end()
            while end < len(sent) and sent[end].isalpha():  # « mémoris » → « mémorise »
                end += 1
            word, tail = fold(m.group(0)).replace("’", "'"), sent[end:]
            todo = word.startswith("n'oublie") and re.match(r"\s+(?:de\s+|d['’])", tail) and re.search(_DEADLINE, tail, re.I)
            if REM_PRONOUN_RX.match(tail) or (word.startswith("memoris") and not REM_OBJECT_RX.match(tail)) \
                    or (word.startswith(("n'oublie", "souviens", "remember")) and not todo
                        and not (REM_STATEMENT_RX.match(tail) or CAPTURE_RX.search(tail))):
                continue
            tail = tail[REM_LINK_RX.match(tail).end():]
            if word.startswith(("n'oublie", "souviens")):
                tail = re.sub(r"^(?:de\b|d['’])\s*", "", tail, flags=re.I)
            text = f"{'' if REM_LEAD_RX.fullmatch(head) else head} {tail}"
            if todo:  # « n'oublie pas de relancer X avant jeudi » : un à-faire daté, pas un fait
                text = TODO_PREFIX + text.strip()
            if sent.endswith(":"):
                text += " ; ".join([""] + sents[i + 1:])
            text = " ".join(text.split()).strip(" ;,:-–—").rstrip(".!?… ")
            if REM_ANAPHORA_RX.match(text):  # ce que je viens de dire : toujours pnpm → ce qui suit les deux-points
                text = text.split(":", 1)[1].strip() if ":" in text else ""
            if len(tokenize(text, keep_stop=True)) >= 3 and text[:1].upper() + text[1:] not in out:
                out.append(text[:1].upper() + text[1:])
            if sent.endswith(":"):
                break
    return out[:REM_MAX]


# Vie privée d'un tiers (santé, famille, religion, politique, sexualité) : jamais enregistrée par le hook. La phrase
# n'est écartée que si elle parle de quelqu'un d'autre que l'utilisateur (un prénom, il/elle, « sa femme », « le client »…).
_PRIVATE_TOPICS = (
    ("santé", r"maternit|enceinte|grossesse|accouch|arret maladie|maladie|malade|cancer|depress|burn-?out|handicap|hospitalis|"
              r"chimio|psychiatr|sante mentale|seropositi|invalidite|fausse couche"),
    ("famille", r"divorc|deces\b|decede|obseques|enterrement|deuil"),
    ("religion", r"musulman|juif\b|juive|chretien|catholique|protestant|bouddhiste|hindou|athee|religion|religieu|ramadan"),
    ("politique", r"vote pour|votes? a (?:gauche|droite)|electeur|syndique|parti politique|extreme (?:droite|gauche)|"
                  r"opinions? politique|orientation politique"),
    ("sexualité", r"homosexuel|\bgay\b|lesbienne|bisexuel|transgenre|orientation sexuelle|coming out"),
)
_PRIVATE_RX = [(label, _Rx(rx)) for label, rx in _PRIVATE_TOPICS]
_OTHER_PERSON_RX = _Rx(
    r"\b(?:il|elle|ils|elles|son|sa|ses|leur|leurs|lui)\b|"
    r"\b(?:mon|ma|mes|notre|nos|le|la|un|une) (?:femme|mari|epouse|epoux|fils|fille|enfants?|bebe|frere|soeur|mere|pere|"
    r"parents?|copine|copain|compagne|compagnon|conjoint|collegue|client|cliente|patron|patronne|employe|employee|"
    r"salarie|salariee|stagiaire|voisin|voisine|ami|amie|cousin|cousine|oncle|tante|candidat|candidate)\b")
# Mots qu'une majuscule ne change pas en prénom : « jusqu'au 3 Décembre », « Lundi, je suis malade »
_NOT_A_NAME = {"janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
               "decembre", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "noel", "paques",
               "toussaint", "ascension", "pentecote"}


def private_about_other(text) -> str:
    """« santé », « religion »… si la phrase dit quelque chose de privé sur quelqu'un d'autre que l'utilisateur, sinon ''."""
    from .common import STOPWORDS
    f = fold(text)
    topic = next((label for label, rx in _PRIVATE_RX if rx.search(f)), "")
    if not topic:
        return ""
    words = re.findall(r"(?:^|(?<=\s))([A-ZÀ-Ý][a-zà-ÿ]{2,})\b(?!['’])", text)  # « J'ai », « Aujourd'hui » : pas des noms
    named = any(fold(w) not in STOPWORDS and fold(w) not in _NOT_A_NAME for w in words)
    return topic if named or _OTHER_PERSON_RX.search(f) else ""


def _known_already(b, text, title):
    """Un souvenir actif qui dit déjà la même chose avec d'autres mots (trouvé par l'index de recherche : au moins 4 mots
    de contenu en commun et 70 % de ceux de la phrase, aucun chiffre nouveau, aucun repère de temps différent, aucun
    changement de valeur) → son id, sinon None. Un fait dont la valeur change n'est pas un doublon : c'est une mise à jour.
    L'index est celui du cerveau tel qu'il a été lu (b.pinned_index, remember_now : memidx.bin, rien à reconstruire —
    avant, l'index entier était refait ici à chaque « retiens… », 220 ms à 3 000 souvenirs) ; les souvenirs déjà écrits
    ou modifiés par ce même message, qu'il ne contient pas encore, sont regardés en plus."""
    from . import reconcile
    toks = set(tokenize(text))
    if len(toks) < 4:
        return None
    nums = set(reconcile.NUM_RX.findall(text))
    found = [r["node"] for r in search.search_memories(b, text, limit=5, expand=False)]
    seen = {n["id"] for n in found}
    found += [b.nodes[i] for i in (getattr(b, "_avant", None) or ()) if i in b.nodes and i not in seen
              and b.nodes[i].get("status", "active") == "active"]
    for n in found:
        if n["type"] == "project" or n["id"].startswith("c--"):  # jamais une page d'ami
            continue
        old = f"{n['title']} {n.get('body', '')}"
        shared = toks & set(tokenize(old))
        if len(shared) < 4 or len(shared) / len(toks) < 0.7 or not nums <= set(reconcile.NUM_RX.findall(old)):
            continue
        sig = reconcile.signals(n, title, text)
        if not sig.get("autre événement") and not any(sig.get(k) for k in reconcile.VALUE_SIGNALS):
            return n["id"]
    return None


def _remember_one(b, text, cwd):
    """Un souvenir enregistré comme `brain add` : complète celui qui dit déjà ça, remplace celui dont la valeur change,
    sinon en crée un (à-faire si « n'oublie pas de… avant jeudi », règle si c'est une préférence, sinon fait du projet
    courant) ; un fait déjà là sous d'autres mots n'est pas enregistré deux fois.
    → (« new » | « merged » | « updated » | « known », id, type, titre)."""
    from . import reconcile
    from .common import fmt_date
    todo = text.startswith(TODO_PREFIX)
    text = text[len(TODO_PREFIX):] if todo else text
    text = text[:1].upper() + text[1:]
    ntype = "todo" if todo else "feedback" if CAPTURE_RX.search(text) else "fact"
    title, body = short(text, REM_TITLE), f"{short(text, REM_BODY)} (noté le {fmt_date(now_iso())})"
    proj = None if ntype == "feedback" else b.project_for_path(cwd)
    pid = proj["id"] if proj else None
    dec = reconcile.decide(b, ntype, title, text, pid)  # comparé sans la date : le même propos redit un autre jour = doublon
    if dec["action"] == "merge":
        old = dec["target"]
        has = fold(text) in fold(old.get("body", ""))
        b.update(old["id"], body=old.get("body", "") if has else f"{old.get('body', '')}\n{body}".strip())
        b.adjust_confidence(old["id"], +0.1)  # redit : un peu plus sûr
        return "merged", old["id"], old["type"], old["title"]
    if dec["action"] == "new" and not todo:
        known = _known_already(b, text, title)
        if known:
            return "known", known, ntype, b.nodes[known]["title"]
    node = b.add(ntype, title, body, project=pid, source="auto")
    if dec["action"] == "update":  # même sujet, valeur changée : l'ancien est archivé (consultable)
        b.supersede(node["id"], dec["target"]["id"])
        return "updated", node["id"], ntype, title
    return "new", node["id"], ntype, title


def remember_now(data, raw, keep=None):
    """Demande explicite (« retiens que… ») : enregistrée par le hook lui-même — zéro token, et rien n'est perdu si Claude
    oublie. Mêmes règles que `brain add` : anti-doublon (même reformulé), jamais de secret ni de vie privée d'un tiers (la
    phrase est alors écartée, et on le dit).
    → (la ligne pour Claude, la ligne vue par l'utilisateur) ; ('', '') si le hook ne peut pas s'en charger (Claude fait
    alors `add`, comme avant). `keep` (dict) : reçoit le cerveau tout juste enregistré (« brain »), que le rappel du même
    message reprend sans relire graph.json ni refaire l'index (search.memory_index, pinned_index).
    Le hook n'écrit que le souvenir, dans le fichier d'attente (attente.py : lu aussitôt par tous, journal des textes et
    recents.jsonl compris) ; la tâche de fond qu'il lance le fait entrer dans graph.json, puis refait l'index des
    souvenirs (memidx.bin) et les vues. Avant, le hook réécrivait graph.json et refaisait deux fois l'index : 0,6 s à
    3 000 souvenirs, 0,12 s désormais (étape 22 du plan)."""
    from .privacy import find
    found = {t: find(t) for t in remember_texts(raw)}
    leaks = sorted({x for v in found.values() for x in v})
    clean = [t for t, v in found.items() if not v]
    private = {t: private_about_other(t) for t in clean}
    texts = [t for t in clean if not private[t]]
    skipped = sorted({v for v in private.values() if v})
    done = []
    if texts and data.get("simulation"):  # `brain recall` : montrer sans enregistrer
        return "🧠 (simulation) serait enregistré tel quel : " + " · ".join(
            f"[{TYPES['todo' if t.startswith(TODO_PREFIX) else 'feedback' if CAPTURE_RX.search(t) else 'fact']}] "
            f"« {short(t.removeprefix(TODO_PREFIX), REM_TITLE)} »" for t in texts), ""
    if texts:
        with Brain.edit(timeout=2.5, defer=True) as b:  # (attente.py : graph.json n'est pas réécrit pour ça)
            try:  # l'index du savoir tel qu'il est lu : doublons cherchés, puis rappel de ce message (voir plus haut)
                b.pinned_index = search.memory_index(b)
            except Exception as exc:
                log(f"mémorisation : index : {exc!r}")
            done = [_remember_one(b, text, data.get("cwd")) for text in texts]
            wrote = b.dirty
        if keep is not None:
            keep["brain"] = b
        if wrote:
            try:
                from . import vues
                vues.request(attente=True)  # en arrière-plan : le souvenir entre dans graph.json, puis l'index
                # des souvenirs et les vues sont refaits une fois les écritures calmées
            except Exception as exc:
                log(f"mémorisation : vues : {exc!r}")
    ids = [x[1] for x in done if x[0] != "known"]
    known = [x for x in done if x[0] == "known"]
    if done or skipped:
        sid = data.get("session_id")
        if sid:  # déjà montrés à Claude : ni rappelés dans ce message, ni redemandés en fin de tâche
            st = load_state(sid)
            st["injected"] = sorted(set(st.get("injected", [])) | set(ids))
            said = journal.clean_prompt(raw, 300)
            st["auto_saved"] = [x for x in st.get("auto_saved", []) if x != said][-9:] + [said]
            save_state(sid, st)
    lines, seen = [], []
    if ids:
        many = len(ids) > 1
        lines.append(f"🧠 Déjà enregistré{'s tels quels' if many else ' tel quel'} ({', '.join(f'`{x}`' for x in ids)}) : "
                     f"complète-{'les' if many else 'le'} avec `{CMD} edit {'<id>' if many else ids[0]}` seulement si c'est utile")
        for kind, i, ntype, title in done:
            if kind != "known":
                what = {"todo": "à faire", "feedback": "règle"}.get(ntype, "fait")
                seen.append(f"🧠 Retenu ({what}{', remplace l’ancien' if kind == 'updated' else ''}) : « {short(title, 70)} »")
    for kind, i, ntype, title in known:
        lines.insert(0, f"🧠 Déjà dans le cerveau (`{i}`) sous d'autres mots : pas enregistré en double")
        seen.append(f"🧠 Déjà retenu (`{i}`) : pas enregistré en double")
    if skipped:
        lines.append(f"🧠 Non enregistré : information privée ({', '.join(skipped)}) sur quelqu'un d'autre : ne la copie pas "
                     "dans le cerveau sauf demande explicite")
        seen.append(f"🧠 Pas retenu : information privée ({', '.join(skipped)}) sur quelqu'un d'autre. "
                    "Dis-le-moi si tu veux vraiment la garder.")
    if leaks:
        lines.append(f"🧠 Secret probable dans le message ({', '.join(leaks)}) : non enregistré, ne le copie jamais dans le cerveau")
        seen.append(f"🧠 Pas retenu : secret probable ({', '.join(leaks)}).")
    return "\n".join(lines), "\n".join(seen)


def on_prompt(data, cfg):
    raw = (data.get("prompt") or "").strip()
    try:  # cerveau commun : les pages des amis, récupérées en arrière-plan (au plus une fois par minute)
        if commun_member(cfg):  # (non-membre : commun.py n'est pas chargé)
            from . import commun
            commun.maybe_pull(wait=2.5)
    except Exception as exc:
        log(f"commun (message) : {exc!r}")
    alert = ""
    if not raw.startswith("/"):
        try:
            alert = context_alert(data, cfg)
        except Exception as exc:
            log(f"alerte contexte : {exc!r}")
    saved, keep = "", {}
    if not raw.startswith("/") and not journal.is_auto(raw) and REMEMBER_RX.search(raw):
        try:  # « retiens que… » : enregistré ici même, indépendamment du rappel automatique
            saved, seen = remember_now(data, raw, keep)
            alert = f"{alert}\n{seen}".strip() if seen else alert  # ce qui a été retenu (ou pas) : visible de l'utilisateur
        except Exception as exc:
            log(f"mémorisation automatique : {exc!r}")
    # Fin d'une tâche de fond : rien à rappeler (les souvenirs gardent leur place pour un vrai message)
    ctx = recall_context(data, cfg, raw, saved, keep.get("brain")) if cfg["recall"]["enabled"] and len(raw) >= 6 \
        and not raw.startswith(("/", "<task-notification>", "[SYSTEM NOTIFICATION")) else saved
    if (cfg.get("eco") or {}).get("annonce"):
        try:  # annonce d'une tâche de fond (filtre appris, plugins…) : dite dans la session ouverte, sans attendre un démarrage
            from . import eco
            note = eco.take_annonce(cfg)
            if note:
                ctx = f"{ctx}\n\n{note} (dis-le à l'utilisateur en une phrase au début de ta réponse)".strip()
        except Exception as exc:
            log(f"éco (annonce) : {exc!r}")
    emit("UserPromptSubmit", ctx, alert)

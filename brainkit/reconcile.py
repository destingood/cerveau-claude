"""Réconciliation à l'écriture, façon mem0 / Zep mais sans LLM : face à un nouveau fait, décider s'il
- complète un souvenir existant (même chose redite → fusion),
- le remplace (même sujet, valeur changée : chiffre, négation, changement annoncé, autre nom propre),
- ou s'ajoute (autre sujet, autre événement daté, autre entité dans le titre, simple précision).
Rien n'est jamais effacé : un fait remplacé est archivé avec sa date de fin (`supersede`)."""
from __future__ import annotations

import re

from .common import STOPWORDS, fold, jaccard, now_iso, tokenize

UPDATABLE = ("fact", "decision", "reference", "entity", "user", "feedback", "project")
NUM_RX = re.compile(r"\d+(?:[.,]\d+)?")
DATE_RX = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b")
NEG_RX = re.compile(r"\bn(?:e\b|['’])\s*(?:[\w'’-]+\s+){0,3}?(?:pas|plus|jamais|rien|aucun\w*)\b|\bjamais\b|"
                    r"\baucun(?:e|s|es)?\b", re.I)
OFF_RX = re.compile(r"\b(?:d[ée]sactiv\w*|arr[êe]t[ée]\w*|supprim[ée]\w*|coup[ée](?:e|s|es)?|ferm[ée](?:e|s|es)?|"
                    r"abandonn[ée]\w*|retir[ée]\w*|annul[ée]\w*|refus[ée]\w*|bloqu[ée]\w*|interdit\w*|stopp[ée]\w*|"
                    r"r[ée]sili[ée]\w*|en pause|hors service|hors ligne|termin[ée](?:e|s|es)?)\b", re.I)
ON_RX = re.compile(r"\b(?:activ[ée]\w*|r[ée]activ[ée]\w*|actif|actifs|active|actives|lanc[ée]\w*|relanc[ée]\w*|"
                   r"ouvert\w*|autoris[ée]\w*|publi[ée]\w*|en ligne|en service|repris\w*|propos[ée]\w*|"
                   r"disponibles?)\b", re.I)
CUE_RX = re.compile(r"\b(?:d[ée]sormais|dor[ée]navant|maintenant|[àa] partir d(?:e|u|es|['’])|"
                    r"depuis (?:le|la|les|l['’]|que|ce|cette|qu['’])|n['’]est plus|ne \w+ plus|a remplac[ée]|"
                    r"remplac[ée](?:e|s|es)? par|au lieu d(?:e|u|es|['’])|pass[ée](?:e|s|es)? (?:[àa]|au|aux|en|sur|chez)|"
                    r"passage (?:[àa]|au|aux|en)|passe(?:nt)? de [^.;\n]{1,40}? [àa] |chang[ée](?:e|s|es)?|modifi[ée](?:e|s|es)?|nouveaux?|nouvelles?|"
                    r"mis(?:e|es)? [àa] jour|actualis[ée](?:e|s|es)?|plus que)\b", re.I)
_WORD = re.compile(r"[\wÀ-ÿ][\wÀ-ÿ'’.\-]*[\wÀ-ÿ]|[\wÀ-ÿ]")
_SENT_START = re.compile(r"(?:^|[.!?:;]\s+|\n\s*[-*]?\s*)$")
_LEAD = {"le", "la", "les", "l", "un", "une", "des", "ce", "cet", "cette", "ces", "il", "elle", "ils", "elles", "on",
         "nous", "pour", "avec", "dans", "sur", "depuis", "chaque", "tout", "tous", "toute", "toutes", "si", "quand",
         "en", "au", "aux", "du", "de", "d", "mon", "ma", "mes", "son", "sa", "ses", "notre", "nos", "leur", "leurs",
         "apres", "avant", "pendant", "selon", "lors", "the", "a", "an"}


# Repères de temps ou de rang : deux souvenirs qui n'ont pas les mêmes sont deux événements (la note 7 et la note 9,
# la semaine 45 et la 46, septembre et octobre, 2025 et 2026), jamais une mise à jour de l'un par l'autre.
_MONTHS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10, "novembre": 11, "nov": 11,
           "decembre": 12, "dec": 12}
_ORDINALS = {"premier": 1, "premiere": 1, "deuxieme": 2, "second": 2, "seconde": 2, "troisieme": 3, "quatrieme": 4,
             "cinquieme": 5, "sixieme": 6, "septieme": 7, "huitieme": 8, "neuvieme": 9, "dixieme": 10}
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTH_RX = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b\.?")
_DATE_FOLD_RX = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b|\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2}|1er) (" +
                           "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b")
_YEAR_RX = re.compile(r"(?<![\d/-])(?:19|20)\d\d(?![\d/-])")
_WEEK_RX = re.compile(r"\b(?:semaine|sem|week|wk)\b\.?\s*(?:n°|no\.?|#)?\s*(\d{1,2})\b|\bs(\d{1,2})\b")
_QUARTER_RX = re.compile(r"\b[tq]([1-4])\b|\b(\d|" + "|".join(_ORDINALS) + r")\w*\s+trimestre\b|\btrimestre\s+(\d)\b")
_RANK_RX = re.compile(r"(?:\bn°|\bno\.?|\bnumero|#)\s*(\d{1,3})\b|\b(\d{1,3})\s?(?:er|re|e|eme|nd|nde)\b|\b("
                      + "|".join(_ORDINALS) + r")\b")
_SERIES_RX = re.compile(r"\b(?:note|notes|episode|partie|chapitre|lecon|reunion|session|video|jour|etape|lot|sprint|tome|"
                        r"volume|vol|point|bilan|rapport|compte rendu)s?\.?\s*(\d{1,3})\b|(?<![\d.,€$%])\b(\d{1,3})\s*$")
# « depuis novembre », « à partir de… » : le repère de temps date alors le changement, il ne désigne pas un autre événement
_START_RX = re.compile(r"\b(?:d[ée]sormais|dor[ée]navant|[àa] partir d|depuis|au lieu d|passe(?:nt)? de|n['’]est plus|"
                       r"ne \w+ plus|a remplac[ée])", re.I)


def _picks(m_list) -> set:
    return {g for m in m_list for g in (m if isinstance(m, tuple) else (m,)) if g}


def period_marks(text, title=False) -> dict:
    """Repères de temps et de rang d'un texte, par sorte : {"date", "month", "year", "week", "quarter", "rank"} et, pour un
    titre seulement, {"weekday", "series"} (un jour de semaine ou un numéro de série en plein texte n'est pas un repère)."""
    t = fold(str(text or ""))
    out = {
        "date": {m.group(0) for m in _DATE_FOLD_RX.finditer(t)},
        "month": {str(_MONTHS[m.group(1)]) for m in _MONTH_RX.finditer(t)},
        "year": set(_YEAR_RX.findall(DATE_RX.sub(" ", t))) | {m.group(4) or m.group(3) for m in _DATE_FOLD_RX.finditer(t)
                                                              if (m.group(4) or m.group(3))},
        "week": _picks(_WEEK_RX.findall(t)),
        "quarter": {str(_ORDINALS.get(x, x)) for x in _picks(_QUARTER_RX.findall(t))},
        "rank": {str(_ORDINALS.get(x, x)).lstrip("0") for x in _picks(_RANK_RX.findall(t))},
    }
    if title:
        out["weekday"] = {d for d in _DAYS if re.search(rf"\b{d}s?\b", t)}
        out["series"] = {x.lstrip("0") for x in _picks(_SERIES_RX.findall(str(text or "").lower()))}
    return {k: v for k, v in out.items() if v}


def _differ(a, b) -> bool:
    """Deux ensembles de repères qui ont chacun quelque chose que l'autre n'a pas (ni l'un ni l'autre n'est vide)."""
    return bool(a - b and b - a)


def other_event(o_title, o_body, n_title, n_body) -> bool:
    """Le nouveau souvenir parle-t-il d'un autre jour, d'une autre semaine, d'un autre mois, d'une autre année ou d'un
    autre numéro d'une série que l'ancien ? Dans les titres, tout repère qui diffère le dit. Dans les textes, une semaine,
    un trimestre ou un rang (n°, 3e, deuxième) qui diffère aussi ; un mois, une année ou une date seulement si le nouveau
    texte n'annonce pas un changement (« depuis novembre », « à partir du 20/11 » : la date est celle du changement)."""
    ot, nt = period_marks(o_title, True), period_marks(n_title, True)
    if any(_differ(ot.get(k, set()), nt.get(k, set())) for k in ("date", "month", "year", "week", "quarter", "rank",
                                                               "weekday", "series")):
        return True
    ob, nb = period_marks(f"{o_title}\n{o_body}"), period_marks(f"{n_title}\n{n_body}")
    if any(_differ(ob.get(k, set()), nb.get(k, set())) for k in ("week", "quarter", "rank")):
        return True
    return not _START_RX.search(f"{n_title}\n{n_body}") and any(
        _differ(ob.get(k, set()), nb.get(k, set())) for k in ("date", "month", "year"))


def entities(text) -> set:
    """Noms propres et codes d'un texte (Colissimo, Mondial Relay, NEWS15, judge.me…), repliés.
    En début de phrase, un mot capitalisé ne compte que s'il a l'air d'un nom (point, chiffre, majuscule interne)."""
    return {f for _, _, f in _entity_spans(text)}


def names(text) -> set:
    """Les noms d'un texte sous une forme qui ne dépend pas de l'écriture (étape 14, d'après graphiti) : les mots d'un
    nom en plusieurs mots réunis, sans espace, tiret ni point — « Mondial Relay », « MondialRelay » et « mondial-relay »
    donnent tous « mondialrelay »."""
    text = str(text or "")
    spans, out, run = _entity_spans(text), set(), []
    for s, e, f in spans:
        gap = text[run[-1][1]:s] if run else ""
        if run and not (gap and gap.strip(" \t") == ""):  # séparés par autre chose que des espaces : deux noms
            out.add(re.sub(r"[^0-9a-z]", "", "".join(x[2] for x in run)))
            run = []
        run.append((s, e, f))
    if run:
        out.add(re.sub(r"[^0-9a-z]", "", "".join(x[2] for x in run)))
    return {x for x in out if len(x) >= 2}


def _entity_spans(text) -> list:
    """[(début, fin, mot replié)] des noms propres et codes d'un texte, dans l'ordre (voir entities)."""
    text = str(text or "")
    out = []
    for m in _WORD.finditer(text):
        w = re.sub(r"^(?:[ldjmnstcLDJMNSTC]|[qQ]u)['’]", "", m.group(0).strip(".'’-"))  # d'Amazon → Amazon
        if len(w) < 2:
            continue
        f = fold(w)
        if f in STOPWORDS or f in _LEAD:
            continue
        has_digit = any(c.isdigit() for c in w)
        code = has_digit and any(c.isalpha() for c in w)
        domain = re.search(r"\.[a-z]{2,4}$", f) is not None
        cap = w[0].isupper()
        inner = any(c.isupper() for c in w[1:]) and not w.isupper() or (w.isupper() and len(w) >= 2 and w.isalpha())
        if not (code or domain or cap):
            continue
        if cap and not (code or domain) and _SENT_START.search(text[:m.start()]) and not (inner or "." in w):
            continue
        out.append((m.start(), m.end(), f))
    return out


def polarity(text) -> int:
    """-1 : négatif ou arrêté · +1 : actif, activé, proposé · 0 : neutre."""
    t = str(text or "")
    if NEG_RX.search(t) or OFF_RX.search(t):
        return -1
    return 1 if ON_RX.search(t) else 0


def _nums(text):
    return set(NUM_RX.findall(DATE_RX.sub(" ", str(text or "")))), set(DATE_RX.findall(str(text or "")))


def _content(text) -> set:
    return set(tokenize(text))


def signals(old, title, body) -> dict:
    """Ce qui distingue le nouveau fait (title, body) d'un souvenir existant `old`."""
    o_title, o_body = old.get("title", ""), old.get("body", "")
    o_all, n_all = f"{o_title}\n{o_body}", f"{title}\n{body}"
    sig = {}
    ot_ent, nt_ent = names(o_title), names(title)  # « Mondial Relay » = « MondialRelay » (étape 14)
    if ot_ent != nt_ent:
        sig["autre sujet"] = True  # une entité du titre change ou s'ajoute (Kyoto ≠ Osaka, « … en Belgique »)
    if set(DATE_RX.findall(o_title)) != set(DATE_RX.findall(title)) or other_event(o_title, o_body, title, body):
        sig["autre événement"] = True  # « Audit du 15/10 » ≠ « Audit du 20/10 », note 7 ≠ note 9, semaine 45 ≠ 46
    (on, od), (nn, nd) = _nums(o_all), _nums(n_all)
    if (on - nn and nn - on) or (od and nd and od - nd and nd - od):
        sig["chiffres"] = True
    po, pn = polarity(o_all), polarity(n_all)
    if po != pn and -1 in (po, pn):
        sig["négation"] = True
    if CUE_RX.search(n_all) and not CUE_RX.search(o_all):
        sig["changement annoncé"] = True
    oe, ne = names(o_body) - ot_ent, names(body) - nt_ent
    if oe - ne and ne - oe:
        sig["autre nom"] = True  # Colissimo → Mondial Relay, Dawn → Impulse
    return sig


VALUE_SIGNALS = ("chiffres", "négation", "changement annoncé", "autre nom")


def decide(brain, ntype, title, body, project=None, exclude=None, period=None):
    """→ {"action": "merge"|"update"|"new", "target": nœud|None, "why": [...], "neighbors": [(sim, nœud, why)]}
    `period` : dates écrites du nouveau fait ({"valid_from", "valid_to"}) ; un souvenir dont la période ne chevauche
    pas la sienne n'est ni fusionné ni remplacé (étape 14 : deux périodes distinctes ne se contredisent pas)."""
    from .temps import overlap
    t_tok = _content(title)
    cands = brain.similar(title, body, None, limit=6, threshold=0.3, exclude=exclude)
    neighbors = []
    me = {"meta": dict(period or {}), "created": now_iso()}
    for s, n in cands:
        if (n.get("project") or None) != (project or None) or not overlap(me, n):
            continue
        sig = signals(n, title, body)
        ts = jaccard(t_tok, _content(n["title"]))
        value = [k for k in VALUE_SIGNALS if sig.get(k)]
        other = sig.get("autre sujet") or sig.get("autre événement")
        neighbors.append((round(max(s, ts), 2), n, value, other))
        if other or n["type"] != ntype:
            continue
        if ntype in UPDATABLE and value and (ts >= 0.75 or s >= 0.8 or (ts >= 0.5 and "changement annoncé" in value
                                                                         and len(value) >= 2)):
            return {"action": "update", "target": n, "why": value, "neighbors": neighbors}
        if s >= 0.8 and not value:
            return {"action": "merge", "target": n, "why": [], "neighbors": neighbors}
    near = _same_name(brain, title, body, project, {exclude}, me)
    boost = {n["id"] for _, n, _, _ in near}
    neighbors = [(max(sim, 0.45) if n["id"] in boost else sim, n, v, o) for sim, n, v, o in neighbors]
    have = {n["id"] for _, n, _, _ in neighbors}
    neighbors += [x for x in near if x[1]["id"] not in have]
    return {"action": "new", "target": None, "why": [], "neighbors": neighbors}


RARE = 3  # un nom du titre porté par au plus RARE souvenirs : un lien fort entre eux


def _same_name(brain, title, body, project, seen, me) -> list:
    """Souvenirs qui partagent un nom propre rare du titre, même rédigés autrement (étape 14, d'après graphiti :
    les faits à invalider se cherchent aussi parmi ceux qui touchent la même entité). Seulement des suggestions
    (« remplace peut-être »), jamais un remplacement automatique. → voisins au format de decide."""
    from .temps import overlap
    mine = names(title)
    if not mine:
        return []
    holders = {}
    for n in brain.active(own=True):
        if n["id"] in seen or n["type"] == "project":
            continue
        for x in names(f"{n.get('title', '')}\n{n.get('body', '')}") & mine:
            holders.setdefault(x, []).append(n)
    out = []
    for x, nodes in holders.items():
        if len(nodes) > RARE:
            continue
        for n in nodes:
            if (n.get("project") or None) != (project or None) or not overlap(me, n) or n["id"] in seen:
                continue
            sig = signals(n, title, body)
            value = [k for k in VALUE_SIGNALS if sig.get(k)]
            seen = seen | {n["id"]}
            out.append((0.45, n, value, bool(sig.get("autre événement"))))
    return out


def suggestions(decision, limit=2):
    """Voisins à signaler après un ajout : même sujet probable avec une valeur différente (à confirmer)."""
    out = []
    for sim, n, value, other in decision["neighbors"]:
        if value and not other and sim >= 0.45:
            out.append((sim, n, value))
    return out[:limit]

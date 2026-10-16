"""Réconciliation à l'écriture, façon mem0 / Zep mais sans LLM : face à un nouveau fait, décider s'il
- complète un souvenir existant (même chose redite → fusion),
- le remplace (même sujet, valeur changée : chiffre, négation, changement annoncé, autre nom propre),
- ou s'ajoute (autre sujet, autre événement daté, autre entité dans le titre, simple précision).
Rien n'est jamais effacé : un fait remplacé est archivé avec sa date de fin (`supersede`)."""
from __future__ import annotations

import re

from .common import STOPWORDS, fold, jaccard, tokenize

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
                    r"passage (?:[àa]|au|aux|en)|chang[ée](?:e|s|es)?|modifi[ée](?:e|s|es)?|nouveaux?|nouvelles?|"
                    r"mis(?:e|es)? [àa] jour|actualis[ée](?:e|s|es)?|plus que)\b", re.I)
_WORD = re.compile(r"[\wÀ-ÿ][\wÀ-ÿ'’.\-]*[\wÀ-ÿ]|[\wÀ-ÿ]")
_SENT_START = re.compile(r"(?:^|[.!?:;]\s+|\n\s*[-*]?\s*)$")
_LEAD = {"le", "la", "les", "l", "un", "une", "des", "ce", "cet", "cette", "ces", "il", "elle", "ils", "elles", "on",
         "nous", "pour", "avec", "dans", "sur", "depuis", "chaque", "tout", "tous", "toute", "toutes", "si", "quand",
         "en", "au", "aux", "du", "de", "d", "mon", "ma", "mes", "son", "sa", "ses", "notre", "nos", "leur", "leurs",
         "apres", "avant", "pendant", "selon", "lors", "the", "a", "an"}


def entities(text) -> set:
    """Noms propres et codes d'un texte (Colissimo, Mondial Relay, NEWS15, judge.me…), repliés.
    En début de phrase, un mot capitalisé ne compte que s'il a l'air d'un nom (point, chiffre, majuscule interne)."""
    text = str(text or "")
    out = set()
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
        out.add(f)
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
    ot_ent, nt_ent = entities(o_title), entities(title)
    if ot_ent != nt_ent:
        sig["autre sujet"] = True  # une entité du titre change ou s'ajoute (Kyoto ≠ Osaka, « … en Belgique »)
    if set(DATE_RX.findall(o_title)) != set(DATE_RX.findall(title)):
        sig["autre événement"] = True  # « Audit du 15/10 » ≠ « Audit du 20/10 »
    (on, od), (nn, nd) = _nums(o_all), _nums(n_all)
    if (on - nn and nn - on) or (od and nd and od - nd and nd - od):
        sig["chiffres"] = True
    po, pn = polarity(o_all), polarity(n_all)
    if po != pn and -1 in (po, pn):
        sig["négation"] = True
    if CUE_RX.search(n_all) and not CUE_RX.search(o_all):
        sig["changement annoncé"] = True
    oe, ne = entities(o_body) - ot_ent, entities(body) - nt_ent
    if oe - ne and ne - oe:
        sig["autre nom"] = True  # Colissimo → Mondial Relay, Dawn → Impulse
    return sig


VALUE_SIGNALS = ("chiffres", "négation", "changement annoncé", "autre nom")


def decide(brain, ntype, title, body, project=None, exclude=None):
    """→ {"action": "merge"|"update"|"new", "target": nœud|None, "why": [...], "neighbors": [(sim, nœud, why)]}"""
    t_tok = _content(title)
    cands = brain.similar(title, body, None, limit=6, threshold=0.3, exclude=exclude)
    neighbors = []
    for s, n in cands:
        if (n.get("project") or None) != (project or None):
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
    return {"action": "new", "target": None, "why": [], "neighbors": neighbors}


def suggestions(decision, limit=2):
    """Voisins à signaler après un ajout : même sujet probable avec une valeur différente (à confirmer)."""
    out = []
    for sim, n, value, other in decision["neighbors"]:
        if value and not other and sim >= 0.45:
            out.append((sim, n, value))
    return out[:limit]

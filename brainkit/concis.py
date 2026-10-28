"""Texte injecté plus court — idées de Caveman et du pack de langue français de Troglodita : tournures longues et mots
de remplissage retirés des résumés que le cerveau injecte (index, fiche du projet, rappel à chaque message), et
tableau en-tête + lignes (façon TOON) là où chaque ligne répète les mêmes étiquettes.

Prudent : seulement des tournures dont le sens ne change pas ; articles, négations, chiffres, dates et code restent.
Les pages du wiki et les souvenirs gardés ne sont jamais réécrits : seul le texte injecté l'est.
Mesuré : sur des listes « - titre `id` », un tableau allonge le texte (« | » entre colonnes contre « - [ ] ») ; il ne
sert que pour les lignes à étiquettes répétées (sessions : « dernière demande : … — modifiés : … »)."""
import re

from .common import short, tokenize

_E = r"(?:de |d['’])"  # « de » ou « d' » élidé
_RULES = [(re.compile(p, re.I), r) for p, r in (
    (rf"\bafin {_E}", "pour "), (r"\bafin que\b", "pour que"), (rf"\bdans le but {_E}", "pour "),
    (r"\bde (?:manière|façon) à\b", "pour"), (r"\ben ce qui concerne\b", "pour"),
    (rf"\bil est (?:possible|permis) {_E}", "on peut "), (rf"\bil est (?:nécessaire|indispensable) {_E}", "il faut "),
    (rf"\best en mesure {_E}", "peut "), (rf"\bsont en mesure {_E}", "peuvent "),
    (r"\bà l['’]heure actuelle\b", "aujourd'hui"), (r"\bau jour d['’]aujourd['’]hui\b", "aujourd'hui"),
    (rf"\bun certain nombre {_E}", "plusieurs "), (r"\bun grand nombre d(e |['’])", r"beaucoup d\1"),
    (r"\bpar exemple\b", "p. ex."), (r"\b(?:environ|approximativement|à peu près) (?=\d)", "≈ "),
    (r"\*\*|__", ""),  # gras Markdown : rien à lire de plus sur une ligne de résumé
)]
# Remplissage retiré (avec sa virgule) ; « vraiment » et compagnie restent après une négation (« pas vraiment »).
_FILLER = re.compile(r"(^|[.!?;:]\s+|[\s(«])(?:(?:en fait|en effet|tout simplement|bien sûr|bien entendu|évidemment|"
                     r"il faut savoir que|il (?:convient|est important) de noter que|il est à noter que)\b"
                     r"|(?<!pas )(?<!plus )(?:vraiment|réellement|littéralement|tout à fait)\b),?\s*(\w?)", re.I)


def _drop(m):
    """Le mot retiré ouvrait la phrase : la suite prend sa majuscule (« En fait, il faut » → « Il faut »)."""
    lead, nxt = m.group(1), m.group(2)
    opens = lead == "" or lead.rstrip()[-1:] in (".", "!", "?")
    return lead + (nxt.upper() if opens and m.group(0)[len(lead):][:1].isupper() else nxt)


def _keep_case(rep):
    """Remplacement qui garde la majuscule d'origine (« Il est possible de » → « On peut »)."""
    def sub(m):
        out = m.expand(rep)
        return out[:1].upper() + out[1:] if m.group(0)[:1].isupper() else out
    return sub


def concis(text) -> str:
    """Résumé injecté : tournures longues raccourcies, remplissage retiré, espaces resserrés."""
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    for rx, rep in _RULES:
        s = rx.sub(_keep_case(rep), s)
    s = _FILLER.sub(_drop, s)
    s = re.sub(r"(?<=\w) ([,.])(?=\s|$)", r"\1", s)  # « c'est vraiment. » → « c'est . » → « c'est. »
    return " ".join(s.split())


def table(cols, rows) -> list:
    """En-tête puis une ligne par élément, colonnes séparées par « | » (une barre dans une valeur devient « / »)."""
    cell = lambda v: " ".join(str(v or "—").replace("|", "/").split())
    return [" | ".join(cols)] + [" | ".join(cell(v) for v in r) for r in rows]


_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")


def _window(s, q, n) -> str:
    """Phrase trop longue : la fenêtre qui commence un peu avant le premier mot du message."""
    if len(s) <= n:
        return s
    for m in re.finditer(r"\w+", s):
        if m.start() > n // 2 and set(tokenize(m.group())) & q:
            a = s.rfind(" ", 0, m.start() - 40) + 1
            return "… " + short(s[a:], n - 2)
        if set(tokenize(m.group())) & q:
            break
    return short(s, n)


def relevant(base, body, query, chars, skip="") -> str:
    """Phrases d'un souvenir qui répondent au message (idée du moteur Relevance d'OmniRoute), dans leur ordre, si elles
    montrent plus de mots du message que le début du résumé ; sinon "" (on garde le début). `skip` : mots déjà lus
    (le titre)."""
    q = set(tokenize(query)) - set(tokenize(skip))
    if not q:
        return ""
    start = short(concis(base), chars)
    sents, seen = [], set()
    for part in _SENT.split(f"{base}\n{body}"):
        s = concis(part.strip(" \t#*->|`"))
        if len(s) >= 12 and s not in seen:
            seen.add(s)
            sents.append(_window(s, q, chars))
    hits = sorted(((len(q & set(tokenize(s))), i, s) for i, s in enumerate(sents)), key=lambda x: (-x[0], x[1]))
    picked, got, used = [], set(), 0
    for k, i, s in hits:
        new = q & set(tokenize(s)) - got
        if not k or not new or (used and used + len(s) + 3 > chars):
            continue
        picked.append((i, s))
        got |= new
        used += len(s) + 3
    out = short(" … ".join(s for _, s in sorted(picked)), chars)
    return out if len(q & set(tokenize(out))) > len(q & set(tokenize(start))) else ""

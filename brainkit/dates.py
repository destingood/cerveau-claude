"""Dates d'échéance en français : « 10/11 », « 10/11/2026 », « 10 novembre », « demain », « dans 3 jours »…"""
from __future__ import annotations

import datetime as _dt
import re

from .common import fold

MONTHS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5,
          "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10,
          "novembre": 11, "nov": 11, "decembre": 12, "dec": 12}
_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TXT = re.compile(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?(?:\s+(\d{4}))?\b")
_REL = re.compile(r"\bdans\s+(\d{1,3})\s*(jours?|j|semaines?|sem|mois)\b")
# Dans un titre d'à-faire : date en tête (« 10/11 : vérifier… ») ou annoncée (« avant le 10/11 », « pour le 3 mars »).
_LEAD = re.compile(r"^\s*(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)\s*[:\-–—]")
_ANNOUNCED = re.compile(r"\b(?:avant|pour|d'ici|jusqu'au|au plus tard|[ée]ch[ée]ance|due|deadline)\s*(?:le|au|:)?\s*"
                        r"(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?|\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+\d{4})?)", re.I)


def _mk(y, m, d):
    try:
        return _dt.date(y, m, d)
    except ValueError:
        return None


def parse(text, today=None):
    """Texte → date ISO « AAAA-MM-JJ » (année absente : la prochaine occurrence, à 30 jours de retard près)."""
    today = today or _dt.date.today()
    t = fold(text or "").strip()
    if not t or t in ("none", "aucune", "-"):
        return None
    if t in ("aujourd'hui", "aujourdhui", "ce soir"):
        return today.isoformat()
    if t == "demain":
        return (today + _dt.timedelta(days=1)).isoformat()
    if t in ("apres-demain", "apres demain"):
        return (today + _dt.timedelta(days=2)).isoformat()
    if t == "hier":
        return (today - _dt.timedelta(days=1)).isoformat()
    if t in ("avant-hier", "avant hier"):
        return (today - _dt.timedelta(days=2)).isoformat()
    m = re.search(r"\bil y a\s+(\d{1,3})\s*(jours?|j|semaines?|sem|mois)\b", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return (today - _dt.timedelta(days=n * (7 if unit.startswith("sem") else 30 if unit == "mois" else 1))).isoformat()
    m = _REL.search(t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * (7 if unit.startswith("sem") else 30 if unit == "mois" else 1)
        return (today + _dt.timedelta(days=days)).isoformat()
    m = _ISO.search(t)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.isoformat() if d else None
    m = _NUM.search(t)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = _TXT.search(t)
        if not m:
            return None
        day, month, year = int(m.group(1)), MONTHS[m.group(2)], m.group(3)
    if year:
        y = int(year)
        y = y + 2000 if y < 100 else y
        d = _mk(y, month, day)
    else:
        d = _mk(today.year, month, day)
        if d and (today - d).days > 30:
            d = _mk(today.year + 1, month, day)
    return d.isoformat() if d else None


def from_title(title, today=None):
    """Échéance lisible dans le titre d'un à-faire (date en tête ou annoncée) — jamais une simple date de constat."""
    m = _LEAD.search(title or "") or _ANNOUNCED.search(title or "")
    return parse(m.group(1), today) if m else None


def days_until(iso, today=None):
    today = today or _dt.date.today()
    try:
        return (_dt.date.fromisoformat(iso) - today).days
    except (TypeError, ValueError):
        return None


def human(iso, today=None):
    n = days_until(iso, today)
    if n is None:
        return "?"
    d = _dt.date.fromisoformat(iso)
    when = d.strftime("%d/%m")
    if n < 0:
        return f"en retard de {-n} j ({when})"
    if n == 0:
        return "aujourd'hui"
    if n == 1:
        return "demain"
    return f"dans {n} j ({when})"


def due_of(node, today=None):
    """Échéance d'un nœud : explicite (meta.due) sinon lue dans le titre d'un à-faire."""
    meta = node.get("meta") or {}
    if meta.get("due"):
        return meta["due"]
    if node.get("type") == "todo":
        return from_title(node.get("title", ""), today)
    return None


# ------------------------------------------------------------------------------------ dates relatives → absolues
_WD = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTH_NAMES = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                "novembre", "décembre")
_NOT_DATED = r"(?![ \t]*\(\s*(?:\d|semaine|[a-zéû]+ \d{4}))"  # déjà suivi de sa date : ne rien ajouter
_RELATIVE = re.compile(
    r"\b(aujourd['’]hui|avant[- ]hier|apr[eè]s[- ]demain|hier|demain|ce matin|ce soir|cet apr[eè]s-midi|cette nuit|"
    r"il y a (\d{1,3}) (jours?|semaines?|mois)|dans (\d{1,3}) (jours?|semaines?|mois)|"
    r"la semaine (derni[eè]re|prochaine)|cette semaine|(?:le|du|au) mois (dernier|prochain)|ce mois-ci|"
    r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche) (dernier|prochain)|"
    r"l['’](?:an|ann[ée]e) (derni[eè]re?|prochaine?)|cette ann[ée]e)\b" + _NOT_DATED, re.I)


def _fmt(d):
    return d.strftime("%d/%m/%Y")


def _shift_month(d, n):
    m = d.month - 1 + n
    return _dt.date(d.year + m // 12, m % 12 + 1, 1)


def _relative_value(m, today):
    """Expression relative → texte absolu à mettre entre parenthèses (ou None)."""
    w = fold(m.group(1)).replace("’", "'")
    day = _dt.timedelta(days=1)
    simple = {"aujourd'hui": 0, "ce matin": 0, "ce soir": 0, "cet apres-midi": 0, "cette nuit": 0, "hier": -1,
              "avant-hier": -2, "avant hier": -2, "demain": 1, "apres-demain": 2, "apres demain": 2}
    if w in simple:
        return _fmt(today + simple[w] * day)
    if m.group(2) or m.group(4):
        n = int(m.group(2) or m.group(4))
        unit = m.group(3) or m.group(5)
        sign = -1 if m.group(2) else 1
        if unit.startswith("mois"):
            return _fmt(today + sign * 30 * n * day)
        return _fmt(today + sign * n * (7 if unit.startswith("semaine") else 1) * day)
    monday = today - today.weekday() * day
    if w.startswith("la semaine") or w == "cette semaine":
        shift = -7 if "dern" in w else 7 if "proch" in w else 0
        return f"semaine du {_fmt(monday + shift * day)}"
    if w.endswith(("mois dernier", "mois prochain")) or w == "ce mois-ci":  # « le / du / au mois dernier »
        first = _shift_month(today, -1 if "dern" in w else 1 if "proch" in w else 0)
        return f"{_MONTH_NAMES[first.month - 1]} {first.year}"
    if m.group(8):
        target = _WD.index(fold(m.group(8)))
        if m.group(9).lower().startswith("dern"):
            delta = (today.weekday() - target) % 7 or 7
            return _fmt(today - delta * day)
        delta = (target - today.weekday()) % 7 or 7
        return _fmt(today + delta * day)
    if "an" in w:
        year = today.year + (-1 if "dern" in w else 1 if "proch" in w else 0)
        return str(year)
    return None


def absolutize(text, today=None) -> str:
    """« hier », « dans 2 semaines », « lundi prochain »… suivis de leur date réelle, pour qu'un souvenir reste vrai
    dans six mois (« hier (15/10/2026) »). Idempotent : une expression déjà datée n'est pas retouchée."""
    if not text:
        return text
    today = today or _dt.date.today()

    def sub(m):
        val = _relative_value(m, today)
        return f"{m.group(0)} ({val})" if val else m.group(0)
    return _RELATIVE.sub(sub, str(text))


def has_relative(text) -> bool:
    return bool(_RELATIVE.search(text or ""))


# ------------------------------------------------------------------------------------ plages de dates (questions)
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
_PART = re.compile(r"\b(debut|mi|fin)[- ](" + _MONTH_RX + r")\b")
_IN_MONTH = re.compile(r"\b(?:en|au mois d['e]|mois d['e]|d['e])\s*(" + _MONTH_RX + r")\b")


def _nearest(month, day, today):
    """Jour/mois sans année → l'occurrence la plus proche d'aujourd'hui (passée ou future)."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        d = _mk(y, month, min(day, 28) if month == 2 and day > 28 else day)
        if d and (best is None or abs((d - today).days) < abs((best - today).days)):
            best = d
    return best


def query_range(text, today=None):
    """Question → plage de dates visée (début, fin) ou None : « hier », « le 12/11 », « la semaine dernière »,
    « le bilan du mois dernier », « il y a 3 semaines », « début septembre », « en août », « lundi dernier »…"""
    today = today or _dt.date.today()
    t = fold(text or "")
    day = _dt.timedelta(days=1)
    m = re.search(r"\bil y a\s+(\d{1,3})\s*(jours?|j|semaines?|sem|mois)\b", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        span, tol = (30, 10) if unit == "mois" else (7, 3) if unit.startswith("sem") else (1, 1)
        center = today - n * span * day
        return center - tol * day, center + tol * day
    for word, delta in (("avant-hier", -2), ("avant hier", -2), ("apres-demain", 2), ("hier", -1), ("demain", 1),
                        ("aujourd'hui", 0), ("aujourdhui", 0), ("ce matin", 0)):
        if re.search(r"\b" + re.escape(word) + r"\b", t):
            d = today + delta * day
            return d, d
    monday = today - today.weekday() * day
    # Quel que soit l'article : « (de) la semaine dernière », « semaine dernière », « le / du / au mois dernier ».
    # « passé » en exige un (« un mois passé à tester » n'est pas une date) ; « ce mois de mai » reste mai.
    if re.search(r"\b(?:semaine (?:derniere|precedente)|la semaine passee)\b", t):
        return monday - 7 * day, monday - day
    if re.search(r"\bcette semaine\b", t):
        return monday, monday + 6 * day
    if re.search(r"\bsemaine prochaine\b", t):
        return monday + 7 * day, monday + 13 * day
    for rx, shift in ((r"\b(?:mois (?:dernier|precedent)|(?:le|du|au) mois passe)\b", -1),
                      (r"\bce mois(?:-ci)?\b(?! d['e])", 0), (r"\bmois prochain\b", 1)):
        if re.search(rx, t):
            first = _shift_month(today, shift)
            return first, _shift_month(first, 1) - day
    m = re.search(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche) (dernier|prochain)\b", t)
    if m:
        target = _WD.index(m.group(1))
        delta = ((today.weekday() - target) % 7 or 7) * (-1) if m.group(2) == "dernier" else ((target - today.weekday()) % 7 or 7)
        d = today + delta * day
        return d, d
    m = _ISO.search(t)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, d
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)  # « / » seulement : « 3.5 » n'est pas une date
    if m:
        dd, mm = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            d = _mk(y + 2000 if y < 100 else y, mm, dd)
        else:
            d = _nearest(mm, dd, today) if 1 <= mm <= 12 and 1 <= dd <= 31 else None
        if d:
            return d, d
    m = _TXT.search(t)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))) if m.group(3) else \
            _nearest(MONTHS[m.group(2)], int(m.group(1)), today)
        if d:
            return d, d
    m = _PART.search(t)
    if m:
        first = _nearest(MONTHS[m.group(2)], 1, today)
        end = _shift_month(first, 1) - day
        part = m.group(1)
        return (first, first + 9 * day) if part == "debut" else (first + 9 * day, first + 19 * day) if part == "mi" \
            else (first + 19 * day, end)
    m = _IN_MONTH.search(t)
    if m:
        first = _nearest(MONTHS[m.group(1)], 15, today).replace(day=1)
        return first, _shift_month(first, 1) - day
    return None


_ANY_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b|"
                       r"\b(\d{1,2})(?:er)?\s+(" + _MONTH_RX + r")\.?(?:\s+(\d{4}))?\b")


def dates_in(text, ref=None):
    """Dates écrites dans un texte (ISO, 15/10, 15/10/2026, 15 octobre) — année absente : celle la plus proche de ref."""
    ref = ref or _dt.date.today()
    out = []
    for m in _ANY_DATE.finditer(fold(text or "")):
        if m.group(1):
            d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif m.group(4):
            dd, mm = int(m.group(4)), int(m.group(5))
            if not (1 <= dd <= 31 and 1 <= mm <= 12):
                continue
            if m.group(6):
                y = int(m.group(6))
                d = _mk(y + 2000 if y < 100 else y, mm, dd)
            else:
                d = _nearest(mm, dd, ref)
        else:
            d = _mk(int(m.group(9)), MONTHS[m.group(8)], int(m.group(7))) if m.group(9) else \
                _nearest(MONTHS[m.group(8)], int(m.group(7)), ref)
        if d:
            out.append(d)
    return out

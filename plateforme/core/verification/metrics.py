"""Computed metrics: a draft number given as one must come from a tool figure of that metric (R1).

A VaR, a volatility or a Sharpe ratio is computed by a tool; a page, a search result or a text
leaf of an output may hold the same number for something else (B1.1, G-1). A draft number is
*given as* a metric when, in its sentence, the nearest metric word before it names one (``la VaR
à 99 % sur une séance est de 23 456,78 €``: the three numbers), or when the metric follows it
(``18 % de volatilité``). The sentence ends at ``.``, ``;``, ``!``, ``?`` or a line break; a
colon or a comma does not end it (``VaR : 23 456,78 €``).

Such a number is supported only by a figure whose id names the same metric, the last one named in
the id (``var/historique/99/1/cvar_eur`` is a CVaR, ``volatilite/garch/beta`` a beta).

Limits: a metric word farther than the sentence, or in a table header on another line, is not
seen; a number after a metric word in the same sentence is held to that metric even when it
counts something else (write it in another sentence). Plain ``rendement``, ``performance`` and
``return`` are not metrics, since a page often gives a bond yield or an index return; their
annualised or weighted forms (``TWR``, ``rendement annualisé``) are. A correlation, a bêta-bloquant
or a published volatility read on a page is not a computed metric of the user's book either:
the last one is refused, which the check accepts as the price of R1.
"""

from __future__ import annotations

import re

_FAMILIES: dict[str, tuple[str, str]] = {  # family: (draft words, figure id words)
    "cvar": (
        r"\bC(?:VaR|VAR)\b|(?i:\bexpected[- ]shortfall\b|\bVaR conditionnelle\b)",
        r"cvar|es|expected_shortfall",
    ),
    "var": (r"\b(?:VaR|VAR)\b|(?i:\bvalue[- ]at[- ]risk\b|\bvaleur en risque\b)", r"var"),
    "volatilite": (
        r"(?i:\bvolatilit(?:é|e|y|ies)s?\b)",
        r"volatilite|volatility|vol",
    ),
    "sharpe": (r"(?i:\bsharpe\b)", r"sharpe"),
    "sortino": (r"(?i:\bsortino\b)", r"sortino"),
    "calmar": (r"(?i:\bcalmar\b)", r"calmar"),
    "treynor": (r"(?i:\btreynor\b)", r"treynor"),
    "drawdown": (
        r"(?i:\bdrawdowns?\b|\bpertes? maximales?\b|\brepli maximal\b)",
        r"drawdown|max_drawdown|perte_max|mdd",
    ),
    "beta": (r"(?i:\bb[êe]ta\b(?!-))", r"beta"),
    "tracking": (
        r"(?i:\btracking[- ]error\b|\b[ée]cart de suivi\b)",
        r"tracking_error|tracking|ecart_suivi",
    ),
    "information": (
        r"(?i:\bratio d['’]information\b|\binformation ratio\b)",
        r"information_ratio|ratio_information",
    ),
    "tri": (
        r"\b(?:TRI|IRR)\b|(?i:\btaux de rendement interne\b|\binternal rate of return\b)",
        r"tri|irr",
    ),
    "rendement": (
        r"\b(?:TWR|MWR)\b|(?i:\brendements? (?:annualis|pond[ée]r)\w*|\btime[- ]weighted\b"
        r"|\bmoney[- ]weighted\b|\bannuali[sz]ed returns?\b|\bperformances? annualis[ée]es?\b)",
        r"twr|mwr|rendement|return|cagr|performance",
    ),
}
METRICS = frozenset(_FAMILIES)
_DRAFT = re.compile("|".join(f"(?P<{name}>{words})" for name, (words, _) in _FAMILIES.items()))
_ID = re.compile(
    "|".join(
        rf"(?P<{name}>(?<![a-z])(?:{words})(?![a-z]))" for name, (_, words) in _FAMILIES.items()
    )
)
_SENTENCE_END = re.compile(r"[;!?\n]|\.(?=\s|$)")
_AFTER = re.compile(r"\s*(?:(?i:de|du|d['’]|en)\s*)?(?:(?i:la|le|l['’])\s*)?")
_LOOK_BEHIND = 240  # characters read before a number for its sentence


def _family(match: re.Match[str]) -> str:
    name = match.lastgroup
    if name is None:  # every alternative is a named group
        raise ValueError("métrique sans nom")
    return name


def draft_metric(text: str, start: int, end: int) -> str | None:
    """The metric a draft number at ``text[start:end]`` is given as, or ``None``."""
    after = _AFTER.match(text, end)
    if after is not None and (found := _DRAFT.match(text, after.end())) is not None:
        return _family(found)
    sentence = _SENTENCE_END.split(text[max(0, start - _LOOK_BEHIND) : start])[-1]
    words = list(_DRAFT.finditer(sentence))
    return _family(words[-1]) if words else None


def figure_metric(figure_id: str) -> str | None:
    """The metric a figure id names last: ``var/historique/99/1/cvar_eur`` is a CVaR."""
    found = list(_ID.finditer(figure_id.casefold()))
    return _family(found[-1]) if found else None


__all__ = ["METRICS", "draft_metric", "figure_metric"]

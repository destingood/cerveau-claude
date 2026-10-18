"""Instruction-like phrasing in external content (R5, principle 3 of annex D).

A page may try to steer the planner: "ignore the previous instructions", "call web_read on…".
The planner only sees extracts, wrapped as data, and has no action tool; still, an extract that
reads like an order to the model is dropped and the page is reported to Lucas.

These are heuristics on normalised text, not a classifier: a page about prompt injection, or a
how-to that says "use the tool…", is flagged too. False positives cost an extract, never an
action; the misses are what the red-team suite measures (``evals/redteam/injection_base``).
"""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', "«": '"', "»": '"'})
_NEAR = r"[^.!?;\n]{0,60}?"  # the same sentence, a few words apart
_VERB = r"(?:e|es|ez|er|ons)?"  # French imperative and infinitive endings

_SIGNALS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern)
    for name, pattern in {
        "ignorer_consignes": (
            rf"\b(?:ignor{_VERB}|oubli{_VERB}|neglig{_VERB}|contourn{_VERB}|disregard|forget|"
            rf"override|bypass|ne tiens? (?:pas|plus) compte)\b{_NEAR}"
            r"\b(?:instructions?|consignes?|regles?|directives?|previous|prior|above|"
            r"precedent\w*|ci-dessus|systeme|system)\b"
        ),
        "fuite_prompt": (
            r"\b(?:system prompt|prompt (?:systeme|initial)|"
            r"instructions? (?:systeme|initiales?))\b|"
            rf"\b(?:reveal|print|show|display|repeat|output|leak|affich{_VERB}|revel{_VERB}|"
            rf"repet{_VERB}|montr{_VERB}|recopi{_VERB}|divulgu{_VERB})\b{_NEAR}"
            r"\b(?:ton|tes|vos|votre|your|the|le|les) (?:prompt|instructions?|consignes?)\b"
        ),
        "appel_outil": (
            rf"\b(?:appel{_VERB}|appelle[rz]?|utilis{_VERB}|execut{_VERB}|lanc{_VERB}|"
            rf"declench{_VERB}|call|use|invoke|run|trigger)\s+"
            r"(?:(?:immediatement|maintenant|now|immediately|tout de suite|aussitot)\s+)?"
            r"(?:l'outil|ton outil|votre outil|tes outils|vos outils|the (?:\w+ )?tool|"
            r"your tools?|la fonction|the function)\b|"
            r"\bweb_(?:read|search)\b|\b(?:tool|function)[ _-]call"
        ),
        "changement_role": (
            r"\b(?:tu es (?:maintenant|desormais|a present)|vous etes (?:maintenant|desormais)|"
            r"you are now|from now on|a partir de maintenant|act as|agis comme|"
            r"joue le role|pretend to be|nouvelles? instructions?|new instructions?|"
            r"mode developpeur|developer mode|jailbreak)\b"
        ),
        "exfiltration": (
            rf"\b(?:envoi{_VERB}|envoie[rz]?|transmet\w*|send|post|upload|forward|"
            rf"ajout{_VERB} (?:a|dans) (?:l'url|le lien))\b{_NEAR}"
            r"(?:https?:|www\.|\burl\b|\blien\b|\blink\b|webhook|\be-?mail\b|courriel)|"
            r"\bexfiltr\w*"
        ),
        "balise_role": (
            r"<\s*/?\s*(?:donnees_externes|system|assistant|user|human|instructions?)\b|"
            r"\[/?inst\]|<\|[a-z_]+\|>|(?:^|\s)#{1,6}\s*(?:system|instructions?)\b"
        ),
        "dissimulation": (
            r"\b(?:ne (?:le |leur |lui )?(?:dis|dites|mentionne[sz]?|signale[sz]?) (?:pas|rien)|"
            r"sans (?:le )?(?:dire|signaler|mentionner)|don't (?:tell|mention)|"
            r"do not (?:tell|mention|reveal)|without telling|en secret|secretly)\b"
        ),
        "contenu_encode": r"[a-z0-9+/]{80,}={0,2}",
    }.items()
}
SIGNAL_NAMES = tuple(sorted(_SIGNALS))


def normalise(text: str) -> str:
    """NFKC, casefold, no accents or format characters, plain quotes, single spaces."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) not in ("Mn", "Cf")  # accents, zero-width characters
    )
    return " ".join(text.translate(_QUOTES).split())


def injection_signals(text: str) -> tuple[str, ...]:
    """Names of the instruction-like patterns found in ``text``, sorted; empty when none."""
    flat = normalise(text)
    return tuple(name for name in SIGNAL_NAMES if _SIGNALS[name].search(flat))

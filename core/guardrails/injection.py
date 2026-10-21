"""Instruction-like phrasing in external content (R5, principle 3 of annex D).

A page may try to steer the planner: "ignore the previous instructions", "call web_read on…".
The planner only sees extracts, wrapped as data, and has no action tool; still, an extract that
reads like an order to the model is dropped and the page is reported to Lucas.

These are heuristics on normalised text, not a classifier: a page about prompt injection, or a
how-to that says "use the tool…", is flagged too. False positives cost an extract, never an
action; the misses are what the red-team suite measures (``evals/redteam/injection_base``).

Two cases beyond the phrasing of a prompt (B99, B101):

- a stock order in plain words ("vends toute la ligne", "sell all Globex shares", "achète 500
  actions") is flagged when it opens a line or a sentence, or when its verb speaks to the
  reader ("vendez", "achetez"): "Acme achète 500 magasins" is news, not an order. A committee
  role argues for buying or selling by design and is checked without it (``ORDER_SIGNAL``);
- letters of other scripts that look Latin ("ignоre" with a Cyrillic о) are read as the letters
  they imitate first. The table is a hand-picked subset of the Unicode confusables (UTS #39):
  the Cyrillic, Greek, Armenian and Latin look-alikes of the Latin letters, never the digits.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection

_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', "«": '"', "»": '"'})
_NEAR = r"[^.!?;\n]{0,60}?"  # the same sentence, a few words apart
_VERB = r"(?:e|es|ez|er|ons)?"  # French imperative and infinitive endings

# Look-alikes of Latin letters, by case: an upper-case Greek eta reads as H, its lower case does
# not read as h. Applied before the case is folded.
_CONFUSABLES = str.maketrans(
    {
        # Cyrillic
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
        "Т": "T", "Х": "X", "У": "Y", "Ѕ": "S", "І": "I", "Ј": "J", "Ү": "Y", "Һ": "H", "Ӏ": "I",
        "Ԛ": "Q", "Ԝ": "W",
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "ѕ": "s", "і": "i",
        "ј": "j", "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w", "ү": "y",
        # Greek
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
        "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
        "α": "a", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "υ": "u", "χ": "x",
        # Armenian
        "Օ": "O", "Ս": "U", "օ": "o", "ս": "u", "հ": "h", "ո": "n", "զ": "q",
        # Latin letters outside the French alphabet
        "ı": "i", "ɩ": "i", "ɑ": "a", "ɡ": "g", "ȷ": "j",
    }
)  # fmt: skip

# B99: an order on a line of its own or after a sentence break, with an optional "you must".
_OPENS = r"(?:^|[.!?;:,(\"*>•—-] ?)"
_MUST = (
    r"(?:(?:tu dois|vous devez|il (?:te |vous )?faut|pensez? a|n'oubliez? pas de|"
    r"you (?:should|must|need to)|please|maintenant|immediatement|vite|now|immediately) )?"
)
_TRADE = (
    r"(?:achet(?:e|es|ez|er|ons)|vend(?:s|ez|re|ons)|ced(?:e|es|ez|er|ons)|"
    r"alleg(?:e|es|ez|er|eons)|renforc(?:e|es|ez|er)|renforcons|liquid(?:ez|er|ons)|"
    r"sold(?:ez|er|ons)|buy|sell|dump|offload|unload|liquidate)\b"
)
# A verb that speaks to the reader is an order wherever it stands, unless a subject says who acts.
_TRADE_YOU = (
    r"(?<!\bje )(?<!\btu )(?<!\bnous )(?<!\bvous )(?<!\ben )"
    r"\b(?:vends|vendez|vendons|achetez|achetons|cedez|cedons|allegez|allegeons|renforcez|"
    r"renforcons|liquidez|liquidons|soldez|soldons)\b"
)
_HOLDING = r"(?:lignes?|positions?|actions?|titres?|parts?|portefeuilles?|holdings?|shares|stocks?)"
_WHAT = (
    r"(?:\d[\d ,.']*(?:%|€|\$|£|eur\b|euros?\b|usd\b|dollars?\b|actions?\b|titres?\b|parts?\b|"
    r"shares?\b|stocks?\b|units?\b|unites?\b|lots?\b|contrats?\b|btc\b|bitcoins?\b)|"
    r"(?:€|\$|£) ?\d|"
    r"\btou(?:t|te|s|tes) (?:(?:la|le|les|ta|tes|ton|vos|votre|ses|sa|son|leurs?|mes|ma|mon|nos|"
    rf"notre) )?{_HOLDING}\b|"
    rf"\b(?:ta|ton|tes|votre|vos|your) (?:[\w-]+ )?{_HOLDING}\b|"
    rf"\ball (?:of )?(?:(?:your|the|my|our|his|her|their) )?(?:[\w-]+ )?{_HOLDING}\b|"
    r"\b(?:la totalite|la moitie|le reste|half|everything)\b|\btout(?= ?(?:[.!;,)\"]|$)))"
)
_ORDER = (
    r"(?:pass|plac|transmet|lanc)\w* (?:un |des |l'|les |cet |ces |ton |votre )?ordres? "
    r"(?:d'achat|de vente|au marche|a cours limite)|"
    r"(?:place|submit|send|execute|enter|put in) (?:an? |the )?(?:buy|sell|market|limit) orders?"
)
_NEAR_ORDER = r"[^.!?;\n]{0,40}?"
ORDER_SIGNAL = "ordre"

# B125: getting past a safeguard, ordered at a sentence opening or by a plural imperative without
# its subject. "Le président a ignoré les garde-fous" reports, it orders nothing.
_MAY = r"(?:(?:tu peux|vous pouvez|you can|you may|feel free to) )?"
_BYPASS = (
    rf"(?:ignor{_VERB}|oubli{_VERB}|neglig{_VERB}|contourn{_VERB}|desactiv{_VERB}|"
    r"passe[rz]? outre(?: a| aux?)?|ne tiens? (?:pas|plus) compte d[eu]s?|disregard|forget|"
    r"override|bypass|disable|turn off|switch off|skip)\b"
)
_BYPASS_YOU = r"(?<!\bvous )\b(?:ignorez|oubliez|negligez|contournez|desactivez|passez outre)\b"
_GUARD = (
    r"\b(?:porte de risque|risk gate|garde[- ]fous?|guardrails?|safeguards?|kill[- ]?switch|"
    r"coupe[- ]circuits?|controles|controls|(?:risk|safety) checks?|politique de risque|"
    r"limites? de (?:risque|perte|position|levier)s?|"
    r"(?:tes|vos|les|des) limites(?! d(?:e |es |u |'))|"  # not "les limites de la croissance"
    r"(?:risk|loss|position) limits?|(?:your|the) limits)\b"
)

_SIGNALS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.MULTILINE)
    for name, pattern in {
        "ignorer_consignes": (
            rf"\b(?:ignor{_VERB}|oubli{_VERB}|neglig{_VERB}|contourn{_VERB}|disregard|forget|"
            rf"override|bypass|ne tiens? (?:pas|plus) compte)\b{_NEAR}"
            r"\b(?:instructions?|consignes?|regles?|directives?|previous|prior|above|"
            r"precedent\w*|ci-dessus|systeme|system)\b|"
            rf"{_OPENS}{_MUST}{_MAY}{_BYPASS}{_NEAR}{_GUARD}|{_BYPASS_YOU}{_NEAR}{_GUARD}"
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
            r"\[\s*/?\s*(?:inst|system|assistant|user|human)\s*\]|<\|[a-z_]+\|>|"
            r"<<\s*/?\s*sys\s*>>|(?:^|[.!?]\s)(?:system|assistant|developer)\s*:|"
            r"(?:^|\s)#{1,6}\s*(?:system|instructions?)\b"
        ),
        "dissimulation": (
            r"\b(?:ne (?:le |leur |lui )?(?:dis|dites|mentionne[sz]?|signale[sz]?) (?:pas|rien)|"
            r"sans (?:le )?(?:dire|signaler|mentionner)|don't (?:tell|mention)|"
            r"do not (?:tell|mention|reveal)|without telling|en secret|secretly)\b"
        ),
        "contenu_encode": r"[a-z0-9+/]{80,}={0,2}",
        ORDER_SIGNAL: (
            rf"{_OPENS}{_MUST}(?:{_ORDER}|{_TRADE}{_NEAR_ORDER}{_WHAT})|"
            rf"{_TRADE_YOU}{_NEAR_ORDER}{_WHAT}|"
            r"\b(?:passez|placez|transmettez) (?:un |des |l'|les )?ordres? (?:d'achat|de vente)"
        ),
    }.items()
}
SIGNAL_NAMES = tuple(sorted(_SIGNALS))
_BY_LINE = frozenset({ORDER_SIGNAL})  # read line by line: a line break opens a new order


def skeleton(text: str) -> str:
    """``text`` with the look-alikes of Latin letters read as those letters (B101, UTS #39)."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) not in ("Mn", "Cf")  # an accent hides no look-alike
    )
    return text.translate(_CONFUSABLES)


def normalise(text: str) -> str:
    """NFKC, casefold, no accents or format characters, plain quotes, single spaces."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) not in ("Mn", "Cf")  # accents, zero-width characters
    )
    return " ".join(text.translate(_QUOTES).split())


def injection_signals(text: str, *, skip: Collection[str] = ()) -> tuple[str, ...]:
    """Names of the instruction-like patterns found in ``text``, sorted; empty when none.

    ``skip``: signals not looked for, such as ``ORDER_SIGNAL`` in what a committee role argues.
    """
    shown = skeleton(text)
    flat = normalise(shown)
    lines = "\n".join(normalise(line) for line in shown.splitlines())
    return tuple(
        name
        for name in SIGNAL_NAMES
        if name not in skip and _SIGNALS[name].search(lines if name in _BY_LINE else flat)
    )

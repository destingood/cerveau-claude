"""A small lexical ranking of memories for a request (BM25, standard library only).

Words are folded (lower case, accents removed: « préférée » and « PREFEREE » are one word), short
words and common French and English function words are dropped, and a final « s » or « x » of a
long word is removed so that a plural matches its singular. The score is Okapi BM25 (k1 = 1.2,
b = 0.75) over the memories in scope; the title counts twice.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from core.memory.rules import fold

K1, B = 1.2, 0.75
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS_TEXT = (
    "le la les un une des du de et ou au aux en dans sur pour par avec sans ce cet cette ces "
    "mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs je tu il elle on nous "
    "vous ils elles qui que quoi dont est sont etre avoir ai as ont pas ne plus se mais "
    "comme si tout tous toute toutes quel quelle quels quelles the of and to in is it for on "
    "with what how"
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for word in _WORD.findall(fold(text)):
        if len(word) < 2 or word in STOPWORDS:
            continue
        if len(word) > 4 and word[-1] in "sx":
            word = word[:-1]
        out.append(word)
    return out


def bm25(query: Sequence[str], documents: Sequence[Sequence[str]]) -> list[float]:
    """The BM25 score of each document for the query's distinct words (0 for no common word)."""
    count = len(documents)
    if not count:
        return []
    terms = set(query)
    frequency = Counter(term for doc in documents for term in set(doc) if term in terms)
    average = sum(len(doc) for doc in documents) / count or 1.0
    scores: list[float] = []
    for doc in documents:
        found = Counter(term for term in doc if term in terms)
        score = 0.0
        for term, times in found.items():
            df = frequency[term]
            idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
            score += idf * times * (K1 + 1) / (times + K1 * (1 - B + B * len(doc) / average))
        scores.append(score)
    return scores

"""French PII pseudonymisation with Presidio's analyzer and our own replacement (ADR-010).

``PiiAnalyzer`` is built once per process: spaCy ``fr_core_news_md`` for PERSON and LOCATION,
Presidio's EMAIL, IBAN and CREDIT_CARD recognizers declared for French, and our FR_PHONE, FR_NIR
(control key) and IP recognizers. ``Pseudonymiser`` lives for one request: it replaces each entity
with a ``<LABEL_n>`` pseudonym, gives the same text the same pseudonym, and keeps the mapping in
memory only, for the final re-identification. The mapping is never journaled, never logged and
never sent to a model; ``counts()`` is the only thing the journal may record.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar

import spacy.util
import tldextract
from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    SpacyRecognizer,
)

from core.config.loader import Config, PiiConfig

LANGUAGE = "fr"
PSEUDONYM = re.compile(r"\\?<([A-Z][A-Z_]*)_(\d+)\\?>")

# Presidio's EmailRecognizer validates with the module-level tldextract, which downloads the
# public suffix list on first use. This one only reads the snapshot shipped with the package.
_OFFLINE_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class PiiUnavailableError(Exception):
    """Pseudonymisation cannot run (model missing, entity without recognizer, no threshold)."""


class OfflineEmailRecognizer(EmailRecognizer):
    def validate_result(self, pattern_text: str) -> bool:
        return _OFFLINE_TLD(pattern_text).fqdn != ""


class FrPhoneRecognizer(PatternRecognizer):
    """French numbers: 0X XX XX XX XX or +33 / 0033, with spaces, dots or dashes."""

    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "fr_phone",
            r"(?<![\w+])(?:(?:\+|00)33[\s.-]?(?:\(0\)[\s.-]?)?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\w)",
            0.6,
        )
    ]
    CONTEXT: ClassVar[list[str]] = [
        "téléphone",
        "tél",
        "tel",
        "portable",
        "mobile",
        "appeler",
        "numéro",
        "joindre",
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="FR_PHONE",
            name="FrPhoneRecognizer",
            supported_language=LANGUAGE,
            patterns=self.PATTERNS,
            context=self.CONTEXT,
        )


def nir_key_is_valid(candidate: str) -> bool:
    """NIR control key: 97 - (13 first digits mod 97), Corsica 2A / 2B counted as 19 / 18."""
    digits = re.sub(r"\s", "", candidate).upper()
    if len(digits) != 15:
        return False
    department = {"2A": "19", "2B": "18"}.get(digits[5:7], digits[5:7])
    body = digits[:5] + department + digits[7:13]
    if not (body + digits[13:]).isdigit():
        return False
    return 97 - int(body) % 97 == int(digits[13:])


class FrNirRecognizer(PatternRecognizer):
    """French social security number (NIR), kept only when its control key is right."""

    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "fr_nir",
            r"(?<!\w)[1-478]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2[AB])\s?\d{3}\s?\d{3}\s?\d{2}(?!\w)",
            0.5,
        )
    ]
    CONTEXT: ClassVar[list[str]] = [
        "sécurité sociale",
        "sécu",
        "nir",
        "insee",
        "numéro de sécurité",
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="FR_NIR",
            name="FrNirRecognizer",
            supported_language=LANGUAGE,
            patterns=self.PATTERNS,
            context=self.CONTEXT,
        )

    def validate_result(self, pattern_text: str) -> bool:
        return nir_key_is_valid(pattern_text)


class IpRecognizer(PatternRecognizer):
    """IPv4 and IPv6 addresses, checked with ``ipaddress`` (score kept at 0.6 like Presidio's)."""

    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern("ipv4", r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w|\.\d)", 0.6),
        Pattern("ipv6", r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", 0.6),
    ]
    CONTEXT: ClassVar[list[str]] = ["ip", "adresse", "serveur", "routeur", "réseau"]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IP_ADDRESS",
            name="FrIpRecognizer",
            supported_language=LANGUAGE,
            patterns=self.PATTERNS,
            context=self.CONTEXT,
        )

    def invalidate_result(self, pattern_text: str) -> bool:
        try:
            ipaddress.ip_address(pattern_text)
        except ValueError:
            return True
        return False


def _recognizers() -> list[EntityRecognizer]:
    return [
        SpacyRecognizer(supported_language=LANGUAGE, supported_entities=["PERSON", "LOCATION"]),
        OfflineEmailRecognizer(
            supported_language=LANGUAGE, context=["courriel", "mail", "e-mail", "adresse"]
        ),
        IbanRecognizer(supported_language=LANGUAGE, context=["iban", "rib", "compte", "virement"]),
        CreditCardRecognizer(
            supported_language=LANGUAGE, context=["carte", "cb", "visa", "mastercard", "paiement"]
        ),
        FrPhoneRecognizer(),
        FrNirRecognizer(),
        IpRecognizer(),
    ]


@dataclass(frozen=True)
class Detection:
    start: int
    end: int
    entity: str
    score: float


def resolve_overlaps(results: Iterable[RecognizerResult]) -> list[Detection]:
    """Keep the best non-overlapping spans: higher score first, then the longer span."""
    ordered = sorted(results, key=lambda r: (-r.score, -(r.end - r.start), r.start))
    kept: list[Detection] = []
    for r in ordered:
        if r.end > r.start and all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(Detection(r.start, r.end, r.entity_type, r.score))
    return sorted(kept, key=lambda d: d.start)


class PiiAnalyzer:
    """The Presidio engine for French text; loads spaCy once (about 2 s)."""

    def __init__(self, pii: PiiConfig) -> None:
        if isinstance(pii.score_threshold, str):
            raise PiiUnavailableError(f"seuil de score Presidio = {pii.score_threshold}")
        if not spacy.util.is_package(pii.spacy_model):
            # SpacyNlpEngine.load() would download it: no network here, install with uv sync.
            raise PiiUnavailableError(f"modèle spaCy « {pii.spacy_model} » non installé")
        registry = RecognizerRegistry(supported_languages=[LANGUAGE])
        for recognizer in _recognizers():
            registry.add_recognizer(recognizer)
        supported = set(registry.get_supported_entities([LANGUAGE]))
        missing = sorted(set(pii.entities) - supported)
        if missing:
            raise PiiUnavailableError("entités sans recognizer : " + ", ".join(missing))
        nlp = SpacyNlpEngine(models=[{"lang_code": LANGUAGE, "model_name": pii.spacy_model}])
        nlp.load()
        self.labels: Mapping[str, str] = dict(pii.entities)
        self.score_threshold = float(pii.score_threshold)
        self._engine = AnalyzerEngine(
            registry=registry, nlp_engine=nlp, supported_languages=[LANGUAGE]
        )

    @classmethod
    def from_config(cls, config: Config) -> PiiAnalyzer:
        config.require("guardrails.pii")  # BlockedFeatureError while a marker remains
        return cls(config.guardrails.pii)

    def detect(self, text: str) -> list[Detection]:
        results = self._engine.analyze(
            text=text,
            language=LANGUAGE,
            entities=list(self.labels),
            score_threshold=self.score_threshold,
        )
        protected = [m.span() for m in PSEUDONYM.finditer(text)]
        return [
            d
            for d in resolve_overlaps(results)
            if all(d.end <= start or d.start >= end for start, end in protected)
        ]


def _key(label: str, value: str) -> tuple[str, str]:
    return label, " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class Pseudonymiser:
    """Reversible pseudonyms for one request. Its repr shows counts only, never the mapping."""

    def __init__(self, analyzer: PiiAnalyzer) -> None:
        self._analyzer = analyzer
        self._pseudonyms: dict[tuple[str, str], str] = {}
        self._originals: dict[str, str] = {}
        self._next: Counter[str] = Counter()
        self._counts: Counter[str] = Counter()

    def __repr__(self) -> str:
        return f"Pseudonymiser(counts={dict(sorted(self._counts.items()))})"

    __str__ = __repr__

    def _pseudonym(self, entity: str, value: str) -> str:
        label = self._analyzer.labels[entity]
        key = _key(label, value)
        if key not in self._pseudonyms:
            self._next[label] += 1
            token = f"<{label}_{self._next[label]}>"
            self._pseudonyms[key] = token
            self._originals[token] = value
        return self._pseudonyms[key]

    def pseudonymise(self, text: str) -> str:
        parts: list[str] = []
        cursor = 0
        for d in self._analyzer.detect(text):
            parts.append(text[cursor : d.start])
            parts.append(self._pseudonym(d.entity, text[d.start : d.end]))
            self._counts[d.entity] += 1
            cursor = d.end
        parts.append(text[cursor:])
        return "".join(parts)

    def reidentify(self, text: str) -> str:
        """Put the originals back; unknown pseudonyms are left as they are."""

        def original(match: re.Match[str]) -> str:
            token = f"<{match.group(1)}_{match.group(2)}>"
            return self._originals.get(token, match.group(0))

        return PSEUDONYM.sub(original, text)

    def counts(self) -> dict[str, int]:
        """Entities replaced so far, per Presidio type: the only part fit for the journal."""
        return dict(sorted(self._counts.items()))

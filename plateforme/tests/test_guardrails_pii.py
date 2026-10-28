"""French pseudonymisation (ADR-010): detection, overlaps, reversibility and no leak of the map."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from presidio_analyzer import RecognizerResult

from core.config.loader import BlockedFeatureError, PiiConfig, load_config
from core.guardrails.pii import (
    FrNirRecognizer,
    FrPhoneRecognizer,
    IpRecognizer,
    PiiAnalyzer,
    PiiUnavailableError,
    Pseudonymiser,
    nir_key_is_valid,
    resolve_overlaps,
)

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
NIR = "1 85 05 78 006 084 91"
NIR_CORSICA = "2 90 01 2A 004 012 02"
CARD = "4111 1111 1111 1111"  # Luhn-valid test number
IBAN = "FR76 3000 6000 0112 3456 7890 189"


def pii_config(**update: Any) -> PiiConfig:
    return load_config(REPO_CONFIG).guardrails.pii.model_copy(
        update={"score_threshold": 0.5, **update}
    )


@pytest.fixture(scope="module")
def analyzer() -> PiiAnalyzer:
    return PiiAnalyzer(pii_config())


def detected(analyzer: PiiAnalyzer, text: str) -> list[tuple[str, str]]:
    return [(d.entity, text[d.start : d.end]) for d in analyzer.detect(text)]


def matches(recognizer: Any, text: str) -> list[str]:
    results = recognizer.analyze(text, recognizer.supported_entities)
    return [text[r.start : r.end] for r in results]


def test_an_undefined_threshold_blocks_the_feature(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, config_dir)
    guardrails = config_dir / "guardrails.yaml"
    text = guardrails.read_text(encoding="utf-8")
    text = re.sub(r"score_threshold: .*", "score_threshold: A_DEFINIR", text)
    guardrails.write_text(text, encoding="utf-8")
    with pytest.raises(BlockedFeatureError, match="score_threshold"):
        PiiAnalyzer.from_config(load_config(config_dir))
    with pytest.raises(PiiUnavailableError, match="A_DEFINIR"):
        PiiAnalyzer(pii_config(score_threshold="A_DEFINIR"))


def test_a_missing_spacy_model_is_refused_instead_of_downloaded() -> None:
    with pytest.raises(PiiUnavailableError, match=r"fr_core_news_lg.*non installé"):
        PiiAnalyzer(pii_config(spacy_model="fr_core_news_lg"))


def test_an_entity_without_recognizer_is_refused() -> None:
    entities = {**pii_config().entities, "FR_SIREN": "SIREN"}
    with pytest.raises(PiiUnavailableError, match="sans recognizer : FR_SIREN"):
        PiiAnalyzer(pii_config(entities=entities))


def test_a_french_sample_is_fully_detected(analyzer: PiiAnalyzer) -> None:
    text = (
        "Bonjour, je suis Marie Dupont et j'habite à Lyon. Écris à marie.dupont@example.org, "
        f"IBAN {IBAN}, carte {CARD}, téléphone 06 12 34 56 78, sécurité sociale {NIR}, "
        "serveur 192.168.1.20."
    )
    found = detected(analyzer, text)
    for expected in [
        ("PERSON", "Marie Dupont"),
        ("LOCATION", "Lyon"),
        ("EMAIL_ADDRESS", "marie.dupont@example.org"),
        ("IBAN_CODE", IBAN),
        ("CREDIT_CARD", CARD),
        ("FR_PHONE", "06 12 34 56 78"),
        ("FR_NIR", NIR),
        ("IP_ADDRESS", "192.168.1.20"),
    ]:
        assert expected in found


def test_an_email_is_validated_offline(analyzer: PiiAnalyzer) -> None:
    # pytest-socket blocks the network: the public suffix list comes from the snapshot.
    assert detected(analyzer, "contact : jean@exemple.fr") == [("EMAIL_ADDRESS", "jean@exemple.fr")]
    assert detected(analyzer, "contact : jean@exemple.invalidtld") == []


def test_a_card_failing_luhn_is_ignored(analyzer: PiiAnalyzer) -> None:
    assert ("CREDIT_CARD", "4111 1111 1111 1112") not in detected(
        analyzer, "carte 4111 1111 1111 1112"
    )


@pytest.mark.parametrize(
    "number",
    [
        "06 12 34 56 78",
        "06.12.34.56.78",
        "06-12-34-56-78",
        "0612345678",
        "+33 6 12 34 56 78",
        "+33612345678",
        "0033 6 12 34 56 78",
        "+33 (0)6 12 34 56 78",
        "01 23 45 67 89",
    ],
)
def test_french_phone_numbers(number: str) -> None:
    assert matches(FrPhoneRecognizer(), f"appelle le {number} demain") == [number]


@pytest.mark.parametrize(
    "text", ["1234567890", "06 12 34 56", "061234567890", "00 12 34 56 78", "+44 6 12 34 56 78"]
)
def test_not_french_phone_numbers(text: str) -> None:
    assert matches(FrPhoneRecognizer(), f"code {text} ici") == []


@pytest.mark.parametrize("nir", [NIR, NIR.replace(" ", ""), NIR_CORSICA, NIR_CORSICA.lower()])
def test_nir_with_a_valid_key(nir: str) -> None:
    assert matches(FrNirRecognizer(), f"numéro {nir}.") == [nir]


@pytest.mark.parametrize("nir", [NIR[:-2] + "92", NIR_CORSICA[:-2] + "03", "5 85 05 78 006 084 91"])
def test_nir_with_a_wrong_key_or_sex_digit(nir: str) -> None:
    assert matches(FrNirRecognizer(), f"numéro {nir}.") == []


@given(st.from_regex(r"[1-478]\d{12}", fullmatch=True))
def test_the_nir_key_accepts_the_right_key_only(body: str) -> None:
    key = 97 - int(body) % 97
    assert nir_key_is_valid(f"{body}{key:02d}")
    assert not nir_key_is_valid(f"{body}{key % 97 + 1:02d}")


@pytest.mark.parametrize("address", ["192.168.1.20", "8.8.8.8", "2001:db8::1", "fe80::1"])
def test_ip_addresses(address: str) -> None:
    assert matches(IpRecognizer(), f"serveur {address}, port 80") == [address]


@pytest.mark.parametrize("text", ["999.1.1.1", "12:30:45", "version 3.8.16", "1.2.3.4.5"])
def test_not_ip_addresses(text: str) -> None:
    assert matches(IpRecognizer(), f"valeur {text} ici") == []


def result(entity: str, start: int, end: int, score: float) -> RecognizerResult:
    return RecognizerResult(entity_type=entity, start=start, end=end, score=score)


def test_overlaps_keep_the_higher_score_then_the_longer_span() -> None:
    kept = resolve_overlaps(
        [
            result("LOCATION", 0, 9, 0.85),
            result("IBAN_CODE", 5, 38, 1.0),
            result("PERSON", 40, 45, 0.85),
            result("PERSON", 40, 52, 0.85),
            result("LOCATION", 52, 56, 0.85),  # adjacent, not overlapping
            result("PERSON", 60, 60, 0.85),  # empty span
        ]
    )
    assert [(d.entity, d.start, d.end) for d in kept] == [
        ("IBAN_CODE", 5, 38),
        ("PERSON", 40, 52),
        ("LOCATION", 52, 56),
    ]


def test_pseudonyms_are_stable_and_reversible(analyzer: PiiAnalyzer) -> None:
    text = "Marie Dupont habite à Lyon. Paul Martin écrit à Marie Dupont, à Lyon."
    p = Pseudonymiser(analyzer)
    masked = p.pseudonymise(text)
    assert masked == (
        "<PERSONNE_1> habite à <LIEU_1>. <PERSONNE_2> écrit à <PERSONNE_1>, à <LIEU_1>."
    )
    assert p.reidentify(masked) == text
    assert p.counts() == {"LOCATION": 2, "PERSON": 3}


def test_the_same_entity_keeps_its_pseudonym_across_texts_of_a_request(
    analyzer: PiiAnalyzer,
) -> None:
    p = Pseudonymiser(analyzer)
    assert p.pseudonymise("Appelle Marie Dupont.") == "Appelle <PERSONNE_1>."
    assert p.pseudonymise("MARIE  DUPONT a répondu.").startswith("<PERSONNE_1>")
    assert p.reidentify("<PERSONNE_1> !") == "Marie Dupont !"


def test_pseudonymising_twice_changes_nothing(analyzer: PiiAnalyzer) -> None:
    p = Pseudonymiser(analyzer)
    masked = p.pseudonymise("Marie Dupont habite à Lyon.")
    assert p.pseudonymise(masked) == masked
    assert p.counts() == {"LOCATION": 1, "PERSON": 1}


def test_reidentify_handles_escapes_and_unknown_pseudonyms(analyzer: PiiAnalyzer) -> None:
    p = Pseudonymiser(analyzer)
    p.pseudonymise("Marie Dupont")
    assert p.reidentify(r"\<PERSONNE_1\> et <PERSONNE_9>") == "Marie Dupont et <PERSONNE_9>"


def test_the_mapping_never_shows_in_repr(analyzer: PiiAnalyzer) -> None:
    p = Pseudonymiser(analyzer)
    p.pseudonymise(f"Marie Dupont, {NIR}")
    for shown in (repr(p), str(p), f"{p}"):
        assert "Marie" not in shown
        assert NIR not in shown
    assert repr(p) == "Pseudonymiser(counts={'FR_NIR': 1, 'PERSON': 1})"


def test_text_without_personal_data_is_unchanged(analyzer: PiiAnalyzer) -> None:
    p = Pseudonymiser(analyzer)
    text = "Quel est le taux du livret A en 2026 ?"
    assert p.pseudonymise(text) == text
    assert p.counts() == {}

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config.loader import LEVELS, AutonomyConfig, load_config
from core.governance import signatures
from core.governance.signatures import (
    MAX_BYTES,
    MAX_REPORT_BYTES,
    PROMOTION_DIR,
    REPORT_PASSED,
    SIGNATURES_DIR,
    SignedLevels,
    effective_autonomy,
    effective_level,
    promoted_domains,
    read_signatures,
    signature_text,
)
from tests.signing import report_text, sign

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = load_config(ROOT / "config").autonomy
DAY = date(2026, 10, 21)


def _at(level: str, *, generaliste: str = "N1") -> AutonomyConfig:
    data = AUTONOMY.model_dump()
    data["domains"]["finance"]["level"] = level
    data["domains"]["generaliste"]["level"] = generaliste
    return AutonomyConfig.model_validate(data)


def _write(root: Path, name: str, text: str | bytes) -> Path:
    path = root / SIGNATURES_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_finance_is_the_only_promoted_domain() -> None:
    assert promoted_domains(AUTONOMY) == frozenset({"finance"})


def test_the_repository_signs_nothing_and_finance_stays_at_n0() -> None:
    signed = read_signatures(ROOT)
    assert signed.signatures == ()
    assert signed.problems == ()
    assert effective_level(AUTONOMY, ROOT, "finance") == "N0"
    assert effective_level(AUTONOMY, ROOT, "generaliste") == "N1"


def test_without_a_folder_nothing_is_signed(tmp_path: Path) -> None:
    assert read_signatures(tmp_path) == SignedLevels((), ())
    assert read_signatures(tmp_path).highest("finance") == "N0"


@pytest.mark.parametrize("written", LEVELS)
def test_editing_autonomy_yaml_alone_promotes_nothing(tmp_path: Path, written: str) -> None:
    result = effective_autonomy(_at(written), tmp_path)
    assert result.autonomy.domains["finance"].level == "N0"
    assert result.capped == (() if written == "N0" else (f"finance : {written} écrit, N0 signé",))
    assert result.autonomy.domains["generaliste"].level == "N1"


@pytest.mark.parametrize("signed", ["N1", "N2"])
def test_a_signature_below_n3_needs_no_report(tmp_path: Path, signed: str) -> None:
    sign(tmp_path, "finance", signed, DAY)
    assert effective_level(_at("N4"), tmp_path, "finance") == signed
    assert effective_level(_at("N1"), tmp_path, "finance") == "N1"  # demotion is immediate


@pytest.mark.parametrize("signed", ["N3", "N4"])
def test_from_n3_the_cited_report_must_exist(tmp_path: Path, signed: str) -> None:
    sign(tmp_path, "finance", signed, DAY, report=False)
    signed_levels = read_signatures(tmp_path)
    assert signed_levels.signatures == ()
    (problem,) = signed_levels.problems
    assert "aucun rapport de promotion" in problem
    assert effective_level(_at("N4"), tmp_path, "finance") == "N0"
    sign(tmp_path, "finance", signed, DAY)
    assert effective_level(_at("N4"), tmp_path, "finance") == signed


def test_a_report_with_another_digest_does_not_count(tmp_path: Path) -> None:
    sign(tmp_path, "finance", "N3", DAY, report=False)
    (tmp_path / PROMOTION_DIR).mkdir(parents=True)
    (tmp_path / PROMOTION_DIR / "rapport.md").write_text("autre rapport", encoding="utf-8")
    assert effective_level(_at("N3"), tmp_path, "finance") == "N0"


@pytest.mark.parametrize("statut", ["promotion_impossible", "non_evaluable", "possible"])
def test_a_report_refusing_the_promotion_carries_no_signature(tmp_path: Path, statut: str) -> None:
    sign(tmp_path, "finance", "N3", DAY, statut=statut)
    signed = read_signatures(tmp_path)
    assert signed.signatures == ()
    (problem,) = signed.problems
    assert f"conclut « {statut} », pas « {REPORT_PASSED} »" in problem
    assert effective_level(_at("N3"), tmp_path, "finance") == "N0"


def _cite(root: Path, report: bytes) -> str:
    """Sign finance N3 citing ``report``; the one problem the signature raises."""
    (root / PROMOTION_DIR).mkdir(parents=True, exist_ok=True)
    (root / PROMOTION_DIR / "rapport.md").write_bytes(report)
    digest = hashlib.sha256(report).hexdigest()
    _write(root, f"{DAY.isoformat()}-finance-N3.md", signature_text("finance", "N3", DAY, digest))
    (problem,) = read_signatures(root, today=DAY).problems
    return problem


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (report_text("finance", "N4", DAY), "le rapport cité porte sur finance N4"),
        (report_text("recherche", "N3", DAY), "le rapport cité porte sur recherche N3"),
        (b"# Rapport sans en-tete\n", "n'a pas l'en-tête d'un rapport de promotion"),
        (
            b"---\nrapport: autre\ndomain: finance\nlevel: N3\nstatut: promotion_possible\n---\n",
            "n'a pas l'en-tête",
        ),
        (
            b"---\nrapport: promotion\nlevel: N3\nstatut: promotion_possible\n---\n",
            "n'a pas l'en-tête",
        ),
        (b"---\n\xff\n---\n", "n'a pas l'en-tête"),
        (  # no genere_le (B240)
            b"---\nrapport: promotion\ndomain: finance\nlevel: N3\n"
            b"statut: promotion_possible\n---\n",
            "n'a pas l'en-tête",
        ),
        (  # a generation time without its offset is no instant at all
            report_text("finance", "N3", DAY, generated="2026-10-21T08:00:00"),
            "n'a pas l'en-tête",
        ),
        (b"---\n[: :\n---\n", "n'a pas l'en-tête"),
    ],
)
def test_the_cited_report_must_be_a_promotion_report_for_that_level(
    tmp_path: Path, report: bytes, expected: str
) -> None:
    assert expected in _cite(tmp_path, report)
    assert effective_level(_at("N4"), tmp_path, "finance") == "N0"


def test_the_highest_valid_signature_wins(tmp_path: Path) -> None:
    sign(tmp_path, "finance", "N1", date(2026, 1, 5))
    sign(tmp_path, "finance", "N2", date(2026, 4, 5))
    sign(tmp_path, "finance", "N3", DAY, report=False)  # invalid: ignored
    result = effective_autonomy(_at("N4"), tmp_path)
    assert result.autonomy.domains["finance"].level == "N2"
    assert result.capped == ("finance : N4 écrit, N2 signé",)
    assert len(result.problems) == 1


def test_a_signature_for_another_domain_raises_nothing_else(tmp_path: Path) -> None:
    sign(tmp_path, "recherche", "N2", DAY)
    assert effective_level(_at("N2"), tmp_path, "finance") == "N0"
    assert read_signatures(tmp_path).highest("recherche") == "N2"


def test_an_unpromoted_domain_keeps_its_written_level(tmp_path: Path) -> None:
    assert effective_level(_at("N0", generaliste="N0"), tmp_path, "generaliste") == "N0"
    assert effective_level(_at("N0"), tmp_path, "generaliste") == "N1"


def _header(**fields: str) -> str:
    base = {
        "domain": "finance",
        "level": "N2",
        "date": "2026-10-21",
        "promotion_report_sha256": f'"{"a" * 64}"',
        "signed_by": "lucas",
    } | fields
    body = "\n".join(f"{k}: {v}" for k, v in base.items() if v != "-")
    return f"---\n{body}\n---\nSigné à la main.\n"


@pytest.mark.parametrize(
    ("name", "text", "problem"),
    [
        ("2026-10-21-finance-N2.txt.md", _header(), "nom attendu"),
        ("21-10-2026-finance-N2.md", _header(), "nom attendu"),
        ("2026-10-21-finance-N5.md", _header(), "nom attendu"),
        ("2026-10-21-finance-N2.md", "pas d'en-tête\n", "en-tête YAML"),
        ("2026-10-21-finance-N2.md", "---\ndomain: [\n---\n", "YAML illisible"),
        ("2026-10-21-finance-N2.md", "---\n- liste\n---\n", "en-tête refusé"),
        ("2026-10-21-finance-N2.md", _header(signed_by="claude"), "signed_by"),
        ("2026-10-21-finance-N2.md", _header(level="N3"), "ne concordent pas"),
        ("2026-10-21-finance-N2.md", _header(domain="recherche"), "ne concordent pas"),
        ("2026-10-21-finance-N2.md", _header(date="2026-10-22"), "ne concordent pas"),
        ("2026-10-21-finance-N2.md", _header(date='"2026-10-21"'), "date"),
        ("2026-10-21-finance-N2.md", _header(promotion_report_sha256="abc"), "promotion_report"),
        ("2026-10-21-finance-N2.md", _header(signed_by="-"), "signed_by"),
        ("2026-10-21-finance-N2.md", _header(extra="1"), "extra"),
    ],
)
def test_a_malformed_signature_is_ignored_and_reported(
    tmp_path: Path, name: str, text: str, problem: str
) -> None:
    _write(tmp_path, name, text)
    signed = read_signatures(tmp_path)
    assert signed.signatures == ()
    (reported,) = signed.problems
    assert reported.startswith(name)
    assert problem in reported
    assert effective_level(_at("N2"), tmp_path, "finance") == "N0"


def test_other_files_are_not_signatures(tmp_path: Path) -> None:
    _write(tmp_path, "LISEZMOI.txt", "rien")
    assert read_signatures(tmp_path) == SignedLevels((), ())


def test_an_oversized_or_non_utf8_signature_is_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-21-finance-N1.md", _header(level="N1") + "x" * MAX_BYTES)
    _write(tmp_path, "2026-10-22-finance-N1.md", b"\xff\xfe")
    problems = read_signatures(tmp_path).problems
    assert [p.split(" : ")[1] for p in problems] == [f"plus de {MAX_BYTES} octets", "UTF-8 attendu"]


def test_a_folder_named_like_a_signature_is_ignored(tmp_path: Path) -> None:
    (tmp_path / SIGNATURES_DIR / "2026-10-21-finance-N1.md").mkdir(parents=True)
    (problem,) = read_signatures(tmp_path).problems
    assert "pas un fichier ordinaire" in problem


def test_a_symbolic_link_is_not_a_signature(tmp_path: Path) -> None:
    target = tmp_path / "ailleurs.md"
    target.write_text(signature_text("finance", "N1", DAY, "a" * 64), encoding="utf-8")
    link = tmp_path / SIGNATURES_DIR / "2026-10-21-finance-N1.md"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("liens symboliques indisponibles sur ce système")
    (problem,) = read_signatures(tmp_path).problems
    assert "pas un fichier ordinaire" in problem


def test_an_unreadable_folder_signs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign(tmp_path, "finance", "N1", DAY)

    def refuse(self: Path) -> object:
        raise PermissionError("refusé")

    monkeypatch.setattr(Path, "iterdir", refuse)
    signed = read_signatures(tmp_path)
    assert signed.signatures == ()
    assert signed.problems == ("governance/approvals illisible (PermissionError)",)


def test_an_unreadable_signature_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign(tmp_path, "finance", "N1", DAY)
    original = Path.open

    def refuse(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.parent.name == "approvals":
            raise PermissionError("refusé")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    (problem,) = read_signatures(tmp_path).problems
    assert problem == "2026-10-21-finance-N1.md : illisible (PermissionError)"


def test_unreadable_reports_refuse_n3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sign(tmp_path, "finance", "N3", DAY)
    sign(tmp_path, "finance", "N2", date(2026, 7, 1))
    original = Path.open

    def refuse(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.parent.name == "promotion":
            raise PermissionError("refusé")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    signed = read_signatures(tmp_path)
    assert signed.highest("finance") == "N2"
    (problem,) = signed.problems
    assert "rapport de promotion invérifiable" in problem


def test_a_signature_dated_after_today_does_not_count(tmp_path: Path) -> None:
    sign(tmp_path, "finance", "N2", DAY)
    before = date(2026, 10, 20)
    signed = read_signatures(tmp_path, today=before)
    assert signed.signatures == ()
    assert signed.problems == (
        "2026-10-21-finance-N2.md : datée du 21/10/2026, après aujourd'hui (20/10/2026)",
    )
    assert effective_level(_at("N2"), tmp_path, "finance", today=before) == "N0"
    assert effective_level(_at("N2"), tmp_path, "finance", today=DAY) == "N2"


def test_today_is_today_in_paris_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign(tmp_path, "finance", "N2", DAY)
    monkeypatch.setattr(signatures, "today_in_paris", lambda: date(2026, 10, 20))
    assert effective_level(_at("N2"), tmp_path, "finance") == "N0"
    monkeypatch.setattr(signatures, "today_in_paris", lambda: DAY)
    assert effective_level(_at("N2"), tmp_path, "finance") == "N2"


def test_today_in_paris_is_a_date() -> None:
    assert isinstance(signatures.today_in_paris(), date)


def _cite_dated(root: Path, report: bytes, level: str = "N3") -> str:
    """File ``report`` and a signature of ``level`` on DAY citing it; the signature's name."""
    (root / PROMOTION_DIR).mkdir(parents=True, exist_ok=True)
    (root / PROMOTION_DIR / f"rapport-{level}.md").write_bytes(report)
    digest = hashlib.sha256(report).hexdigest()
    name = f"{DAY.isoformat()}-finance-{level}.md"
    _write(root, name, signature_text("finance", level, DAY, digest))  # type: ignore[arg-type]
    return name


@pytest.mark.parametrize(
    ("generated", "counts"),
    [
        ("2026-10-21T21:59:59+00:00", True),  # 23:59:59 in Paris, the day of the signature
        ("2026-10-21T22:00:00+00:00", False),  # midnight in Paris: the report is from the 22nd
        ("2026-10-22T08:00:00+02:00", False),
        ("2026-10-20T08:00:00+02:00", True),
    ],
)
def test_a_signature_before_the_report_it_cites_does_not_count(
    tmp_path: Path, generated: str, counts: bool
) -> None:
    name = _cite_dated(tmp_path, report_text("finance", "N3", DAY, generated=generated))
    signed = read_signatures(tmp_path, today=date(2026, 10, 23))
    if counts:
        assert (signed.highest("finance"), signed.problems) == ("N3", ())
    else:
        assert signed.problems == (
            f"{name} : datée du 21/10/2026, avant le rapport qu'elle cite (22/10/2026)",
        )


def test_an_oversized_report_is_set_aside_unread(tmp_path: Path) -> None:
    sign(tmp_path, "finance", "N3", DAY)
    report = report_text("finance", "N4", DAY)
    _cite_dated(tmp_path, report + b"x" * (MAX_REPORT_BYTES + 1 - len(report)), "N4")
    signed = read_signatures(tmp_path, today=DAY)
    assert signed.highest("finance") == "N3"
    oversized, uncited = signed.problems
    assert oversized == f"var/promotion/rapport-N4.md : plus de {MAX_REPORT_BYTES} octets, ignoré"
    assert "aucun rapport de promotion" in uncited


def test_a_report_at_the_bound_is_read(tmp_path: Path) -> None:
    report = report_text("finance", "N3", DAY)
    _cite_dated(tmp_path, report + b"x" * (MAX_REPORT_BYTES - len(report)))
    assert read_signatures(tmp_path, today=DAY).highest("finance") == "N3"


def test_the_signature_text_round_trips(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"rapport").hexdigest()
    path = _write(
        tmp_path, "2026-10-21-finance-N2.md", signature_text("finance", "N2", DAY, digest)
    )
    (signature,) = read_signatures(tmp_path).signatures
    assert (signature.path, signature.domain, signature.level, signature.date) == (
        path,
        "finance",
        "N2",
        DAY,
    )
    assert signature.promotion_report_sha256 == digest


@given(written=st.sampled_from(LEVELS), signed=st.lists(st.sampled_from(LEVELS[1:]), max_size=4))
def test_the_effective_level_is_never_above_either_bound(written: str, signed: list[str]) -> None:
    from core.governance.signatures import Signature

    signatures = tuple(
        Signature(Path(f"{i}.md"), "finance", level, DAY, "a" * 64)  # type: ignore[arg-type]
        for i, level in enumerate(signed)
    )
    result = effective_autonomy(
        _at(written), Path("inexistant"), signed=SignedLevels(signatures, ())
    )
    level = result.autonomy.domains["finance"].level
    highest = max(signed, key=LEVELS.index, default="N0")
    assert LEVELS.index(level) == min(LEVELS.index(written), LEVELS.index(highest))

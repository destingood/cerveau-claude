"""Signed promotions and the effective autonomy level (ADR-036, D6, D7).

A domain under ``promotion`` in ``autonomy.yaml`` (today ``finance``) runs at the lower of its
written level and the highest level Lucas signed in ``governance/approvals/``: editing
``autonomy.yaml`` alone promotes nothing, while lowering it there demotes at once. N0 needs no
signature; the other domains keep their written level, bounded by their ``max_level``.

A signature is ``governance/approvals/AAAA-MM-JJ-<domaine>-N<k>.md``, opening with a YAML header::

    ---
    domain: finance
    level: N3
    date: 2026-10-21
    promotion_report_sha256: "<64 chiffres hexadécimaux>"
    signed_by: lucas
    ---

It counts when its name, its header and its date agree and, from N3 on, when the promotion report
it cites exists under ``var/promotion/`` with that digest, opens with the header that
``cerveau promotion report`` writes (ADR-040) for the same domain and level, and concludes
``promotion_possible``: a signature cannot promote on a report that refuses the promotion.
A signature dated after today, or before the day (in Paris) its report was generated, does not
count either (B240). Files are read up to a bound, never whole (B233). Anything else is ignored
and reported, never repaired. This module reads; it never writes a signature (R3, D18).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from core.config.loader import LEVELS, AutonomyConfig, Level
from core.finance.model import local_date
from core.governance.demotion import floors, read_demotions

SIGNATURES_DIR = Path("governance") / "approvals"
PROMOTION_DIR = Path("var") / "promotion"
REPORT_FROM = "N3"  # from this level on, the cited promotion report must exist (D7)
REPORT_KIND: Final = "promotion"  # the header ``rapport`` of a promotion report
REPORT_PASSED: Final = "promotion_possible"  # the only ``statut`` a signature may rest on
MAX_BYTES = 64 * 1024  # a signature is a short header and a few lines
MAX_REPORT_BYTES = 1024 * 1024  # a promotion report is a few pages of Markdown (B233)
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z][a-z0-9_]*)-(N[0-4])\.md$")
_HEADER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


class _Header(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    domain: str
    level: Level
    date: date
    promotion_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed_by: Literal["lucas"]


class _ReportHeader(BaseModel):
    """What a signature needs from the report it cites; the other keys are for Lucas."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    rapport: Literal["promotion"]
    domain: str
    level: Level
    statut: str
    genere_le: Annotated[AwareDatetime, Field(strict=False)]  # quoted ISO text in the header


@dataclass(frozen=True)
class Signature:
    path: Path
    domain: str
    level: Level
    date: date
    promotion_report_sha256: str


@dataclass(frozen=True)
class SignedLevels:
    """The valid signatures, and why every other file was ignored."""

    signatures: tuple[Signature, ...]
    problems: tuple[str, ...]

    def highest(self, domain: str) -> Level:
        """The highest level signed for ``domain``; N0 without a signature."""
        levels = [s.level for s in self.signatures if s.domain == domain]
        return max(levels, key=LEVELS.index, default="N0")


Reports = Mapping[str, _ReportHeader | None]  # SHA-256 → the report's header, None if absent


def _report_header(raw: bytes) -> _ReportHeader | None:
    try:
        block = _HEADER.match(raw.decode("utf-8"))
        if block is None:
            return None
        return _ReportHeader.model_validate(yaml.safe_load(block.group(1)))
    except (UnicodeDecodeError, yaml.YAMLError, ValidationError):
        return None


def _head(path: Path, limit: int) -> bytes | None:
    """The bytes of ``path``, or None when it holds more than ``limit``: never read whole."""
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    return raw if len(raw) <= limit else None


def _reports(root: Path) -> tuple[Reports, tuple[str, ...]] | str:
    """Each regular file under ``var/promotion/`` by its SHA-256, with its header, and why each
    oversized one was set aside; or why they cannot be read."""
    folder = root / PROMOTION_DIR
    try:
        if not folder.is_dir():
            return {}, ()
        reports: dict[str, _ReportHeader | None] = {}
        oversized: list[str] = []
        for path in sorted(folder.iterdir()):
            if path.is_file() and not path.is_symlink():
                raw = _head(path, MAX_REPORT_BYTES)
                if raw is None:
                    where = f"{PROMOTION_DIR.as_posix()}/{path.name}"
                    oversized.append(f"{where} : plus de {MAX_REPORT_BYTES} octets, ignoré")
                else:
                    reports[hashlib.sha256(raw).hexdigest()] = _report_header(raw)
        return reports, tuple(oversized)
    except OSError as exc:
        return f"{PROMOTION_DIR.as_posix()} illisible ({type(exc).__name__})"


def _report_problem(header: _Header, cited: _ReportHeader | None) -> str | None:
    """Why the cited report cannot carry this signature, if it cannot."""
    if cited is None:
        return "le rapport cité n'a pas l'en-tête d'un rapport de promotion (ADR-040)"
    if (cited.domain, cited.level) != (header.domain, header.level):
        return f"le rapport cité porte sur {cited.domain} {cited.level}"
    if cited.statut != REPORT_PASSED:
        return f"le rapport cité conclut « {cited.statut} », pas « {REPORT_PASSED} »"
    generated = local_date(cited.genere_le)
    if header.date < generated:
        return (
            f"datée du {header.date:%d/%m/%Y}, avant le rapport qu'elle cite ({generated:%d/%m/%Y})"
        )
    return None


def _read(path: Path, reports: Reports | str, today: date) -> Signature | str:
    """The signature in ``path``, or why it does not count on ``today``."""
    name = path.name
    match = _NAME.match(name)
    if match is None:
        return f"{name} : nom attendu AAAA-MM-JJ-<domaine>-N<k>.md"
    if path.is_symlink() or not path.is_file():
        return f"{name} : pas un fichier ordinaire"
    try:
        raw = _head(path, MAX_BYTES)
    except OSError as exc:
        return f"{name} : illisible ({type(exc).__name__})"
    if raw is None:
        return f"{name} : plus de {MAX_BYTES} octets"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"{name} : UTF-8 attendu"
    block = _HEADER.match(text)
    if block is None:
        return f"{name} : en-tête YAML entre deux lignes « --- » attendu"
    try:
        header = _Header.model_validate(yaml.safe_load(block.group(1)))
    except (yaml.YAMLError, ValidationError) as exc:
        detail = "YAML illisible" if isinstance(exc, yaml.YAMLError) else _first(exc)
        return f"{name} : en-tête refusé ({detail})"
    named = (match.group(1), match.group(2), match.group(3))
    if named != (header.date.isoformat(), header.domain, header.level):
        return f"{name} : le nom et l'en-tête ne concordent pas"
    if header.date > today:
        return f"{name} : datée du {header.date:%d/%m/%Y}, après aujourd'hui ({today:%d/%m/%Y})"
    if LEVELS.index(header.level) >= LEVELS.index(REPORT_FROM):
        if isinstance(reports, str):
            return f"{name} : rapport de promotion invérifiable, {reports}"
        if header.promotion_report_sha256 not in reports:
            return (
                f"{name} : aucun rapport de promotion d'empreinte "
                f"{header.promotion_report_sha256[:12]}… sous {PROMOTION_DIR.as_posix()}"
            )
        problem = _report_problem(header, reports[header.promotion_report_sha256])
        if problem is not None:
            return f"{name} : {problem}"
    return Signature(
        path=path,
        domain=header.domain,
        level=header.level,
        date=header.date,
        promotion_report_sha256=header.promotion_report_sha256,
    )


def _first(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"]) or "en-tête"
    return f"{where} : {error['msg']}"


def today_in_paris() -> date:
    return local_date(datetime.now(UTC))


def read_signatures(root: Path, *, today: date | None = None) -> SignedLevels:
    """Every signature under ``governance/approvals/`` that counts on ``today`` (by default,
    today in Paris); an unreadable folder signs nothing."""
    today = today_in_paris() if today is None else today
    folder = root / SIGNATURES_DIR
    try:
        if not folder.is_dir():
            return SignedLevels((), ())
        paths = sorted(p for p in folder.iterdir() if p.suffix == ".md")
    except OSError as exc:
        return SignedLevels((), (f"{SIGNATURES_DIR.as_posix()} illisible ({type(exc).__name__})",))
    found = _reports(root)
    reports, set_aside = (found, ()) if isinstance(found, str) else found
    signatures: list[Signature] = []
    problems: list[str] = list(set_aside)
    for path in paths:
        read = _read(path, reports, today)
        if isinstance(read, str):
            problems.append(read)
        else:
            signatures.append(read)
    return SignedLevels(tuple(signatures), tuple(problems))


def promoted_domains(autonomy: AutonomyConfig) -> frozenset[str]:
    """The domains whose level only a signature raises: those under ``promotion``."""
    return frozenset(type(autonomy.promotion).model_fields)


@dataclass(frozen=True)
class EffectiveAutonomy:
    autonomy: AutonomyConfig
    capped: tuple[str, ...]  # "finance : N2 écrit, N0 signé"
    problems: tuple[str, ...]


def effective_autonomy(
    autonomy: AutonomyConfig,
    root: Path,
    *,
    signed: SignedLevels | None = None,
    today: date | None = None,
) -> EffectiveAutonomy:
    """``autonomy`` with each promoted domain at min(written level, highest level signed by
    ``today``), then every domain at or below its demotions (ADR-067)."""
    signed = read_signatures(root, today=today) if signed is None else signed
    domains = dict(autonomy.domains)
    capped: list[str] = []
    for domain in sorted(promoted_domains(autonomy) & set(domains)):
        spec = domains[domain]
        ceiling = signed.highest(domain)
        if LEVELS.index(spec.level) > LEVELS.index(ceiling):
            domains[domain] = spec.model_copy(update={"level": ceiling})
            capped.append(f"{domain} : {spec.level} écrit, {ceiling} signé")
    demotions = read_demotions(root)
    problems = signed.problems
    if isinstance(demotions, str):  # unreadable: every domain held at N0 (ADR-067)
        problems += (demotions,)
        lowest = dict.fromkeys(domains, LEVELS[0])
    else:
        lowest = floors(demotions)
    for domain, floor in sorted(lowest.items()):
        spec = domains.get(domain)
        if spec is not None and LEVELS.index(spec.level) > LEVELS.index(floor):
            domains[domain] = spec.model_copy(update={"level": floor})
            capped.append(f"{domain} : {spec.level}, rétrogradé à {floor}")
    return EffectiveAutonomy(
        autonomy=autonomy.model_copy(update={"domains": domains}),
        capped=tuple(capped),
        problems=problems,
    )


def effective_level(
    autonomy: AutonomyConfig, root: Path, domain: str, *, today: date | None = None
) -> Level:
    return effective_autonomy(autonomy, root, today=today).autonomy.domains[domain].level


def signature_text(
    domain: str, level: Level, day: date, report_sha256: str, *, body: Iterable[str] = ()
) -> str:
    """The text of a signature file, for Lucas to copy and for the tests (never written here)."""
    lines = [
        "---",
        f"domain: {domain}",
        f"level: {level}",
        f"date: {day.isoformat()}",
        f'promotion_report_sha256: "{report_sha256}"',  # quoted: all digits would read as a number
        "signed_by: lucas",
        "---",
        *body,
    ]
    return "\n".join(lines) + "\n"

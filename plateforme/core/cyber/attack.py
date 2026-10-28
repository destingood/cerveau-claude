"""Frozen index of MITRE ATT&CK Enterprise, built from one pinned STIX bundle (ADR-056).

`cerveau cyber attack-fetch`, run by Lucas, checks the downloaded bundle against its pin and builds
this index; the bundle itself is not kept. The ``cyber_attack`` plugin reads the index only: no
network. Texts of the bundle are external data (R5): one line, invisible characters and
citations removed, cut.

Field mapping: ATT&CK Data Model 3.3.0 (attack-data-model, main branch, read on 2026-10-27).
Whether it matches the v20.0 bundle is seen at the first fetch: the counts by kind are shown.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.net.text import clean_text, clip

ATTACK_DIR = Path("var") / "cyber" / "attack"
DOMAIN = "enterprise-attack"
INDEX_FORMAT = 1
MAX_INDEX_BYTES = 40_000_000
MAX_OBJECTS = 50_000
DESCRIPTION_MAX = 2000
NAME_MAX = 200
LIST_MAX = 2000
NOTICE = (
    "© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission "
    "of The MITRE Corporation."
)
TERMS_URL = "https://attack.mitre.org/resources/legal-and-branding/terms-of-use/"
FETCH_HINT = "lancer `cerveau cyber attack-fetch --version {version}` (Lucas)"

Kind = Literal[
    "tactic",
    "technique",
    "subtechnique",
    "mitigation",
    "detection_strategy",
    "group",
    "software",
    "campaign",
]
KINDS: tuple[Kind, ...] = get_args(Kind)
KIND_LABELS: dict[Kind, str] = {
    "tactic": "tactiques",
    "technique": "techniques",
    "subtechnique": "sous-techniques",
    "mitigation": "mesures d'atténuation",
    "detection_strategy": "stratégies de détection",
    "group": "groupes",
    "software": "logiciels",
    "campaign": "campagnes",
}
ID_PATTERNS: dict[Kind, str] = {
    "tactic": r"TA[0-9]{4}",
    "technique": r"T[0-9]{4}",
    "subtechnique": r"T[0-9]{4}\.[0-9]{3}",
    "mitigation": r"M[0-9]{4}",
    "detection_strategy": r"DET[0-9]{4}",
    "group": r"G[0-9]{4}",
    "software": r"S[0-9]{4}",
    "campaign": r"C[0-9]{4}",
}
ATTACK_ID = re.compile("|".join(ID_PATTERNS.values()))
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}")
SHA256 = re.compile(r"[0-9a-f]{64}")
_TYPES: dict[str, Kind] = {
    "x-mitre-tactic": "tactic",
    "course-of-action": "mitigation",
    "x-mitre-detection-strategy": "detection_strategy",
    "intrusion-set": "group",
    "malware": "software",
    "tool": "software",
    "campaign": "campaign",
}
_TECHNIQUES: tuple[Kind, ...] = ("technique", "subtechnique")
_SPEC = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}")
_SHORTNAME = re.compile(r"[a-z][a-z-]{0,39}")
_CITATION = re.compile(r"\(Citation:[^)]{0,300}\)")
_HIDDEN = frozenset({"Cs", "Co", "Cn"})  # clean_text drops Cf and turns Cc into spaces
_URL = r"^https://attack\.mitre\.org/[A-Za-z0-9/._-]{1,200}$"

AttackId = Annotated[str, Field(pattern=f"^(?:{ATTACK_ID.pattern})$")]
Label = Annotated[str, Field(min_length=1, max_length=NAME_MAX)]


class AttackError(Exception):
    """A bundle or an index this code refuses; the message quotes no text of the bundle (R5)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AttackObject(_Strict):
    id: AttackId
    kind: Kind
    name: Label
    description: Annotated[str, Field(max_length=DESCRIPTION_MAX)]
    description_truncated: bool
    url: Annotated[str, Field(pattern=_URL)] | None
    aliases: list[Label] = Field(max_length=LIST_MAX)
    platforms: list[Label] = Field(max_length=LIST_MAX)
    # Technique and sub-technique: tactics, parent, sub-techniques, mitigations, detections.
    tactics: list[AttackId] = Field(max_length=LIST_MAX)
    parent: AttackId | None
    subtechniques: list[AttackId] = Field(max_length=LIST_MAX)
    mitigations: list[AttackId] = Field(max_length=LIST_MAX)
    detection_strategies: list[AttackId] = Field(max_length=LIST_MAX)
    # Mitigated (mitigation), detected (detection strategy), used (group, software, campaign).
    techniques: list[AttackId] = Field(max_length=LIST_MAX)
    revoked: bool
    deprecated: bool
    revoked_by: AttackId | None
    modified: Annotated[str, Field(max_length=40)] | None
    version: Annotated[str, Field(max_length=20)] | None

    # Checked again on reading: a hand-made index cannot bring what the build removes (R5).
    @field_validator("name", "description")
    @classmethod
    def _one_clean_line(cls, value: str) -> str:
        if _plain(value) != value or _CITATION.search(value):
            raise ValueError("texte non nettoyé")
        return value

    @field_validator("aliases", "platforms")
    @classmethod
    def _clean_labels(cls, value: list[str]) -> list[str]:
        if any(_plain(item) != item for item in value):
            raise ValueError("texte non nettoyé")
        return value


class AttackIndex(_Strict):
    format: Literal[1]
    domain: Literal["enterprise-attack"]
    version: Annotated[str, Field(pattern=f"^{VERSION.pattern}$")]
    collection_version: Annotated[str, Field(pattern=f"^{VERSION.pattern}$")] | None
    spec_versions: list[Annotated[str, Field(max_length=20)]] = Field(max_length=20)
    bundle_sha256: Annotated[str, Field(pattern=f"^{SHA256.pattern}$")]
    bundle_bytes: Annotated[int, Field(gt=0)]
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_url: Annotated[
        str, Field(pattern=r"^https://raw\.githubusercontent\.com/mitre-attack/attack-stix-data/")
    ]
    built_at: Annotated[str, Field(max_length=40)]
    notice: Literal[
        "© 2026 The MITRE Corporation. This work is reproduced and distributed with the "
        "permission of The MITRE Corporation."
    ]
    objects: list[AttackObject] = Field(max_length=MAX_OBJECTS)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len({obj.id for obj in self.objects}) != len(self.objects):
            raise ValueError("identifiant ATT&CK en double")
        return self


@dataclass
class BuildReport:
    """What the build kept and left out, shown to Lucas after a fetch."""

    kinds: Counter[str] = field(default_factory=Counter)
    skipped: int = 0  # a known type without a valid ATT&CK identifier or name
    duplicates: int = 0  # a second object with the same identifier
    relationships: int = 0


@dataclass
class _Draft:
    stix_id: str
    kind: Kind
    id: str
    name: str
    description: str
    description_truncated: bool
    url: str | None
    aliases: list[str]
    platforms: list[str]
    shortnames: list[str]
    revoked: bool
    deprecated: bool
    modified: str | None
    version: str | None
    tactics: set[str] = field(default_factory=set)
    parent: str | None = None
    subtechniques: set[str] = field(default_factory=set)
    mitigations: set[str] = field(default_factory=set)
    detection_strategies: set[str] = field(default_factory=set)
    techniques: set[str] = field(default_factory=set)
    revoked_by: str | None = None

    @property
    def current(self) -> bool:
        return not (self.revoked or self.deprecated)


def _plain(raw: str) -> str:
    """One line of plain text, without hidden characters; applied twice, it changes nothing.

    Surrogates (an escape JSON allows), private-use and unassigned characters go first, so that
    ``clean_text`` then leaves single spaces only.
    """
    return clean_text("".join(c for c in raw if unicodedata.category(c) not in _HIDDEN))


def _uncited(raw: str) -> str:
    """``raw`` without citations, even one rebuilt by removing another (each pass shortens it)."""
    count = 1
    while count:
        raw, count = _CITATION.subn("", raw)
    return raw


def _short(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = clip(_plain(value), limit)[0]
    return text or None


def _labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found = (_short(item, NAME_MAX) for item in value[:LIST_MAX])
    return list(dict.fromkeys(item for item in found if item))


def _kind(obj: dict[str, Any]) -> Kind | None:
    kind = obj.get("type")
    if kind == "attack-pattern":
        return "subtechnique" if obj.get("x_mitre_is_subtechnique") is True else "technique"
    return _TYPES.get(kind) if isinstance(kind, str) else None


def _reference(obj: dict[str, Any], kind: Kind) -> tuple[str, str | None] | None:
    """The ATT&CK identifier and page of an object, if its identifier fits its kind."""
    refs = obj.get("external_references")
    for ref in refs if isinstance(refs, list) else []:
        if isinstance(ref, dict) and ref.get("source_name") == "mitre-attack":
            found = ref.get("external_id")
            if isinstance(found, str) and re.fullmatch(ID_PATTERNS[kind], found):
                url = ref.get("url")
                ok = isinstance(url, str) and re.fullmatch(_URL[1:-1], url)
                return found, url if ok else None
            return None
    return None


def _draft(obj: dict[str, Any], kind: Kind) -> _Draft | None:
    stix_id, found = obj.get("id"), _reference(obj, kind)
    name = _short(obj.get("name"), NAME_MAX)
    if not isinstance(stix_id, str) or found is None or name is None:
        return None
    raw = obj.get("description")
    description, cut = clip(_plain(_uncited(raw if isinstance(raw, str) else "")), DESCRIPTION_MAX)
    phases = obj.get("kill_chain_phases")
    shortnames = [
        phase["phase_name"]
        for phase in (phases if isinstance(phases, list) else [])
        if isinstance(phase, dict)
        and phase.get("kill_chain_name") == "mitre-attack"
        and isinstance(phase.get("phase_name"), str)
        and _SHORTNAME.fullmatch(phase["phase_name"])
    ]
    if kind == "tactic":
        shortname = obj.get("x_mitre_shortname")
        shortnames = (
            [shortname] if isinstance(shortname, str) and _SHORTNAME.fullmatch(shortname) else []
        )
    aliases = obj.get("x_mitre_aliases" if kind == "software" else "aliases")
    return _Draft(
        stix_id=stix_id,
        kind=kind,
        id=found[0],
        name=name,
        description=description,
        description_truncated=cut,
        url=found[1],
        aliases=[a for a in _labels(aliases) if a != name],
        platforms=_labels(obj.get("x_mitre_platforms")),
        shortnames=shortnames,
        revoked=obj.get("revoked") is True,
        deprecated=obj.get("x_mitre_deprecated") is True,
        modified=_short(obj.get("modified"), 40),
        version=_short(obj.get("x_mitre_version"), 20),
    )


def _keep(first: _Draft, second: _Draft) -> _Draft:
    """Of two objects with one identifier: the current one, else the latest modified (ISO 8601
    timestamps compare as text), else the smaller STIX identifier."""
    if first.current != second.current:
        return first if first.current else second
    if (first.modified or "") != (second.modified or ""):
        return first if (first.modified or "") > (second.modified or "") else second
    return min(first, second, key=lambda draft: draft.stix_id)


def _family(kind: Kind) -> str:
    return "technique" if kind in _TECHNIQUES else kind


def _link(drafts: dict[str, _Draft], relation: dict[str, Any]) -> bool:
    if relation.get("revoked") is True or relation.get("x_mitre_deprecated") is True:
        return False
    source = drafts.get(str(relation.get("source_ref")))
    target = drafts.get(str(relation.get("target_ref")))
    if source is None or target is None:
        return False
    kind = relation.get("relationship_type")
    if kind == "revoked-by":  # a technique may be revoked by a sub-technique (T1086, T1059.001)
        if _family(source.kind) != _family(target.kind):
            return False
        source.revoked_by = target.id
        return True
    if not (source.current and target.current):  # a link to a retired object is not shown
        return False
    techniques = _TECHNIQUES
    if kind == "subtechnique-of" and (source.kind, target.kind) == ("subtechnique", "technique"):
        source.parent = target.id
        target.subtechniques.add(source.id)
    elif kind == "mitigates" and source.kind == "mitigation" and target.kind in techniques:
        source.techniques.add(target.id)
        target.mitigations.add(source.id)
    elif kind == "detects" and source.kind == "detection_strategy" and target.kind in techniques:
        source.techniques.add(target.id)
        target.detection_strategies.add(source.id)
    elif (
        kind == "uses"
        and source.kind in ("group", "software", "campaign")
        and (target.kind in techniques)
    ):
        source.techniques.add(target.id)
    else:
        return False
    return True


def _version_of(objects: list[Any]) -> tuple[str | None, list[str]]:
    collection, specs = None, set()
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        spec = obj.get("x_mitre_attack_spec_version")
        if isinstance(spec, str) and _SPEC.fullmatch(spec):
            specs.add(spec)
        if obj.get("type") == "x-mitre-collection":
            found = obj.get("x_mitre_version")
            if isinstance(found, str) and VERSION.fullmatch(found):
                collection = found
    return collection, sorted(specs)[:20]


def build_index(
    body: bytes, *, version: str, commit: str, source_url: str, sha256: str, built_at: str
) -> tuple[AttackIndex, BuildReport]:
    """The index of a STIX 2.1 bundle of ATT&CK Enterprise ``version``; a bundle of another
    version, or without any technique, is refused."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise AttackError("bundle ATT&CK illisible (JSON invalide)") from None
    objects = data.get("objects") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("type") != "bundle" or not isinstance(objects, list):
        raise AttackError("bundle ATT&CK illisible (objet « bundle » attendu)")
    collection, specs = _version_of(objects)
    if collection is not None and collection != version:
        raise AttackError(f"bundle de la version {collection} et non {version} : refusé")
    report = BuildReport()
    by_id: dict[str, _Draft] = {}
    for obj in objects:
        kind = _kind(obj) if isinstance(obj, dict) else None
        if kind is None:
            continue
        draft = _draft(obj, kind)
        if draft is None:
            report.skipped += 1
            continue
        if (known := by_id.get(draft.id)) is not None:
            report.duplicates += 1
            draft = _keep(known, draft)
        by_id[draft.id] = draft
    kept = {draft.stix_id: draft for draft in by_id.values()}
    tactics = {  # a current tactic wins over a retired one with the same short name
        d.shortnames[0]: d.id
        for d in sorted(kept.values(), key=lambda d: d.current)
        if d.kind == "tactic" and d.shortnames
    }
    for draft in kept.values():
        if draft.kind in _TECHNIQUES:
            draft.tactics = {tactics[name] for name in draft.shortnames if name in tactics}
    for obj in objects:
        if isinstance(obj, dict) and obj.get("type") == "relationship":
            report.relationships += _link(kept, obj)
    if not any(d.kind == "technique" for d in kept.values()):
        raise AttackError("bundle ATT&CK sans technique : refusé")
    report.kinds.update(d.kind for d in kept.values())
    rank = {kind: n for n, kind in enumerate(KINDS)}
    try:
        index = AttackIndex(
            format=INDEX_FORMAT,
            domain=DOMAIN,
            version=version,
            collection_version=collection,
            spec_versions=specs,
            bundle_sha256=sha256,
            bundle_bytes=len(body),
            commit=commit,
            source_url=source_url,
            built_at=built_at,
            notice=NOTICE,
            objects=[_object(d) for d in sorted(kept.values(), key=lambda d: (rank[d.kind], d.id))],
        )
    except ValidationError:
        raise AttackError("bundle ATT&CK hors des bornes de l'index : refusé") from None
    return index, report


def _object(draft: _Draft) -> AttackObject:
    return AttackObject(
        id=draft.id,
        kind=draft.kind,
        name=draft.name,
        description=draft.description,
        description_truncated=draft.description_truncated,
        url=draft.url,
        aliases=draft.aliases,
        platforms=draft.platforms,
        tactics=sorted(draft.tactics),
        parent=draft.parent,
        subtechniques=sorted(draft.subtechniques),
        mitigations=sorted(draft.mitigations),
        detection_strategies=sorted(draft.detection_strategies),
        techniques=sorted(draft.techniques),
        revoked=draft.revoked,
        deprecated=draft.deprecated,
        revoked_by=draft.revoked_by,
        modified=draft.modified,
        version=draft.version,
    )


def index_path(root: Path, version: str) -> Path:
    return root / ATTACK_DIR / f"{DOMAIN}-{version}.index.json"


def write_index(path: Path, index: AttackIndex) -> str:
    """Write the index whole or not at all: a reader never sees half a file.

    Returns the SHA-256 of the file written, for the journal (R11).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = index.model_dump_json().encode("utf-8")
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return hashlib.sha256(data).hexdigest()


def read_index(path: Path, version: str) -> AttackIndex:
    """The index of ``version``, checked field by field; an altered file is refused."""
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_INDEX_BYTES + 1)
    except FileNotFoundError:
        raise AttackError(
            f"index ATT&CK {version} absent : {FETCH_HINT.format(version=version)}"
        ) from None
    except OSError:
        raise AttackError("index ATT&CK illisible") from None
    altered = AttackError(
        f"index ATT&CK illisible ou altéré : {FETCH_HINT.format(version=version)}"
    )
    if len(data) > MAX_INDEX_BYTES:
        raise altered
    try:
        return AttackIndex.model_validate_json(data)
    except (ValidationError, ValueError):
        raise altered from None

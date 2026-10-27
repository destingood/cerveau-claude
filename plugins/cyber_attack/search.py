"""Search of the frozen ATT&CK index: one identifier, or English keywords (ADR-056).

Deterministic and without any model: a keyword matches when it is a substring of the casefolded
name, aliases or description. The order of the results is fixed and returned with them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property

from core.cyber.attack import (
    ATTACK_ID,
    DESCRIPTION_MAX,
    KINDS,
    TERMS_URL,
    AttackIndex,
    AttackObject,
)
from core.net.text import clip
from plugins.cyber_attack.models import (
    MAX_RESULTS,
    AttackItem,
    AttackLookup,
    AttackSource,
    Ref,
    Status,
)

QUERY_MAX = 200
MAX_TOKENS = 8
TOKEN_MIN = 2
DESCRIPTION_KEYWORDS = 700  # per result of a keyword search; an identifier gets the whole index
LIST_CAP_ID = 100
LIST_CAP_KEYWORDS = 20
ORDER = (
    "objets en vigueur d'abord ; puis tous les mots dans le nom ou un alias avant les mots "
    "trouvés aussi dans la description ; puis le type (tactique, technique, sous-technique, "
    "mesure, stratégie de détection, groupe, logiciel, campagne) ; puis l'identifiant"
)
ORDER_ID = "l'objet demandé, puis son remplaçant s'il est révoqué"
# Control, invisible format, lone surrogate, private use and unassigned characters.
_REFUSED = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_WORD = re.compile(r"\w+")
_RANK = {kind: n for n, kind in enumerate(KINDS)}


class QueryError(Exception):
    """A query this tool refuses; the message never quotes it."""


def normalised(raw: str) -> str:
    """The query on one line, or ``QueryError`` if empty, too long or with a hidden character."""
    if any(unicodedata.category(char) in _REFUSED for char in raw.replace(" ", "")):
        raise QueryError("query : caractère de contrôle, invisible ou non attribué refusé")
    text = " ".join(raw.split())
    if not 1 <= len(text) <= QUERY_MAX:
        raise QueryError(f"query : 1 à {QUERY_MAX} caractères")
    return text


def tokens(text: str) -> list[str]:
    found = list(dict.fromkeys(w for w in _WORD.findall(text.casefold()) if len(w) >= TOKEN_MIN))
    if not found:
        raise QueryError(f"query : au moins un mot de {TOKEN_MIN} caractères")
    if len(found) > MAX_TOKENS:
        raise QueryError(f"query : {MAX_TOKENS} mots au plus")
    return found


def status(obj: AttackObject) -> Status:
    if obj.revoked:
        return "révoqué"
    return "obsolète" if obj.deprecated else "en vigueur"


@dataclass(frozen=True)
class Catalogue:
    """An index and what a search needs from it, built once per index read."""

    index: AttackIndex

    @cached_property
    def by_id(self) -> dict[str, AttackObject]:
        return {obj.id: obj for obj in self.index.objects}

    @cached_property
    def haystacks(self) -> list[tuple[AttackObject, str, str]]:
        return [
            (obj, " ".join([obj.name, *obj.aliases]).casefold(), obj.description.casefold())
            for obj in self.index.objects
        ]

    @cached_property
    def source(self) -> AttackSource:
        return AttackSource(
            name="MITRE ATT&CK Enterprise",
            version=self.index.version,
            commit=self.index.commit,
            bundle_sha256=self.index.bundle_sha256,
            built_at=self.index.built_at,
            notice=self.index.notice,
            terms_url=TERMS_URL,
        )

    def refs(self, ids: list[str], cap: int) -> tuple[list[Ref], bool]:
        found = [Ref(id=i, name=self.by_id[i].name) for i in ids if i in self.by_id]
        return found[:cap], len(found) > cap

    def ref(self, identifier: str | None) -> Ref | None:
        obj = self.by_id.get(identifier) if identifier else None
        return Ref(id=obj.id, name=obj.name) if obj else None

    def item(self, obj: AttackObject, *, description_max: int, cap: int) -> AttackItem:
        lists = {
            name: self.refs(getattr(obj, name), cap)
            for name in ("tactics", "subtechniques", "mitigations", "detection_strategies")
        }
        techniques = self.refs(obj.techniques, cap)
        description, cut = clip(obj.description, description_max)
        return AttackItem(
            id=obj.id,
            kind=obj.kind,
            name=obj.name,
            status=status(obj),
            url=obj.url,
            description=description,
            description_truncated=cut or obj.description_truncated,
            aliases=obj.aliases[:cap],
            platforms=obj.platforms[:cap],
            tactics=lists["tactics"][0],
            parent=self.ref(obj.parent),
            subtechniques=lists["subtechniques"][0],
            mitigations=lists["mitigations"][0],
            detection_strategies=lists["detection_strategies"][0],
            techniques=techniques[0],
            lists_truncated=any(t for _, t in lists.values())
            or techniques[1]
            or len(obj.aliases) > cap
            or len(obj.platforms) > cap,
            revoked_by=self.ref(obj.revoked_by),
            modified=obj.modified,
            version=obj.version,
        )

    def lookup(self, raw: str, max_results: int = 5) -> AttackLookup:
        query = normalised(raw)
        if not 1 <= max_results <= MAX_RESULTS:
            raise QueryError(f"max_results : 1 à {MAX_RESULTS}")
        if ATTACK_ID.fullmatch(query.upper()):
            return self._by_identifier(query)
        words = tokens(query)
        found: list[tuple[tuple[bool, int, int, str], AttackObject]] = []
        for obj, names, description in self.haystacks:
            if all(word in names for word in words):
                tier = 0
            elif all(word in names or word in description for word in words):
                tier = 1
            else:
                continue
            current = not (obj.revoked or obj.deprecated)
            found.append(((not current, tier, _RANK[obj.kind], obj.id), obj))
        found.sort(key=lambda pair: pair[0])
        return AttackLookup(
            query=query,
            match="mots-clés",
            results=[
                self.item(obj, description_max=DESCRIPTION_KEYWORDS, cap=LIST_CAP_KEYWORDS)
                for _, obj in found[:max_results]
            ],
            total_matches=len(found),
            more_available=len(found) > max_results,
            order=ORDER,
            source=self.source,
        )

    def _by_identifier(self, query: str) -> AttackLookup:
        identifier = query.upper()
        objects = [self.by_id[identifier]] if identifier in self.by_id else []
        if objects and (replacement := self.by_id.get(objects[0].revoked_by or "")) is not None:
            objects.append(replacement)
        return AttackLookup(
            query=identifier,
            match="identifiant",
            results=[
                self.item(obj, description_max=DESCRIPTION_MAX, cap=LIST_CAP_ID) for obj in objects
            ],
            total_matches=len(objects),
            more_available=False,
            order=ORDER_ID,
            source=self.source,
        )

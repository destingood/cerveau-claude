"""Synthetic ATT&CK Enterprise STIX bundle for the offline tests of the Cyber pack (ADR-056).

Identifiers, names and links imitate the shape of ATT&CK; descriptions are made up for the
tests. Nothing here is a fact about ATT&CK: the real bundle is only read by
`cerveau cyber attack-fetch`, which Lucas runs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from core.cyber.attack import AttackIndex, BuildReport, build_index

VERSION = "20.0"
COMMIT = "20664a889568dce884a1dac0ec7b12ae3a199f51"
SOURCE_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
    f"{COMMIT}/enterprise-attack/enterprise-attack-{VERSION}.json"
)
BUILT_AT = "2026-10-27T09:30:00+00:00"
SPEC = "3.3.0"
MODIFIED = "2025-04-15T19:58:03.000Z"
_PAGES = {
    "x-mitre-tactic": "tactics",
    "attack-pattern": "techniques",
    "course-of-action": "mitigations",
    "x-mitre-detection-strategy": "detectionstrategies",
    "intrusion-set": "groups",
    "malware": "software",
    "tool": "software",
    "campaign": "campaigns",
}


def stix_id(stix_type: str, key: str) -> str:
    return f"{stix_type}--{uuid.uuid5(uuid.NAMESPACE_URL, f'{stix_type}/{key}')}"


def obj(stix_type: str, attack_id: str, name: str, **extra: Any) -> dict[str, Any]:
    page = attack_id.replace(".", "/")
    found: dict[str, Any] = {
        "type": stix_type,
        "spec_version": "2.1",
        "id": stix_id(stix_type, attack_id),
        "name": name,
        "description": f"Synthetic description of {name}.",
        "external_references": [
            {
                "source_name": "mitre-attack",
                "external_id": attack_id,
                "url": f"https://attack.mitre.org/{_PAGES[stix_type]}/{page}",
            },
            {"source_name": "Example 2024", "description": "Synthetic reference."},
        ],
        "modified": MODIFIED,
        "x_mitre_version": "1.0",
        "x_mitre_attack_spec_version": SPEC,
    }
    found.update(extra)
    return found


def tactic(attack_id: str, name: str, shortname: str, **extra: Any) -> dict[str, Any]:
    return obj("x-mitre-tactic", attack_id, name, x_mitre_shortname=shortname, **extra)


def technique(attack_id: str, name: str, *tactics: str, **extra: Any) -> dict[str, Any]:
    phases = [{"kill_chain_name": "mitre-attack", "phase_name": t} for t in tactics]
    return obj(
        "attack-pattern",
        attack_id,
        name,
        kill_chain_phases=phases,
        x_mitre_is_subtechnique="." in attack_id,
        x_mitre_platforms=["Windows", "Linux", "macOS"],
        **extra,
    )


def relation(kind: str, source: dict[str, Any], target: dict[str, Any], **extra: Any) -> dict:
    found = {
        "type": "relationship",
        "id": stix_id("relationship", f"{kind}/{source['id']}/{target['id']}"),
        "relationship_type": kind,
        "source_ref": source["id"],
        "target_ref": target["id"],
    }
    found.update(extra)
    return found


def collection(version: str = VERSION) -> dict[str, Any]:
    return {
        "type": "x-mitre-collection",
        "id": stix_id("x-mitre-collection", "enterprise"),
        "name": "Enterprise ATT&CK",
        "x_mitre_version": version,
        "x_mitre_attack_spec_version": SPEC,
    }


EXECUTION = tactic("TA0002", "Execution", "execution")
CREDENTIALS = tactic("TA0006", "Credential Access", "credential-access")
EXFILTRATION = tactic("TA0010", "Exfiltration", "exfiltration")
INTERPRETER = technique("T1059", "Command and Scripting Interpreter", "execution")
POWERSHELL = technique(
    "T1059.001",
    "PowerShell",
    "execution",
    description="Adversaries may abuse PowerShell commands and scripts for execution. "
    "(Citation: Example PowerShell 2024)",
)
OLD_POWERSHELL = technique("T1086", "PowerShell", "execution", revoked=True)
SCRIPTING = technique("T1064", "Scripting", "execution", x_mitre_deprecated=True)
DUMPING = technique("T1003", "OS Credential Dumping", "credential-access")
LSASS = technique("T1003.001", "LSASS Memory", "credential-access")
OVER_C2 = technique("T1041", "Exfiltration Over C2 Channel", "exfiltration")
PREVENTION = obj("course-of-action", "M1038", "Execution Prevention")
DISABLE = obj("course-of-action", "M1042", "Disable or Remove Feature or Program")
PROTECTION = obj("course-of-action", "M1043", "Credential Access Protection")
DETECT = obj("x-mitre-detection-strategy", "DET0001", "Detect PowerShell abuse")
APT = obj(
    "intrusion-set",
    "G0007",
    "APT28",
    aliases=["APT28", "Sofacy", "Fancy Bear"],
    description="Synthetic group that runs PowerShell scripts.",
)
TOOL = obj("tool", "S0002", "Mimikatz", x_mitre_aliases=["Mimikatz"], aliases=["Ignored"])
CAMPAIGN = obj("campaign", "C0024", "Synthetic Campaign", aliases=["Synthetic Campaign"])

SAMPLE: list[dict[str, Any]] = [
    collection(),
    EXECUTION,
    CREDENTIALS,
    EXFILTRATION,
    INTERPRETER,
    POWERSHELL,
    OLD_POWERSHELL,
    SCRIPTING,
    DUMPING,
    LSASS,
    OVER_C2,
    PREVENTION,
    DISABLE,
    PROTECTION,
    DETECT,
    APT,
    TOOL,
    CAMPAIGN,
    {"type": "identity", "id": stix_id("identity", "mitre"), "name": "The MITRE Corporation"},
    relation("subtechnique-of", POWERSHELL, INTERPRETER),
    relation("subtechnique-of", LSASS, DUMPING),
    relation("revoked-by", OLD_POWERSHELL, POWERSHELL),
    relation("mitigates", PREVENTION, INTERPRETER),
    relation("mitigates", DISABLE, POWERSHELL),
    relation("mitigates", PROTECTION, LSASS),
    relation("detects", DETECT, POWERSHELL),
    relation("uses", APT, POWERSHELL),
    relation("uses", APT, LSASS),
    relation("uses", APT, TOOL),  # software used by a group: not a technique, not kept
    relation("uses", TOOL, LSASS),
    relation("uses", CAMPAIGN, INTERPRETER),
    relation("mitigates", PREVENTION, SCRIPTING),  # retired technique: not shown
]
SAMPLE_RELATIONSHIPS = 11


def bundle(objects: list[dict[str, Any]] | None = None) -> bytes:
    found = SAMPLE if objects is None else objects
    data = {"type": "bundle", "id": stix_id("bundle", "test"), "objects": found}
    return json.dumps(data).encode("utf-8")


def sha256_of(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def build(
    objects: list[dict[str, Any]] | None = None,
    *,
    version: str = VERSION,
    built_at: str = BUILT_AT,
) -> tuple[AttackIndex, BuildReport]:
    body = bundle(objects)
    return build_index(
        body,
        version=version,
        commit=COMMIT,
        source_url=SOURCE_URL,
        sha256=sha256_of(body),
        built_at=built_at,
    )

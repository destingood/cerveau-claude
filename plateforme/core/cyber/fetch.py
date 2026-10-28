"""Download of one pinned ATT&CK STIX bundle, for `cerveau cyber attack-fetch` only (ADR-056).

Lucas runs the command; nothing else downloads the bundle (G5). Each version has a pin read on
GitHub on 2026-10-27: the commit of its release tag, the size of the file and its git blob
SHA-1. A body must match both before anything is built from it. Its SHA-256 is then written in
``config/data_sources.yaml`` once (trust on first use) and checked at every later fetch and by
the plugin at every read of the index.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from core.config.loader import ConfigError, load_config
from core.cyber.attack import AttackError
from core.net import guard
from core.net.body import read_body

BUNDLE_HOST = "raw.githubusercontent.com"
REPOSITORY = "mitre-attack/attack-stix-data"
MAX_BUNDLE_BYTES = 80_000_000
TIMEOUT_S = 600.0  # the whole download: 55 Mo, about 9.5 Mo once compressed
READ_TIMEOUT_S = 60.0  # between two chunks
USER_AGENT = "CERVEAU/0.2 (assistant personnel, lecture seule)"
SOURCES_FILE = "data_sources.yaml"
_SHA256 = re.compile(r"[0-9a-f]{64}")
# The single line `attack-fetch` may change: the digest of the `attack` source, still a marker.
_DIGEST_LINE = re.compile(
    rb"^(    sha256: )(A_VERIFIER|A_DEFINIR)([ \t]*(?:#[^\r\n]*)?)(\r?\n)", re.M
)


@dataclass(frozen=True)
class Pin:
    commit: str  # commit of the release tag
    size: int  # bytes of the file
    blob_sha1: str  # git blob name of the file in that commit


# Tag v20.0 of mitre-attack/attack-stix-data (2026-10-13), read on GitHub on 2026-10-27.
PINS: dict[str, Pin] = {
    "20.0": Pin(
        commit="20664a889568dce884a1dac0ec7b12ae3a199f51",
        size=55_271_014,
        blob_sha1="b39ce73c609d0f028841546e042ec16ffd7fe63f",
    ),
}


def bundle_url(version: str, pin: Pin) -> str:
    return (
        f"https://{BUNDLE_HOST}/{REPOSITORY}/{pin.commit}/enterprise-attack/"
        f"enterprise-attack-{version}.json"
    )


def git_blob_sha1(body: bytes) -> str:
    """Name git gives a file: SHA-1 of ``blob <size>\\0`` and the content.

    SHA-1 collisions need both files made by the attacker; this file was made by MITRE, so
    another file with the same name needs a second preimage, unknown for SHA-1 (ADR-056).
    """
    header = b"blob %d\x00" % len(body)
    return hashlib.sha1(header + body).hexdigest()  # noqa: S324 - second preimage, see above


def verify(body: bytes, pin: Pin) -> str:
    """SHA-256 of a body that matches its pin; any other body is refused."""
    if len(body) != pin.size:
        raise AttackError(f"bundle refusé : {len(body)} octets au lieu de {pin.size}")
    if git_blob_sha1(body) != pin.blob_sha1:
        raise AttackError("bundle refusé : empreinte différente de celle du commit épinglé")
    return hashlib.sha256(body).hexdigest()


async def download(
    version: str,
    pin: Pin,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: guard.Resolver = guard.system_resolver,
    interrupt: Callable[[], None] | None = None,
) -> bytes:
    """Body of the pinned bundle, read on a public address of GitHub only (ADR-006).

    ``interrupt`` runs before each chunk; it raises to stop the download (kill switch, R4).
    """
    try:
        target = guard.check_url(bundle_url(version, pin))
        if target.scheme != "https" or target.host != BUNDLE_HOST:
            raise AttackError("téléchargement : hôte non autorisé")
        async with asyncio.timeout(TIMEOUT_S):
            address = await guard.pin(target, resolver)
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=READ_TIMEOUT_S,
                limits=httpx.Limits(max_keepalive_connections=0),
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            ) as client:
                request = guard.pinned_request(client, target, address, {})
                response = await client.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        raise AttackError(f"téléchargement : réponse HTTP {response.status_code}")
                    # The pinned size bounds the read: a larger body stops at once.
                    limit = min(MAX_BUNDLE_BYTES, pin.size)
                    return await read_body(response, limit, cut=False, interrupt=interrupt)
                finally:
                    await response.aclose()
    except (TimeoutError, httpx.TimeoutException):
        raise AttackError("téléchargement : délai dépassé") from None
    except guard.FetchError as exc:
        raise AttackError(f"téléchargement : {exc}") from None
    except httpx.HTTPError:
        raise AttackError("téléchargement : connexion impossible") from None


def _attack_block(text: bytes) -> tuple[int, int]:
    """Start and end of the ``attack`` entry under ``sources``."""
    start = re.search(rb"^  attack:[ \t]*\r?\n", text, re.M)
    if start is None:
        raise AttackError("config : source « attack » introuvable")
    end = re.search(rb"^(?!    |\r?\n)", text[start.end() :], re.M)
    return start.end(), start.end() + (end.start() if end else len(text) - start.end())


def record_sha256(config_dir: Path, sha256: str) -> None:
    """Write ``sha256`` in place of the marker of the ``attack`` source, and nothing else.

    The file is changed on one line, written whole, then loaded again; if the configuration
    does not read the same digest back, the original text is restored.
    """
    if not _SHA256.fullmatch(sha256):
        raise AttackError("empreinte SHA-256 invalide")
    path = config_dir / SOURCES_FILE
    original = path.read_bytes()
    begin, end = _attack_block(original)
    lines = list(_DIGEST_LINE.finditer(original, begin, end))
    if len(lines) != 1:
        raise AttackError("config : ligne « sha256: A_VERIFIER » de la source attack introuvable")
    line = lines[0]
    changed = (
        original[: line.start()]
        + line.group(1)
        + sha256.encode("ascii")
        + line.group(3)
        + line.group(4)
        + original[line.end() :]
    )
    _replace(path, changed)
    try:
        written = load_config(config_dir).data_sources.sources["attack"].sha256
    except (ConfigError, KeyError):
        written = None
    if written != sha256:
        _replace(path, original)
        raise AttackError("config : empreinte non relue après écriture, fichier restauré")


def _replace(path: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".yaml")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise

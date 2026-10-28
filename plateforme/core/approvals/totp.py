"""Time-based one-time codes (RFC 6238 over RFC 4226), standard library only (ADR-035).

HMAC-SHA1, 6 digits, a 30 s step from the Unix epoch (T0 = 0): what authenticator applications
expect by default. A code is accepted one step late or early (RFC 6238 §5.2 recommends at most one
step of delay; one step ahead covers a phone clock that runs fast), every candidate is compared in
constant time, and a step at or below the last accepted one is refused: a code never serves twice
(RFC 6238 §5.2).

The secret is base32, as the ``otpauth://`` URI carries it, and lives in Lucas's environment
variable ``CERVEAU_TOTP_SECRET``; it never reaches the repository, a log or the journal (R6). A
missing or malformed secret refuses every code.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
WINDOW_STEPS = 1
SECRET_ENV = "CERVEAU_TOTP_SECRET"  # noqa: S105 - the variable's name, not a secret
SECRET_BYTES = 20  # 160 bits, RFC 4226 §4 R6: the length it recommends for HMAC-SHA1
ISSUER = "CERVEAU"
Algorithm = Literal["sha1", "sha256", "sha512"]
_BASE32 = re.compile(r"^[A-Z2-7]+=*$")


class TotpError(ValueError):
    """A secret that cannot be used: absent, not base32 or too short."""


def hotp(key: bytes, counter: int, *, digits: int = DIGITS, algorithm: Algorithm = "sha1") -> str:
    """RFC 4226 §5.3: the dynamically truncated HMAC of the 8-byte big-endian counter."""
    if not 0 <= counter < 2**64:
        raise ValueError("compteur HOTP hors de [0, 2^64)")
    if not 6 <= digits <= 8:
        raise ValueError("un code a de 6 à 8 chiffres")
    mac = hmac.new(key, counter.to_bytes(8, "big"), getattr(hashlib, algorithm)).digest()
    offset = mac[-1] & 0x0F
    value = int.from_bytes(mac[offset : offset + 4], "big") & 0x7FFF_FFFF
    return str(value % 10**digits).zfill(digits)


def time_step(when: datetime) -> int:
    """RFC 6238 §4.2: whole steps of ``STEP_SECONDS`` since the Unix epoch."""
    if when.tzinfo is None:
        raise ValueError("une heure sans fuseau ne date pas un code")
    return int(when.timestamp()) // STEP_SECONDS


def totp(key: bytes, when: datetime, *, digits: int = DIGITS, algorithm: Algorithm = "sha1") -> str:
    return hotp(key, time_step(when), digits=digits, algorithm=algorithm)


def decode_secret(text: str) -> bytes:
    """The key behind a base32 secret, spaces and case ignored, padding optional."""
    compact = text.replace(" ", "").upper()
    padded = compact + "=" * (-len(compact) % 8)
    if not _BASE32.match(padded):
        raise TotpError("secret TOTP : base32 attendu")
    try:
        key = base64.b32decode(padded)
    except binascii.Error as exc:
        raise TotpError("secret TOTP : base32 invalide") from exc
    if len(key) < SECRET_BYTES:
        raise TotpError(f"secret TOTP : au moins {SECRET_BYTES} octets")
    return key


def key_from_environment(environ: Mapping[str, str]) -> bytes | None:
    """The key from ``CERVEAU_TOTP_SECRET``, or None when it is absent or unusable."""
    text = environ.get(SECRET_ENV)
    if not text:
        return None
    try:
        return decode_secret(text)
    except TotpError:
        return None


def generate_secret() -> str:
    """A fresh 160-bit secret in base32, without padding, as authenticator applications take it."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def provisioning_uri(secret: str, *, account: str = "lucas") -> str:
    """The ``otpauth://`` URI an authenticator application scans (Key Uri Format)."""
    decode_secret(secret)
    label = quote(f"{ISSUER}:{account}")
    query = urlencode(
        {
            "secret": secret,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def verify(key: bytes | None, code: str, when: datetime, *, last_step: int | None) -> int | None:
    """The step ``code`` belongs to, within one step of ``when`` and above ``last_step``, or None.

    Every candidate step is computed and compared, whatever matches first, so that the time
    taken does not tell which step, if any, matched."""
    current = time_step(when)
    well_formed = len(code) == DIGITS and code.isascii() and code.isdigit()
    candidate = code if well_formed else "0" * DIGITS
    accepted: int | None = None
    for step in range(max(current - WINDOW_STEPS, 0), current + WINDOW_STEPS + 1):
        expected = hotp(key or b"\0" * SECRET_BYTES, step)
        fresh = last_step is None or step > last_step
        if hmac.compare_digest(expected, candidate) and fresh and accepted is None:
            accepted = step
    if key is None or not well_formed:
        return None
    return accepted

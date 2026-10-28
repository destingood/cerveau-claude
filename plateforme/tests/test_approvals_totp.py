from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.approvals.totp import (
    DIGITS,
    SECRET_ENV,
    STEP_SECONDS,
    TotpError,
    decode_secret,
    generate_secret,
    hotp,
    key_from_environment,
    provisioning_uri,
    time_step,
    totp,
    verify,
)

# RFC 6238, appendix B: the seeds are ASCII digits repeated to the length of each hash.
SEEDS = {
    "sha1": b"12345678901234567890",
    "sha256": b"12345678901234567890123456789012",
    "sha512": b"1234567890123456789012345678901234567890123456789012345678901234",
}
RFC6238 = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]
# RFC 4226, appendix D: HOTP of the SHA-1 seed for the counters 0 to 9.
RFC4226 = [
    "755224",
    "287082",
    "359152",
    "969429",
    "338314",
    "254676",
    "287922",
    "162583",
    "399871",
    "520489",
]
KEY = SEEDS["sha1"]
NOW = datetime(2026, 10, 21, 12, 0, 15, tzinfo=UTC)


@pytest.mark.parametrize(("seconds", "sha1", "sha256", "sha512"), RFC6238)
def test_rfc6238_appendix_b_vectors(seconds: int, sha1: str, sha256: str, sha512: str) -> None:
    when = datetime.fromtimestamp(seconds, UTC)
    assert totp(SEEDS["sha1"], when, digits=8, algorithm="sha1") == sha1
    assert totp(SEEDS["sha256"], when, digits=8, algorithm="sha256") == sha256
    assert totp(SEEDS["sha512"], when, digits=8, algorithm="sha512") == sha512


@pytest.mark.parametrize(("counter", "expected"), list(enumerate(RFC4226)))
def test_rfc4226_appendix_d_vectors(counter: int, expected: str) -> None:
    assert hotp(KEY, counter) == expected


def test_a_code_has_six_digits_by_default_and_keeps_its_leading_zeros() -> None:
    assert DIGITS == 6
    assert totp(KEY, datetime.fromtimestamp(1111111109, UTC)) == "081804"


@pytest.mark.parametrize("counter", [-1, 2**64])
def test_a_counter_outside_eight_bytes_is_refused(counter: int) -> None:
    with pytest.raises(ValueError, match="compteur"):
        hotp(KEY, counter)


@pytest.mark.parametrize("digits", [5, 9])
def test_a_code_has_six_to_eight_digits(digits: int) -> None:
    with pytest.raises(ValueError, match="chiffres"):
        hotp(KEY, 1, digits=digits)


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError, match="fuseau"):
        time_step(datetime(2026, 10, 21, 12, 0))


def test_time_steps_are_thirty_seconds_from_the_epoch() -> None:
    assert STEP_SECONDS == 30
    assert time_step(datetime.fromtimestamp(59, UTC)) == 1
    assert time_step(datetime.fromtimestamp(60, UTC)) == 2


def test_a_secret_ignores_spaces_case_and_missing_padding() -> None:
    key = b"\x01" * 20
    text = base64.b32encode(key).decode().rstrip("=").lower()
    spaced = " ".join(text[i : i + 4] for i in range(0, len(text), 4))
    assert decode_secret(spaced) == key


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "base32 attendu"),
        ("JBSWY3DP!", "base32 attendu"),
        ("A" * 9, "base32 invalide"),
        ("JBSWY3DPEHPK3PXP", "au moins 20 octets"),
    ],
)
def test_an_unusable_secret_is_refused(text: str, message: str) -> None:
    with pytest.raises(TotpError, match=message):
        decode_secret(text)


def test_the_key_comes_from_the_environment_or_not_at_all() -> None:
    secret = generate_secret()
    assert key_from_environment({SECRET_ENV: secret}) == decode_secret(secret)
    assert key_from_environment({}) is None
    assert key_from_environment({SECRET_ENV: ""}) is None
    assert key_from_environment({SECRET_ENV: "trop court"}) is None


def test_a_generated_secret_has_160_bits_and_no_padding() -> None:
    secret = generate_secret()
    assert "=" not in secret
    assert len(decode_secret(secret)) == 20
    assert generate_secret() != secret


def test_the_provisioning_uri_follows_the_key_uri_format() -> None:
    secret = generate_secret()
    uri = urlsplit(provisioning_uri(secret))
    assert (uri.scheme, uri.netloc, uri.path) == ("otpauth", "totp", "/CERVEAU%3Alucas")
    assert parse_qs(uri.query) == {
        "secret": [secret],
        "issuer": ["CERVEAU"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }
    with pytest.raises(TotpError):
        provisioning_uri("court")


def test_the_current_code_is_accepted_at_its_step() -> None:
    code = totp(KEY, NOW)
    assert verify(KEY, code, NOW, last_step=None) == time_step(NOW)


@pytest.mark.parametrize("shift", [-1, 1])
def test_a_code_one_step_off_is_accepted(shift: int) -> None:
    code = totp(KEY, NOW + timedelta(seconds=shift * STEP_SECONDS))
    assert verify(KEY, code, NOW, last_step=None) == time_step(NOW) + shift


@pytest.mark.parametrize("shift", [-2, 2])
def test_a_code_two_steps_off_is_refused(shift: int) -> None:
    code = totp(KEY, NOW + timedelta(seconds=shift * STEP_SECONDS))
    assert verify(KEY, code, NOW, last_step=None) is None


def test_a_code_never_serves_twice() -> None:
    code = totp(KEY, NOW)
    step = verify(KEY, code, NOW, last_step=None)
    assert step is not None
    assert verify(KEY, code, NOW, last_step=step) is None
    assert verify(KEY, totp(KEY, NOW - timedelta(seconds=30)), NOW, last_step=step) is None
    later = NOW + timedelta(seconds=30)
    assert verify(KEY, totp(KEY, later), later, last_step=step) == step + 1


@pytest.mark.parametrize("code", ["", "12345", "1234567", "12345a", "١٢٣٤٥٦", " 12345", "+12345"])
def test_a_malformed_code_is_refused(code: str) -> None:
    assert verify(KEY, code, NOW, last_step=None) is None


def test_without_a_key_every_code_is_refused() -> None:
    zero_key_code = hotp(b"\0" * 20, time_step(NOW))
    assert verify(None, zero_key_code, NOW, last_step=None) is None


def test_near_the_epoch_no_negative_step_is_tried() -> None:
    epoch = datetime.fromtimestamp(0, UTC)
    assert verify(KEY, hotp(KEY, 0), epoch, last_step=None) == 0
    before = datetime.fromtimestamp(-90, UTC)
    assert verify(KEY, hotp(KEY, 0), before, last_step=None) is None


@given(st.integers(min_value=1, max_value=4_000_000_000), st.integers(0, 999_999))
def test_only_codes_of_the_window_are_accepted(seconds: int, guess: int) -> None:
    when = datetime.fromtimestamp(seconds, UTC)
    code = f"{guess:06d}"
    step = verify(KEY, code, when, last_step=None)
    current = time_step(when)
    window = {s: hotp(KEY, s) for s in range(max(current - 1, 0), current + 2)}
    if code in window.values():
        assert step in window
        assert window[step] == code
    else:
        assert step is None

"""ECB Data Portal: euro reference rates and the €STR, over HTTPS without a key (ADR-017, D2).

Facts checked on 2026-10-18 on the ECB's pages:

- reference rates (flow ``EXR``, key ``D.<currencies>.EUR.SP00.A``, units of currency per euro):
  updated « around 16:00 CET every working day, except on TARGET closing days »; the ECB
  publishes them for information and advises against using them for transactions;
- €STR (flow ``EST``, key ``B.EU000A2X2A25.WT``, percent per year): published at 08:00 CET on
  the TARGET business day after the one it describes.

``published_at`` is that documented time, in Frankfurt, plus the margin of
``providers.base``, and never later than the fetch. The ``csvdata`` columns used here (``KEY``,
``CURRENCY``, ``TIME_PERIOD``, ``OBS_VALUE``) are still to check on a real response
(A_VERIFIER): an unexpected header refuses the response instead of guessing.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from core.finance.calendars import next_target_day
from core.finance.model import FxRate, MarketRecord, RateObservation
from core.finance.providers.base import ProviderError, published, validation_message

ECB_SOURCE = "ecb"
FRANKFURT = ZoneInfo("Europe/Berlin")
FX_CATEGORY, ESTR_CATEGORY = "fx_reference_rates", "estr"
CATEGORIES = (FX_CATEGORY, ESTR_CATEGORY)
ESTR_SERIES_ID = "estr"
ESTR_KEY = "B.EU000A2X2A25.WT"
FX_PUBLISHED_AT = time(16)  # same day
ESTR_PUBLISHED_AT = time(8)  # next TARGET business day
TIMEOUT_S = 30.0
MAX_BYTES = 32_000_000
USER_AGENT = "CERVEAU/0.2 (assistant personnel, lecture seule)"
MISSING_VALUES = {"", "NaN"}


@dataclass
class EcbProvider:
    base_url: str  # data_sources.yaml › sources.ecb.url
    categories: Sequence[str]  # data_sources.yaml › sources.ecb.categories
    currencies: Sequence[str]
    start: date
    end: date
    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    timeout_s: float = TIMEOUT_S
    source: ClassVar[str] = ECB_SOURCE

    def __post_init__(self) -> None:
        unknown = sorted(set(self.categories) - set(CATEGORIES))
        if unknown:
            raise ProviderError(
                f"catégories BCE non prises en charge : {', '.join(unknown)} "
                f"(prises en charge : {', '.join(CATEGORIES)})"
            )
        if httpx.URL(self.base_url).scheme != "https":
            raise ProviderError("l'URL de la BCE doit être en https")
        if self.start > self.end:
            raise ProviderError(f"période vide : {self.start} après {self.end}")
        for currency in self.currencies:
            if len(currency) != 3 or not currency.isupper() or currency == "EUR":
                raise ProviderError(f"devise invalide pour le change contre l'euro : {currency}")
        self.received: dict[str, int] = {}

    def describe(self) -> dict[str, Any]:
        return {
            "categories": sorted(self.categories),
            "currencies": sorted(self.currencies),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "observations": dict(self.received),
        }

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        records: list[MarketRecord] = []
        with self._client() as client:
            if FX_CATEGORY in self.categories and self.currencies:
                key = f"D.{'+'.join(sorted(self.currencies))}.EUR.SP00.A"
                rows = self._get(client, "EXR", key)
                fx = [self._fx_rate(row, fetched_at) for row in rows]
                self.received[FX_CATEGORY] = len(fx)
                records += fx
            if ESTR_CATEGORY in self.categories:
                rows = self._get(client, "EST", ESTR_KEY)
                estr = [self._estr(row, fetched_at) for row in rows]
                self.received[ESTR_CATEGORY] = len(estr)
                records += estr
        return records

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self.transport,
            follow_redirects=False,
            timeout=httpx.Timeout(self.timeout_s),
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
        )

    def _get(self, client: httpx.Client, flow: str, key: str) -> list[dict[str, str]]:
        url = f"{self.base_url.rstrip('/')}/data/{flow}/{key}"
        params = {
            "startPeriod": self.start.isoformat(),
            "endPeriod": self.end.isoformat(),
            "format": "csvdata",
            "detail": "dataonly",
        }
        try:
            with client.stream("GET", url, params=params) as response:
                if response.status_code != httpx.codes.OK:
                    # The body is external content (R5): only the status is reported.
                    raise ProviderError(
                        f"BCE {flow} : réponse HTTP {response.status_code} (clé ou période "
                        "à vérifier ; 404 signifie qu'aucune observation ne correspond)"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise ProviderError(f"BCE {flow} : réponse de plus de {MAX_BYTES} octets")
        except httpx.TimeoutException:
            raise ProviderError(f"BCE {flow} : délai de {self.timeout_s:g} s dépassé") from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"BCE {flow} : injoignable ({type(exc).__name__})") from None
        return _parse_csv(flow, bytes(body))

    def _fx_rate(self, row: dict[str, str], fetched_at: datetime) -> FxRate:
        currency = row.get("CURRENCY") or _key_part(row, 1)
        if currency not in self.currencies or row.get("CURRENCY_DENOM", "EUR") != "EUR":
            raise ProviderError("BCE EXR : série inattendue dans la réponse")
        session = _session(row)
        documented = datetime.combine(session, FX_PUBLISHED_AT, tzinfo=FRANKFURT)
        return _validated(
            FxRate,
            "EXR",
            {
                "currency": currency,
                "session": session,
                "rate": row["OBS_VALUE"],
                "source": ECB_SOURCE,
                "published_at": published(documented, fetched_at),
            },
        )

    def _estr(self, row: dict[str, str], fetched_at: datetime) -> RateObservation:
        if "KEY" in row and row["KEY"] != f"EST.{ESTR_KEY}":
            raise ProviderError("BCE EST : série inattendue dans la réponse")
        session = _session(row)
        documented = datetime.combine(next_target_day(session), ESTR_PUBLISHED_AT, tzinfo=FRANKFURT)
        return _validated(
            RateObservation,
            "EST",
            {
                "series_id": ESTR_SERIES_ID,
                "session": session,
                "value_pct": row["OBS_VALUE"],
                "source": ECB_SOURCE,
                "published_at": published(documented, fetched_at),
            },
        )


def _parse_csv(flow: str, body: bytes) -> list[dict[str, str]]:
    """The observations of a ``csvdata`` response; a missing value (holiday) is skipped."""
    try:
        text = body.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        columns = set(reader.fieldnames or ())
        expected = {"TIME_PERIOD", "OBS_VALUE"} | ({"CURRENCY"} if flow == "EXR" else set())
        if not expected <= columns and not ({"TIME_PERIOD", "OBS_VALUE", "KEY"} <= columns):
            raise ProviderError(
                f"BCE {flow} : en-tête inattendu (colonnes TIME_PERIOD, OBS_VALUE et KEY ou "
                "CURRENCY attendues, format csvdata à vérifier)"
            )
        return [row for row in reader if row.get("OBS_VALUE", "").strip() not in MISSING_VALUES]
    except (UnicodeDecodeError, csv.Error):
        raise ProviderError(f"BCE {flow} : réponse CSV illisible") from None


def _key_part(row: dict[str, str], position: int) -> str:
    """A dimension read from ``KEY`` (``EXR.D.USD.EUR.SP00.A``: flow first)."""
    parts = row.get("KEY", "").split(".")
    return parts[position + 1] if len(parts) > position + 1 else ""


def _session(row: dict[str, str]) -> date:
    try:
        return date.fromisoformat(row["TIME_PERIOD"])
    except (KeyError, ValueError):
        raise ProviderError("BCE : date d'observation illisible (journalière attendue)") from None


def _validated[R: FxRate | RateObservation](model: type[R], flow: str, values: dict[str, Any]) -> R:
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        reason = validation_message(exc)
        raise ProviderError(f"BCE {flow} : observation refusée ({reason})") from None

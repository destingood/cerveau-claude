"""Records of the finance store and the timestamps they carry (ADR-012, R10).

Every market record carries its value date, the time it was published (``published_at``) and,
once stored, the time CERVEAU ingested it. Timestamps are timezone-aware and stored in UTC with a
fixed format, so that text comparison in SQLite is time comparison.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.config.loader import Marker
from core.guardrails.injection import injection_signals

# CERVEAU's reference time zone: a date given by Lucas (« au 16 octobre ») is a Paris date.
PARIS = ZoneInfo("Europe/Paris")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
MAX_NAME_CHARS = 120

InstrumentId = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
SourceId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
SeriesId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
AssetClass = Literal["equity", "etf", "bond", "gold", "fund"]


def utc_text(moment: datetime) -> str:
    """The stored form of a timestamp; a naive datetime is refused (its time zone is unknown)."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("horodatage sans fuseau horaire")
    return moment.astimezone(UTC).strftime(_TS_FORMAT)


def from_utc_text(text: str) -> datetime:
    return datetime.strptime(text, _TS_FORMAT).replace(tzinfo=UTC)


def end_of_day(day: date, tz: ZoneInfo = PARIS) -> datetime:
    """The last instant of ``day`` in ``tz``: « au 16 octobre » means after that day's close."""
    return datetime.combine(day + timedelta(days=1), time(), tzinfo=tz) - timedelta(microseconds=1)


def local_date(moment: datetime, tz: ZoneInfo = PARIS) -> date:
    utc_text(moment)  # refuses a naive datetime
    return moment.astimezone(tz).date()


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Instrument(_Record):
    """One version of an instrument's reference data, valid from ``valid_from`` (included)."""

    instrument_id: InstrumentId
    valid_from: date
    valid_to: date | None = None  # excluded; None while the instrument is alive
    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] | None = None
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    asset_class: AssetClass
    currency: Currency  # the currency of its prices and dividends
    mic: Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]  # the exchange, for its calendar
    sector: str = Field(min_length=1, max_length=40)
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    # Modified duration in years, entered by hand for bonds; A_DEFINIR blocks the rate stress.
    duration: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | Marker | None = None

    @field_validator("name", "sector")
    @classmethod
    def _plain_data(cls, value: str) -> str:
        # Names come from CSV files or providers: external content, never instructions (R5).
        if any(not char.isprintable() for char in value):
            raise ValueError("caractères de contrôle interdits")
        if injection_signals(value):
            raise ValueError("texte refusé : il ressemble à une consigne (R5)")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Instrument:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to doit suivre valid_from")
        if (self.asset_class == "bond") != (self.duration is not None):
            raise ValueError("une duration se déclare pour une obligation, et pour elle seule")
        return self


class _Published(_Record):
    """A record that became known at ``published_at``, never before its value date started."""

    source: SourceId
    published_at: AwareDatetime

    @property
    def value_date(self) -> date:
        raise NotImplementedError

    @model_validator(mode="after")
    def _published_after_value_date(self) -> _Published:
        if self.published_at < datetime.combine(self.value_date, time(), tzinfo=UTC):
            raise ValueError("publié avant sa date de valeur")
        return self


class PriceRow(_Published):
    """A raw, unadjusted close in the instrument's currency."""

    instrument_id: InstrumentId
    session: date
    close: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    volume: Annotated[int, Field(ge=0)] | None = None
    currency: Currency

    @property
    def value_date(self) -> date:
        return self.session


class CorporateAction(_Published):
    """A split (``value``: new shares per old share) or a cash dividend per share."""

    instrument_id: InstrumentId
    ex_date: date
    kind: Literal["split", "dividend"]
    value: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    currency: Currency | None = None  # dividends only

    @property
    def value_date(self) -> date:
        # A split or a dividend is announced before its ex-date: only the publication matters.
        return date.min

    @model_validator(mode="after")
    def _kind_fields(self) -> CorporateAction:
        if self.kind == "split" and (self.currency is not None or self.value == 1):
            raise ValueError("un split n'a pas de devise et change le nombre de titres")
        if self.kind == "dividend" and self.currency is None:
            raise ValueError("un dividende porte sa devise")
        return self


class FxRate(_Published):
    """A reference rate: units of ``currency`` for one euro (ECB convention)."""

    currency: Currency
    session: date
    rate: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @property
    def value_date(self) -> date:
        return self.session

    @field_validator("currency")
    @classmethod
    def _not_euro(cls, value: str) -> str:
        if value == "EUR":
            raise ValueError("le change se donne contre l'euro : EUR vaut 1 par définition")
        return value


class RateObservation(_Published):
    """A rate in percent per year, as published (the €STR, a yield-curve point)."""

    series_id: SeriesId
    session: date
    value_pct: Annotated[float, Field(ge=-100, le=100, allow_inf_nan=False)]

    @property
    def value_date(self) -> date:
        return self.session


MarketRecord = PriceRow | CorporateAction | FxRate | RateObservation

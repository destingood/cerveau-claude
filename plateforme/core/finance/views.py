"""What the read tools of the finance pack return (plan of phase 2, §8; ADR-015).

``market_data`` and ``portfolio_snapshot`` read the finance store as known at ``as_of``, and
compute nothing a model could get wrong: every number is a :class:`Figure` with its value, its
French display and an id (R1). No free text from a provider reaches the output (R5): the names
and sectors were checked by ``plain_text`` when they entered the store and are checked again
when they are read back.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from core.finance.adjust import Adjustment
from core.finance.model import AssetClass, Instrument, local_date
from core.finance.portfolio import (
    GAP_ALERT,
    AccountReconciliation,
    PortfolioError,
    ValuedLine,
    build_book,
    reconciliation_status,
    value,
)
from core.finance.schema import SchemaError
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from core.verification.figures import (
    Figure,
    amount,
    count,
    fx_rate,
    percent,
    plain,
    price,
    quantity,
)

Kind = Literal["cours", "referentiel", "fondamentaux"]
QualityGate = Literal["suffisante", "insuffisante", "non_evaluable"]
HOME_ENV = "CERVEAU_HOME"
CASH_BUCKET = "liquidites"  # sector and country of a cash balance
MAX_INSTRUMENTS = 10
MAX_SESSIONS = 260  # about one year of sessions
QUALITY_CAP = "N1"  # the highest level a decision keeps while the data quality is not enough
CAPPED = f"toute décision reste plafonnée à {QUALITY_CAP}"
NO_FUNDAMENTALS = (
    "fondamentaux indisponibles : aucun fournisseur n'est retenu (ADR-013) ; ils seraient "
    "d'ailleurs révisés par le fournisseur, donc non point-in-time"
)


class ViewError(Exception):
    """A request the store cannot answer; the message names identifiers, never a value."""


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def moment(as_of: datetime | None, now: datetime) -> datetime:
    """``as_of``, or now; a moment in the future is refused (R10)."""
    if as_of is None:
        return now
    if as_of > now:
        raise ViewError("as_of est dans le futur : une lecture « connue à » porte sur le passé")
    return as_of


def home_location(environ: Mapping[str, str]) -> Path:
    """The project a plugin serves: ``CERVEAU_HOME``, else this checkout."""
    home = environ.get(HOME_ENV, "").strip()
    return Path(home) if home else Path(__file__).resolve().parents[2]


def store_location(environ: Mapping[str, str]) -> Path:
    """The store of the project a plugin serves: ``CERVEAU_HOME``, else this checkout."""
    return default_store_path(home_location(environ))


def config_location(environ: Mapping[str, str]) -> Path:
    """The ``config/`` directory of the same project."""
    return home_location(environ) / "config"


def read_store[T](path: Path, read: Callable[[FinanceStore], T]) -> T:
    """Open the store read only for one call. A failure is a ViewError whose message names no
    stored value: a record that no longer passes its checks is not quoted (R5)."""
    try:
        with FinanceStore.open(path, read_only=True) as store:
            return read(store)
    except (FinanceStoreError, SchemaError, PortfolioError) as exc:
        raise ViewError(str(exc)) from None
    except ValidationError:
        raise ViewError(
            "une donnée de la base ne passe plus ses contrôles à la relecture"
        ) from None
    except sqlite3.Error:
        raise ViewError("base finance illisible") from None


def _instrument(
    store: FinanceStore, instrument_id: str, as_of: datetime, strict: bool
) -> Instrument:
    found = store.instrument(instrument_id, as_of=as_of, strict=strict)
    if found is None:
        raise ViewError(f"{instrument_id} : absent du référentiel à cette date")
    return found


# market_data ---------------------------------------------------------------------------------


class Close(_Out):
    session: date
    close: Figure


class Quality(_Out):
    """The last quality score recorded for the series at ``assessed_at`` or before (ADR-016)."""

    assessed_at: AwareDatetime
    score: Figure | None  # the minimum of the four sub-scores; None when one is not evaluated
    gaps: Figure | None
    corporate_actions: Figure | None
    outliers: Figure | None
    freshness: Figure | None
    stale_sessions: Figure | None
    not_evaluated: dict[str, str]


class QualityDetailsView(BaseModel):
    """The part of the recorded details shown to the planner; the rest stays in the store."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    stale_sessions: int | None = None
    not_evaluated: dict[str, str] = {}


class PriceSeries(_Out):
    instrument_id: str
    name: str
    currency: str
    mic: str
    adjust: Adjustment
    closes: list[Close]
    last_session: date | None
    age_days: Figure | None  # calendar days from the last close to the Paris date of as_of
    quality: Quality | None
    quality_note: str | None = None


class ReferenceCard(_Out):
    instrument_id: str
    name: str
    asset_class: AssetClass
    currency: str
    mic: str
    sector: str
    country: str
    isin: str | None
    valid_from: date
    valid_to: date | None
    duration: Figure | None  # modified duration of a bond, in years
    duration_note: str | None = None


class MarketData(_Out):
    parity_label: Literal["[Approximation]"] = "[Approximation]"  # as plugin.yaml (R12)
    kind: Kind
    as_of: AwareDatetime
    day: date
    strict: bool
    series: list[PriceSeries] = []
    cards: list[ReferenceCard] = []


def _quality(
    store: FinanceStore, instrument_id: str, as_of: datetime, strict: bool
) -> Quality | None:
    """A recorded score uses only what was ingested by its own date: it holds from then on;
    strict, it counts once it was computed."""
    known = [
        row
        for row in store.quality_history(instrument_id)
        if datetime.fromisoformat(row["as_of"]) <= as_of
        and (not strict or datetime.fromisoformat(row["computed_at"]) <= as_of)
    ]
    if not known:
        return None
    row = known[-1]
    details = QualityDetailsView.model_validate_json(row["details"])
    base = f"{instrument_id}/qualite"

    def score(name: str) -> Figure | None:
        found = row[name]
        return None if found is None else plain(f"{base}/{name}", float(found), "score", 3)

    stale = details.stale_sessions
    return Quality(
        assessed_at=datetime.fromisoformat(row["as_of"]),
        score=score("score"),
        gaps=score("gaps"),
        corporate_actions=score("corporate_actions"),
        outliers=score("outliers"),
        freshness=score("freshness"),
        stale_sessions=None if stale is None else count(f"{base}/stale_sessions", stale, "séances"),
        not_evaluated=details.not_evaluated,
    )


class SeriesScore(_Out):
    instrument_id: str
    assessed_at: AwareDatetime | None
    score: Figure | None


class QualityCheck(_Out):
    """The recorded quality of the series a calculation reads, against
    ``min_quality_score_above_N1`` (D12): below it, or while it cannot be judged, a decision
    stays capped at N1 and the output says so with the scores (plan of phase 2, §3)."""

    threshold: Figure | None
    gate: QualityGate
    decision_cap: Literal["N1"] | None
    series: list[SeriesScore]
    below: list[str]
    not_evaluated: list[str]
    note: str | None = None


def quality_check(
    store: FinanceStore,
    instrument_ids: Sequence[str],
    *,
    as_of: datetime,
    strict: bool,
    threshold: float | str,
) -> QualityCheck:
    """The gate of the held series at ``as_of``. A threshold still at a marker, or a series
    without a complete score at that date, cannot be judged: ``non_evaluable`` (R7)."""
    marker = isinstance(threshold, str)
    cut = None if marker else plain("qualite/seuil", float(threshold), "score", 3)
    series: list[SeriesScore] = []
    below: list[tuple[str, Figure]] = []
    missing: list[str] = []
    for iid in dict.fromkeys(instrument_ids):
        found = _quality(store, iid, as_of, strict)
        score = None if found is None else found.score
        series.append(
            SeriesScore(
                instrument_id=iid,
                assessed_at=None if found is None else found.assessed_at,
                score=score,
            )
        )
        if score is None:
            missing.append(iid)
        elif cut is not None and score.value < cut.value:
            below.append((iid, score))
    notes = []
    if cut is None:
        notes.append(f"le seuil min_quality_score_above_N1 vaut {threshold} (R7)")
    if below and cut is not None:
        scores = ", ".join(f"{iid} score {score.display}" for iid, score in below)
        notes.append(f"{scores} sous le seuil {cut.display}")
    if missing:
        notes.append(f"aucun score complet enregistré à cette date pour {', '.join(missing)}")
    gate: QualityGate = "insuffisante" if below else "non_evaluable" if notes else "suffisante"
    note = None
    if notes:
        title = "qualité des données insuffisante" if below else "qualité non évaluable"
        note = f"{title} : {' ; '.join(notes)} (D12) ; {CAPPED}"
    return QualityCheck(
        threshold=cut,
        gate=gate,
        decision_cap=None if gate == "suffisante" else QUALITY_CAP,
        series=series,
        below=[iid for iid, _ in below],
        not_evaluated=missing,
        note=note,
    )


def market_data(
    store: FinanceStore,
    instrument_ids: Sequence[str],
    *,
    kind: Kind,
    as_of: datetime,
    sessions: int = 20,
    adjust: Adjustment = "none",
    strict: bool = False,
) -> MarketData:
    """Closes (the last ``sessions`` up to the Paris date of ``as_of``) or reference cards."""
    if kind == "fondamentaux":
        raise ViewError(NO_FUNDAMENTALS)
    ids = list(dict.fromkeys(instrument_ids))
    if not 0 < len(ids) <= MAX_INSTRUMENTS:
        raise ViewError(f"de 1 à {MAX_INSTRUMENTS} instruments distincts")
    if not 0 < sessions <= MAX_SESSIONS:
        raise ViewError(f"de 1 à {MAX_SESSIONS} séances")
    day = local_date(as_of)
    instruments = [_instrument(store, i, as_of, strict) for i in ids]
    if kind == "referentiel":
        return MarketData(
            kind=kind, as_of=as_of, day=day, strict=strict, cards=[_card(i) for i in instruments]
        )
    series = []
    for instrument in instruments:
        iid = instrument.instrument_id
        closes = store.closes(iid, as_of=as_of, end=day, adjust=adjust, strict=strict)
        kept = closes.iloc[-sessions:]
        last = kept.index[-1].date() if not kept.empty else None
        quality = _quality(store, iid, as_of, strict)
        series.append(
            PriceSeries(
                instrument_id=iid,
                name=instrument.name,
                currency=instrument.currency,
                mic=instrument.mic,
                adjust=adjust,
                closes=[
                    Close(
                        session=s.date(),
                        close=price(f"{iid}/cloture/{s.date():%Y-%m-%d}", v, instrument.currency),
                    )
                    for s, v in kept.items()
                ],
                last_session=last,
                age_days=None
                if last is None
                else count(f"{iid}/age_jours", (day - last).days, "jours"),
                quality=quality,
                quality_note=None if quality else "aucun score de qualité enregistré à cette date",
            )
        )
    return MarketData(kind=kind, as_of=as_of, day=day, strict=strict, series=series)


def _card(instrument: Instrument) -> ReferenceCard:
    duration = instrument.duration
    known = isinstance(duration, float | int)
    return ReferenceCard(
        instrument_id=instrument.instrument_id,
        name=instrument.name,
        asset_class=instrument.asset_class,
        currency=instrument.currency,
        mic=instrument.mic,
        sector=instrument.sector,
        country=instrument.country,
        isin=instrument.isin,
        valid_from=instrument.valid_from,
        valid_to=instrument.valid_to,
        duration=plain(
            f"{instrument.instrument_id}/duration", float(duration), "ans", 1, show_unit=True
        )
        if known
        else None,
        duration_note=f"duration {duration} (saisie manuelle attendue)"
        if isinstance(duration, str)
        else None,
    )


# portfolio_snapshot --------------------------------------------------------------------------


class Position(_Out):
    account: str
    instrument_id: str
    name: str
    asset_class: AssetClass
    sector: str
    country: str
    currency: str
    quantity: Figure
    cost: Figure  # cost basis at the weighted average price, fees included (ADR-018)
    average_price: Figure
    close: Figure | None  # on the basis of the quantity held, splits applied
    close_date: date | None
    fx_rate: Figure | None  # None for a position in euros
    fx_date: date | None
    value_eur: Figure | None
    unrealized_gain: Figure | None  # quantity × close − cost, in the currency of the position
    weight: Figure | None


class CashBalance(_Out):
    account: str
    currency: str
    balance: Figure
    fx_rate: Figure | None
    fx_date: date | None
    value_eur: Figure | None
    weight: Figure | None


class Exposure(_Out):
    key: str
    value_eur: Figure
    weight: Figure | None  # None when the total is zero


class Exposures(_Out):
    """Cash counts in its currency, and in the ``liquidites`` bucket for sector and country."""

    sector: list[Exposure]
    country: list[Exposure]
    currency: list[Exposure]


class GapRef(_Out):
    nature: Literal["titre", "especes"]
    asset: str  # quantities are shown by the CLI only (ADR-018)


class AccountStatus(_Out):
    account: str
    status: Literal["ok", "ecart", "non_rapproche"]
    statement_date: date | None
    gaps: list[GapRef]


class Snapshot(_Out):
    parity_label: Literal["[Parité]"] = "[Parité]"  # as plugin.yaml (R12)
    as_of: AwareDatetime
    day: date
    strict: bool
    total_eur: Figure | None  # absent, never partial, when a value is missing (R12)
    missing: list[str]
    positions: list[Position]
    cash: list[CashBalance]
    exposures: Exposures | None
    reconciliation: list[AccountStatus]
    alert: Literal["rapprochement: ecart"] | None
    warnings: list[str]


def portfolio_snapshot(store: FinanceStore, *, as_of: datetime, strict: bool = False) -> Snapshot:
    """Positions, cash, weights and exposures at the end of the Paris date of ``as_of``."""
    book = build_book(store, as_of=as_of, strict=strict)
    valuation = value(store, book, strict=strict)
    total = valuation.total_eur
    lines = [line for line in valuation.lines if line.quantity]
    cards = {
        line.asset: _instrument(store, line.asset, as_of, strict)
        for line in lines
        if line.nature == "security"
    }
    costs = {(h.account, h.instrument_id): h for h in book.holdings}

    def weight(figure_id: str, amount_eur: float | None) -> Figure | None:
        if amount_eur is None or not total:
            return None
        return percent(figure_id, amount_eur / total)

    def eur(figure_id: str, amount_eur: float | None) -> Figure | None:
        return None if amount_eur is None else amount(figure_id, amount_eur, "EUR")

    def rate(figure_id: str, line: ValuedLine) -> Figure | None:
        if line.currency == "EUR" or line.fx_rate is None:
            return None
        return fx_rate(figure_id, line.fx_rate, line.currency)

    positions, cash = [], []
    for line in lines:
        base = f"positions/{line.account}/{line.asset}"
        if line.nature == "cash":
            base = f"cash/{line.account}/{line.asset}"
            cash.append(
                CashBalance(
                    account=line.account,
                    currency=line.currency,
                    balance=amount(f"{base}/solde", line.quantity, line.currency),
                    fx_rate=rate(f"{base}/change", line),
                    fx_date=line.fx_date if line.currency != "EUR" else None,
                    value_eur=eur(f"{base}/valeur_eur", line.value_eur),
                    weight=weight(f"{base}/poids", line.value_eur),
                )
            )
            continue
        card, holding = cards[line.asset], costs[(line.account, line.asset)]
        gain = None
        if line.close is not None:
            gain = float(line.quantity) * line.close - float(holding.cost)
        positions.append(
            Position(
                account=line.account,
                instrument_id=line.asset,
                name=card.name,
                asset_class=card.asset_class,
                sector=card.sector,
                country=card.country,
                currency=line.currency,
                quantity=quantity(f"{base}/quantite", line.quantity),
                cost=amount(f"{base}/cout", holding.cost, line.currency),
                average_price=price(f"{base}/prix_moyen", holding.average_price, line.currency),
                close=None
                if line.close is None
                else price(f"{base}/cloture", line.close, line.currency),
                close_date=line.close_date,
                fx_rate=rate(f"{base}/change", line),
                fx_date=line.fx_date if line.currency != "EUR" else None,
                value_eur=eur(f"{base}/valeur_eur", line.value_eur),
                unrealized_gain=None
                if gain is None
                else amount(f"{base}/plus_value_latente", gain, line.currency),
                weight=weight(f"{base}/poids", line.value_eur),
            )
        )
    reconciliation = reconciliation_status(store, as_of=as_of, strict=strict)
    warnings = list(book.warnings)
    if not book.accounts:
        warnings.append(
            "aucune transaction connue à cette date (import : `cerveau portfolio import`)"
        )
    return Snapshot(
        as_of=as_of,
        day=book.day,
        strict=strict,
        total_eur=None if total is None else amount("total_eur", total, "EUR"),
        missing=valuation.missing,
        positions=positions,
        cash=cash,
        exposures=None if total is None else _exposures(lines, cards, total),
        reconciliation=[_status(a) for a in reconciliation],
        alert=GAP_ALERT if any(a.gaps for a in reconciliation) else None,
        warnings=warnings,
    )


def _exposures(
    valued: Iterable[ValuedLine], cards: dict[str, Instrument], total: float
) -> Exposures:
    lines = list(valued)

    def by(axis: str, key: Callable[[ValuedLine], str]) -> list[Exposure]:
        sums: defaultdict[str, list[float]] = defaultdict(list)
        for line in lines:
            sums[key(line)].append(line.value_eur or 0.0)
        rows = sorted(((math.fsum(v), k) for k, v in sums.items()), key=lambda r: (-r[0], r[1]))
        return [
            Exposure(
                key=k,
                value_eur=amount(f"expositions/{axis}/{k}/valeur_eur", v, "EUR"),
                weight=percent(f"expositions/{axis}/{k}/poids", v / total) if total else None,
            )
            for v, k in rows
        ]

    def field(name: str) -> Callable[[ValuedLine], str]:
        return lambda line: (
            CASH_BUCKET if line.nature == "cash" else getattr(cards[line.asset], name)
        )

    return Exposures(
        sector=by("secteur", field("sector")),
        country=by("pays", field("country")),
        currency=by("devise", lambda line: line.currency),
    )


def _status(account: AccountReconciliation) -> AccountStatus:
    nature: dict[str, Literal["titre", "especes"]] = {"security": "titre", "cash": "especes"}
    return AccountStatus(
        account=account.account,
        status=account.status,
        statement_date=account.statement_date,
        gaps=[GapRef(nature=nature[g.nature], asset=g.asset) for g in account.gaps],
    )


__all__ = [
    "MAX_INSTRUMENTS",
    "MAX_SESSIONS",
    "Kind",
    "MarketData",
    "Snapshot",
    "ViewError",
    "config_location",
    "market_data",
    "moment",
    "portfolio_snapshot",
    "read_store",
    "store_location",
]

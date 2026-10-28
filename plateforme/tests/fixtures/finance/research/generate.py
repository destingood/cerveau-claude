"""Generate the synthetic research dataset of the backtest protocol (phase 3 plan, §7, D4).

Every value is invented: four fictitious instruments (``FICT-R…``) quoted in euros on Euronext
Paris for ten years, drawn from a fixed seed. One carries a planted trend effect, so that the
protocol has something real to find; three are random walks without any edge, so that it has
something to reject. Three fictitious crises hit them all. A few closes come out the next
morning and a few prints are corrected the next day, so that the point-in-time view has
something to hide. The effect is deliberately strong: it tests the protocol and says nothing
about a real market. Run it from the repository root; it rewrites the files next to it, and a
test checks they still match:

    uv run python tests/fixtures/finance/research/generate.py

As in the reference generator, the Gaussian draws are computed here (Box–Muller) and every
draw is taken on every weekday, so that the files depend neither on the Python version nor on
a holiday.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from core.finance.calendars import exchange_calendar
from core.finance.providers.base import PUBLICATION_MARGIN

HERE = Path(__file__).resolve().parent
# Chosen among twenty seeds swept with the parameters below (README): the one whose random walks
# sit furthest from the deflated Sharpe threshold, so that the tests do not ride on a coin toss.
SEED = "cerveau-recherche-2026-3"
FIRST, LAST = date(2016, 1, 4), date(2025, 12, 31)  # ten years of Euronext Paris sessions
# The fetch the files stand for (core.finance.fixtures): a Sunday, after every publication.
FETCHED_AT = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
MIC, CURRENCY = "XPAR", "EUR"
PARIS = ZoneInfo("Europe/Paris")
DAYS = 252

# The planted effect: the drift of FICT-RTEND is +TREND or −TREND a year, and flips with the
# probability SWITCH each weekday, so a regime lasts about a hundred sessions. The returns are
# positively autocorrelated over weeks, which a moving average crossover can follow. The regime
# also turns back towards the first close once the price leaves [start / BAND, start × BAND]:
# otherwise a run of falling regimes takes the price to a few cents.
TREND, SWITCH, BAND = 1.2, 0.01, 3.0


@dataclass(frozen=True)
class Spec:
    instrument_id: str
    name: str
    start: float  # first close
    drift: float  # annual log drift; for the trend, the size of the regime's drift
    vol: float  # annual volatility
    trend: bool = False


SPECS = (
    Spec("FICT-RTEND", "Tendance plantée (fictif)", 50.0, TREND, 0.15, trend=True),
    Spec("FICT-RALEA1", "Marche aléatoire 1 (fictif)", 40.0, 0.03, 0.18),
    Spec("FICT-RALEA2", "Marche aléatoire 2 (fictif)", 120.0, 0.03, 0.18),
    Spec("FICT-RALEA3", "Marche aléatoire 3 (fictif)", 75.0, 0.03, 0.18),
)


@dataclass(frozen=True)
class Crisis:
    name: str
    label: str
    start: date
    end: date


# Every instrument falls by FALL over the first FALL_DAYS weekdays of the window, with its
# volatility multiplied by CRISIS_VOL over all of it. The fall is sudden: a slow one would hand
# any trend follower an edge, the random walks included. The 2024 crisis lies in the final test
# sample.
CRISES = (
    Crisis("crise_fictive_2017", "Crise fictive de 2017 (synthétique)",
           date(2017, 5, 15), date(2017, 7, 7)),
    Crisis("crise_fictive_2019", "Crise fictive de 2019 (synthétique)",
           date(2019, 2, 4), date(2019, 3, 29)),
    Crisis("crise_fictive_2024", "Crise fictive de 2024 (synthétique)",
           date(2024, 2, 5), date(2024, 3, 28)),
)  # fmt: skip
FALL, FALL_DAYS, CRISIS_VOL = 0.25, 5, 2.0


@dataclass(frozen=True)
class Action:
    instrument_id: str
    ex_date: date
    kind: str  # CSV type: split, dividende
    value: float  # the split ratio, or the dividend as a share of the close when declared
    announced: date


# FICT-RALEA1 pays a yearly dividend, 2.5 % of its last close on the day it is declared, four
# weeks before the first session from 20 May. FICT-RALEA2 splits 2 for 1.
DIVIDEND_YIELD = 0.025
DIVIDEND_NOTICE = timedelta(weeks=4)
SPLIT = Action("FICT-RALEA2", date(2021, 6, 14), "split", 2.0, date(2021, 5, 17))

# Publications: 5 % of the closes reach the feed only the next weekday at 08:00 in Paris, and one
# close per instrument and year is first printed 4 % off, then corrected the next weekday at
# 09:00 in Paris. Every other close is known at the session's close plus the margin (ADR-017).
LATE_SHARE = 0.05
LATE_AT, CORRECTED_AT = time(8), time(9)
BAD_PRINT = 0.04

# Trading costs of the demonstration, invented: no broker charges them (D13 of phase 2 stays
# A_DEFINIR). The same fields as config/risk.yaml › trading_costs.
COSTS = {
    "commission_pct": "0.10",
    "min_commission_eur": "2.00",
    "slippage_bps": "5",
    "fx_conversion_bps": "10",
}


def normal(rng: random.Random) -> float:
    """One standard Gaussian draw (Box–Muller), from two ``random()`` calls only."""
    u1 = 1.0 - rng.random()  # in (0, 1]: its logarithm is finite
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _stream(name: str) -> random.Random:
    return random.Random(f"{SEED}:{name}")  # noqa: S311 - synthetic data, not a secret


def weekdays() -> Iterator[date]:
    day = FIRST
    while day <= LAST:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def in_paris(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=PARIS).astimezone(UTC)


def session_closes() -> dict[date, datetime]:
    """Each Euronext Paris session and its close, in UTC (early closes included)."""
    calendar = exchange_calendar(MIC, FIRST.year, LAST.year)
    if calendar is None:
        raise ValueError(f"{MIC} : calendrier inconnu")
    closes = calendar.closes[FIRST.isoformat() : LAST.isoformat()]
    return {session.date(): close.to_pydatetime() for session, close in closes.items()}


def crisis_shocks(open_days: set[date]) -> dict[date, tuple[float, float]]:
    """The extra log return and the volatility multiplier of each crisis weekday."""
    shocks: dict[date, tuple[float, float]] = {}
    for crisis in CRISES:
        if not {crisis.start, crisis.end} <= open_days:
            raise ValueError(f"{crisis.name} : bornes hors séance")
        days = [d for d in weekdays() if crisis.start <= d <= crisis.end]
        falling = days[:FALL_DAYS]
        for day in days:
            extra = math.log(1.0 - FALL) / len(falling) if day in falling else 0.0
            shocks[day] = (extra, CRISIS_VOL)
    return shocks


def actions(open_days: set[date]) -> list[Action]:
    ordered = sorted(open_days)
    dividends = []
    for year in range(FIRST.year, LAST.year + 1):
        ex_date = next(d for d in ordered if d >= date(year, 5, 20))
        announced = ex_date - DIVIDEND_NOTICE
        dividends.append(Action("FICT-RALEA1", ex_date, "dividende", DIVIDEND_YIELD, announced))
    found = sorted([*dividends, SPLIT], key=lambda a: (a.instrument_id, a.ex_date))
    if not {a.ex_date for a in found} <= open_days:
        raise ValueError("une date ex hors séance")
    return found


@dataclass(frozen=True)
class Series:
    closes: dict[date, float]
    dividends: dict[date, float]  # the amount paid, in euros, by ex-date


def series(spec: Spec, open_days: set[date], known: list[Action]) -> Series:
    """Log returns accumulated over the weekdays since the previous session. On an ex-date a
    split divides the previous close and a dividend is taken from it."""
    rng = _stream(spec.instrument_id)
    events = {a.ex_date: a for a in known if a.instrument_id == spec.instrument_id}
    shocks = crisis_shocks(open_days)
    daily = spec.vol / math.sqrt(DAYS)
    closes: dict[date, float] = {}
    paid: dict[date, float] = {}
    price, pending, regime = spec.start, 0.0, 1.0
    for day in weekdays():
        flip, shock = rng.random(), normal(rng)
        level = math.log(price / spec.start)
        if spec.trend and abs(level) > math.log(BAND):
            regime = -1.0 if level > 0 else 1.0
        elif spec.trend and flip < SWITCH:
            regime = -regime
        extra, scale = shocks.get(day, (0.0, 1.0))
        drift = regime * spec.drift if spec.trend else spec.drift
        pending += drift / DAYS + extra + scale * daily * shock
        if day not in open_days:
            continue
        action = events.get(day)
        if closes and action is not None:
            if action.kind == "split":
                price /= action.value
            else:
                declared = max(d for d in closes if d <= action.announced)
                paid[day] = round(action.value * closes[declared], 2)
                price -= paid[day]
        if closes:
            price *= math.exp(pending)
        closes[day], pending = price, 0.0
    if min(closes.values()) < 1.0:
        raise ValueError(f"{spec.instrument_id} : cours sous 1 €, la graine est à revoir")
    return Series(closes, paid)


@dataclass(frozen=True)
class Row:
    day: date
    instrument_id: str
    close: float
    published_at: datetime

    def text(self) -> str:
        published = self.published_at.isoformat().replace("+00:00", "Z")
        return f"{self.day},{self.instrument_id},{self.close:.2f},{CURRENCY},{published}"


def close_rows(
    built: dict[str, Series], closes_at: dict[date, datetime], known: list[Action]
) -> list[Row]:
    """Each close as the feed delivered it: one row, or a bad print and its correction."""
    ex_dates = {a.ex_date for a in known}
    rows: list[Row] = []
    for spec in SPECS:
        rng = _stream(f"publication:{spec.instrument_id}")
        days = list(built[spec.instrument_id].closes)
        bad: dict[date, float] = {}
        for year in range(FIRST.year, LAST.year + 1):
            candidates = [d for d in days[1:-1] if d.year == year and d not in ex_dates]
            day = candidates[rng.randrange(len(candidates))]
            bad[day] = 1.0 + BAD_PRINT if rng.random() < 0.5 else 1.0 - BAD_PRINT
        for day in days:
            close = built[spec.instrument_id].closes[day]
            on_time = closes_at[day] + PUBLICATION_MARGIN
            late = rng.random() < LATE_SHARE
            if day in bad:
                rows.append(Row(day, spec.instrument_id, close * bad[day], on_time))
                published = in_paris(next_weekday(day), CORRECTED_AT)
            else:
                published = in_paris(next_weekday(day), LATE_AT) if late else on_time
            rows.append(Row(day, spec.instrument_id, close, published))
    if max(r.published_at for r in rows) > FETCHED_AT:
        raise ValueError("une publication postérieure à la récupération")
    return rows


def _csv(header: str, rows: list[str]) -> str:
    return "\n".join([header, *rows]) + "\n"


def instruments_csv() -> str:
    rows = [
        f"{s.instrument_id},{s.name},action,{CURRENCY},{MIC},Synthétique,FR,{FIRST.isoformat()},"
        for s in SPECS
    ]
    return _csv("identifiant,nom,classe,devise,place,secteur,pays,debut,duration", rows)


def actions_csv(known: list[Action], built: dict[str, Series]) -> str:
    rows = []
    for a in known:
        if a.kind == "split":
            value, currency = f"{a.value:.2f}", ""
        else:
            value, currency = f"{built[a.instrument_id].dividends[a.ex_date]:.2f}", CURRENCY
        rows.append(
            f"{a.ex_date.isoformat()},{a.instrument_id},{a.kind},{value},{currency},"
            f"{a.announced.isoformat()}"
        )
    return _csv("date_ex,identifiant,type,valeur,devise,date_annonce", rows)


def crises_yaml() -> str:
    lines = [
        "# Fenêtres de crise FICTIVES du jeu de recherche synthétique, écrites par generate.py.",
        "# Elles ne décrivent aucune crise réelle. Même forme que",
        "# config/risk.yaml › market_risk.historical_stress.",
    ]
    for c in CRISES:
        lines += [
            f"{c.name}:",
            f'  label: "{c.label}"',
            f"  start: {c.start.isoformat()}",
            f"  end: {c.end.isoformat()}",
            '  source: "fictif : tests/fixtures/finance/research/generate.py"',
        ]
    return "\n".join(lines) + "\n"


def costs_yaml() -> str:
    lines = [
        "# Frais FICTIFS de démonstration, écrits par generate.py : aucun courtier ne les",
        "# pratique. Ils ne remplacent pas config/risk.yaml › trading_costs (A_DEFINIR, D13 de",
        "# la phase 2).",
        'nom: "frais fictifs de démonstration"',
        "trading_costs:",
        *(f"  {name}: {value}" for name, value in COSTS.items()),
    ]
    return "\n".join(lines) + "\n"


def build() -> dict[str, str]:
    """Every generated file, by name."""
    closes_at = session_closes()
    open_days = set(closes_at)
    known = actions(open_days)
    built = {s.instrument_id: series(s, open_days, known) for s in SPECS}
    rows = close_rows(built, closes_at, known)
    return {
        "instruments.csv": instruments_csv(),
        "cours.csv": _csv("date,identifiant,cloture,devise,publie_le", [r.text() for r in rows]),
        "operations.csv": actions_csv(known, built),
        "crises_fictives.yaml": crises_yaml(),
        "frais_fictifs.yaml": costs_yaml(),
    }


def main() -> None:
    for name, text in build().items():
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"{name} : {text.count(chr(10)) - 1} lignes")


if __name__ == "__main__":
    main()

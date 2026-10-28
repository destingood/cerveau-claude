"""Generate the synthetic market data of the fictitious reference portfolio (phase 2 plan, §4).

Every value is invented: fictitious instruments (``FICT-…``) and prices drawn from a fixed seed.
No provider's data is committed (redistribution rights, public opening in phase 8). Run it from
the repository root; it rewrites the CSV files next to it, and a test checks they still match:

    uv run python tests/fixtures/finance/reference/generate.py

Only ``random.Random(seed).random()`` is reproducible across Python versions, so the Gaussian
draws are computed here (Box–Muller) rather than with ``random.gauss``. A draw is taken on every
weekday, holiday or not, so that a calendar never shifts the stream of another day.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from core.finance.calendars import exchange_calendar, is_target_day, next_target_day

HERE = Path(__file__).resolve().parent
SEED = "cerveau-reference-2026"
FIRST, LAST = date(2023, 10, 16), date(2026, 10, 16)  # a Monday and a Friday: three years
# The fetch the files stand for (core.finance.fixtures): nothing published later is in them.
FETCHED_AT = datetime(2026, 10, 18, 12, 0, tzinfo=ZoneInfo("UTC"))
DAYS = 252
MARKET_VOL = 0.16  # annualised volatility of the market factor

# « Pourquoi la VaR a-t-elle augmenté depuis lundi ? » : from Tuesday 13 October 2026 the market
# log returns are set, and the idiosyncratic volatility is doubled all week.
STRESS_WEEK = (date(2026, 10, 12), LAST)
STRESS_MARKET = {
    date(2026, 10, 13): -0.026,
    date(2026, 10, 14): -0.034,
    date(2026, 10, 15): 0.022,
    date(2026, 10, 16): -0.029,
}
STRESS_IDIO = 2.0
# A bad print (the close times 1.22, the next one is right again) and a session without a close.
OUTLIER = ("FICT-BOREAL", date(2025, 11, 20), 1.22)
GAP = ("FICT-CYGNE", date(2026, 9, 16))


@dataclass(frozen=True)
class Spec:
    instrument_id: str
    name: str
    kind: str  # CSV class: action, etf, obligation, or
    currency: str
    mic: str
    sector: str
    country: str
    start: float  # first close, or the first yield of a bond
    drift: float  # annual
    beta: float  # to the market factor
    vol: float  # annual idiosyncratic volatility, or the yield's for a bond
    duration: float | None = None


# The bond is a zero coupon: its price is 100·exp(−y·τ), its duration τ (8.4 on 16 October 2026).
BOND_MATURITY = date(2035, 3, 12)
SPECS = (
    Spec("FICT-ACME", "Acme Industries (fictif)", "action", "EUR", "XPAR", "Industrie", "FR",
         84.0, 0.06, 1.1, 0.18),
    Spec("FICT-BOREAL", "Boréal Énergie (fictif)", "action", "EUR", "XETR", "Énergie", "DE",
         46.0, 0.04, 0.9, 0.20),
    Spec("FICT-CYGNE", "Cygne Santé (fictif)", "action", "EUR", "XPAR", "Santé", "FR",
         112.0, 0.05, 0.6, 0.15),
    Spec("FICT-DELTA", "Delta Banque (fictif)", "action", "EUR", "XPAR", "Finance", "FR",
         38.0, 0.03, 1.2, 0.17),
    Spec("FICT-GLOBEX", "Globex Systems (fictif)", "action", "USD", "XNYS", "Technologie", "US",
         150.0, 0.10, 1.3, 0.25),
    Spec("FICT-HELIOS", "Hélios Consumer (fictif)", "action", "GBP", "XLON", "Consommation", "GB",
         24.0, 0.04, 0.8, 0.16),
    Spec("FICT-MONDE", "ETF Actions Monde (fictif)", "etf", "EUR", "XPAR", "Actions monde", "IE",
         85.0, 0.08, 1.0, 0.02),
    Spec("FICT-EMERG", "ETF Émergents (fictif)", "etf", "USD", "XNYS", "Actions émergentes", "US",
         41.0, 0.05, 0.9, 0.12),
    Spec("FICT-OAT35", "OAT zéro coupon mars 2035 (fictive)", "obligation", "EUR", "XPAR",
         "Souverain", "FR", 0.0305, 0.0, 0.0, 0.007, duration=8.4),
    Spec("FICT-OR", "Or physique (fictif)", "or", "EUR", "XETR", "Matières premières", "DE",
         60.0, 0.09, 0.0, 0.14),
)  # fmt: skip


@dataclass(frozen=True)
class Action:
    instrument_id: str
    ex_date: date
    kind: str  # CSV type: split, dividende
    value: float
    announced: date | None = None  # none: dated at 00:00 in Paris on the ex-date (ADR-017)


def _quarterly(first: date, count: int, value: float, notice: int) -> list[Action]:
    """GLOBEX pays every thirteen weeks, on a Thursday, declared ``notice`` days before."""
    days = (first + timedelta(weeks=13 * n) for n in range(count))
    return [Action("FICT-GLOBEX", d, "dividende", value, d - timedelta(days=notice)) for d in days]


ACTIONS = sorted(
    [
        # ACME: an annual dividend, and a 2-for-1 split announced four weeks before.
        Action("FICT-ACME", date(2024, 5, 15), "dividende", 1.80, date(2024, 4, 10)),
        Action("FICT-ACME", date(2025, 5, 14), "dividende", 1.95, date(2025, 4, 9)),
        Action("FICT-ACME", date(2025, 6, 16), "split", 2.0, date(2025, 5, 20)),
        Action("FICT-ACME", date(2026, 5, 13), "dividende", 1.05, date(2026, 4, 8)),
        # BOREAL: no announcement date, so known from the ex-date only.
        Action("FICT-BOREAL", date(2024, 4, 25), "dividende", 2.10),
        Action("FICT-BOREAL", date(2025, 4, 24), "dividende", 2.20),
        Action("FICT-BOREAL", date(2026, 4, 23), "dividende", 2.30),
        Action("FICT-CYGNE", date(2024, 6, 5), "dividende", 3.00, date(2024, 5, 2)),
        Action("FICT-CYGNE", date(2025, 6, 4), "dividende", 3.10, date(2025, 5, 2)),
        Action("FICT-CYGNE", date(2026, 6, 3), "dividende", 3.20, date(2026, 5, 4)),
        Action("FICT-DELTA", date(2024, 5, 22), "dividende", 2.40, date(2024, 4, 24)),
        Action("FICT-DELTA", date(2025, 5, 21), "dividende", 2.50, date(2025, 4, 23)),
        Action("FICT-DELTA", date(2026, 5, 20), "dividende", 2.60, date(2026, 4, 22)),
        *_quarterly(date(2023, 11, 9), 5, 0.60, notice=21),
        *_quarterly(date(2025, 2, 6), 7, 0.65, notice=21),
        *(
            Action("FICT-HELIOS", d, "dividende", 0.45)
            for d in (date(2024, 3, 14), date(2024, 9, 12), date(2025, 3, 13))
        ),
        *(
            Action("FICT-HELIOS", d, "dividende", 0.48)
            for d in (date(2025, 9, 11), date(2026, 3, 12), date(2026, 9, 10))
        ),
        *(
            Action("FICT-EMERG", d, "dividende", 0.55, d - timedelta(days=7))
            for d in (date(2023, 12, 18), date(2024, 12, 17), date(2025, 12, 16))
        ),
    ],
    key=lambda a: (a.instrument_id, a.ex_date, a.kind),
)

FX = (("USD", 1.0600, 0.07, 4), ("GBP", 0.8700, 0.05, 5))  # start, annual volatility, decimals
# A fictitious €STR path (in %): its level from each date on, plus a small daily noise.
ESTR_STEPS = (
    (FIRST, 3.90),
    (date(2024, 7, 1), 3.65),
    (date(2024, 10, 1), 3.40),
    (date(2025, 1, 2), 3.15),
    (date(2025, 4, 1), 2.90),
    (date(2025, 7, 1), 2.65),
    (date(2026, 1, 2), 2.40),
)
ESTR_NOISE = 0.003
FRANKFURT = ZoneInfo("Europe/Berlin")


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


def sessions(mic: str) -> set[date]:
    calendar = exchange_calendar(mic, FIRST.year, LAST.year)
    if calendar is None:
        raise ValueError(f"{mic} : calendrier inconnu")
    return {s.date() for s in calendar.sessions_in_range(FIRST.isoformat(), LAST.isoformat())}


def market_returns() -> dict[date, float]:
    rng = _stream("marche")
    daily = MARKET_VOL / math.sqrt(DAYS)
    returns = {day: daily * normal(rng) for day in weekdays()}
    return returns | STRESS_MARKET


def _idio_scale(day: date) -> float:
    return STRESS_IDIO if STRESS_WEEK[0] <= day <= STRESS_WEEK[1] else 1.0


def stock_closes(spec: Spec, market: dict[date, float]) -> dict[date, float]:
    """Log returns accumulated over the weekdays since the previous session; a split divides
    the previous close and a dividend is taken from it on the ex-date."""
    rng = _stream(spec.instrument_id)
    open_days = sessions(spec.mic)
    actions = {a.ex_date: a for a in ACTIONS if a.instrument_id == spec.instrument_id}
    if not set(actions) <= open_days:
        raise ValueError(f"{spec.instrument_id} : une date ex hors séance")
    daily = spec.vol / math.sqrt(DAYS)
    closes: dict[date, float] = {}
    price, pending = spec.start, 0.0
    for day in weekdays():
        shock = normal(rng)
        pending += spec.drift / DAYS + spec.beta * market[day] + _idio_scale(day) * daily * shock
        if day not in open_days:
            continue
        if closes:
            action = actions.get(day)
            if action is not None:
                price = price / action.value if action.kind == "split" else price - action.value
            price *= math.exp(pending)
        closes[day], pending = price, 0.0
    return closes


def bond_closes(spec: Spec) -> dict[date, float]:
    """A zero coupon priced on its yield, a random walk: 100·exp(−y·τ), τ in years to maturity."""
    rng = _stream(spec.instrument_id)
    open_days = sessions(spec.mic)
    daily = spec.vol / math.sqrt(DAYS)
    closes: dict[date, float] = {}
    rate = spec.start
    for day in weekdays():
        shock = normal(rng)
        if day > FIRST:
            rate += daily * shock
        if day in open_days:
            years = (BOND_MATURITY - day).days / 365.25
            closes[day] = 100.0 * math.exp(-rate * years)
    return closes


def fx_rates(currency: str, start: float, vol: float) -> dict[date, float]:
    """Units of ``currency`` per euro on TARGET days, the ECB's convention."""
    rng = _stream(f"change:{currency}")
    daily = vol / math.sqrt(DAYS)
    rates: dict[date, float] = {}
    rate, pending = start, 0.0
    for day in weekdays():
        pending += daily * normal(rng)
        if not is_target_day(day):
            continue
        if rates:
            rate *= math.exp(pending)
        rates[day], pending = rate, 0.0
    return rates


def estr() -> dict[date, float]:
    """Only the observations published by the fetch: the €STR of a day comes out the next
    TARGET day at 08:00 in Frankfurt (ADR-017), so Friday 16 October is not known on Sunday."""
    rng = _stream("estr")
    values: dict[date, float] = {}
    for day in weekdays():
        noise = ESTR_NOISE * normal(rng)
        published = datetime.combine(next_target_day(day), time(8), tzinfo=FRANKFURT)
        if not is_target_day(day) or published > FETCHED_AT:
            continue
        level = next(v for start, v in reversed(ESTR_STEPS) if start <= day)
        values[day] = level + noise
    return values


def _csv(header: str, rows: list[str]) -> str:
    return "\n".join([header, *rows]) + "\n"


def instruments_csv() -> str:
    rows = [
        ",".join(
            [
                s.instrument_id,
                s.name,
                s.kind,
                s.currency,
                s.mic,
                s.sector,
                s.country,
                FIRST.isoformat(),
                "" if s.duration is None else f"{s.duration}",
            ]
        )
        for s in SPECS
    ]
    return _csv("identifiant,nom,classe,devise,place,secteur,pays,debut,duration", rows)


def all_closes() -> dict[str, dict[date, float]]:
    """Every instrument's closes, before the bad print and the gap are put in the file."""
    market = market_returns()
    return {
        s.instrument_id: bond_closes(s) if s.kind == "obligation" else stock_closes(s, market)
        for s in SPECS
    }


def closes_csv(closes: dict[str, dict[date, float]]) -> str:
    rows = []
    for spec in SPECS:
        for day, close in closes[spec.instrument_id].items():
            if (spec.instrument_id, day) == GAP:
                continue
            if (spec.instrument_id, day) == OUTLIER[:2]:
                close *= OUTLIER[2]
            rows.append(f"{day.isoformat()},{spec.instrument_id},{close:.2f},{spec.currency}")
    return _csv("date,identifiant,cloture,devise", rows)


def actions_csv() -> str:
    currency = {s.instrument_id: s.currency for s in SPECS}
    rows = [
        ",".join(
            [
                a.ex_date.isoformat(),
                a.instrument_id,
                a.kind,
                f"{a.value:.2f}",
                currency[a.instrument_id] if a.kind == "dividende" else "",
                a.announced.isoformat() if a.announced else "",
            ]
        )
        for a in ACTIONS
    ]
    return _csv("date_ex,identifiant,type,valeur,devise,date_annonce", rows)


def ecb_fx_csv() -> str:
    """The ECB's ``csvdata`` layout (EXR flow), as ``EcbProvider`` reads it."""
    rows = []
    for currency, start, vol, decimals in FX:
        for day, rate in fx_rates(currency, start, vol).items():
            key = f"EXR.D.{currency}.EUR.SP00.A"
            rows.append(f"{key},D,{currency},EUR,SP00,A,{day.isoformat()},{rate:.{decimals}f}")
    return _csv("KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE", rows)


def ecb_estr_csv() -> str:
    rows = [f"EST.B.EU000A2X2A25.WT,B,{d.isoformat()},{v:.3f}" for d, v in estr().items()]
    return _csv("KEY,FREQ,TIME_PERIOD,OBS_VALUE", rows)


# The portfolio ---------------------------------------------------------------------------------

PEA, CTO = "PEA-FICTIF", "CTO-FICTIF"
ORDER_FEES = {"EUR": Decimal("4.90"), "USD": Decimal("1.00"), "GBP": Decimal("3.00")}
WITHHOLDING = {"USD": Decimal("0.15")}  # a fictitious rate withheld at source
PAYMENT_DELAY = timedelta(days=14)  # a dividend is paid about two weeks after its ex-date
CENT = Decimal("0.01")
TRANSACTIONS_HEADER = "date,compte,type,identifiant,quantite,prix,devise,frais,montant,libelle"
STATEMENT_HEADER = "date,compte,nature,identifiant,quantite"
Balances = dict[tuple[str, str], Decimal]  # (account, currency) -> cash


@dataclass(frozen=True)
class Trade:
    """One line of ``transactions.csv``; amounts are in ``currency``."""

    day: date
    account: str
    kind: str  # CSV type
    asset: str  # the instrument, the currency bought, or empty
    quantity: Decimal
    currency: str = "EUR"
    price: Decimal | None = None
    fees: Decimal = Decimal(0)
    amount: Decimal | None = None  # the cash the broker debited
    label: str = ""

    def row(self) -> str:
        def text(value: Decimal | None) -> str:
            return "" if value is None else f"{value:f}"

        fees = text(self.fees) if self.fees else ""
        return ",".join(
            [
                self.day.isoformat(),
                self.account,
                self.kind,
                self.asset,
                text(self.quantity),
                text(self.price),
                self.currency,
                fees,
                text(self.amount),
                self.label,
            ]
        )

    def flows(self) -> list[tuple[tuple[str, str], Decimal]]:
        """The cash it moves, by (account, currency); positive when cash comes in."""
        own = (self.account, self.currency)
        gross = self.quantity if self.price is None else self.quantity * self.price
        if self.kind in ("achat", "change"):
            debit = self.amount if self.amount is not None else gross + self.fees
            bought = [((self.account, self.asset), self.quantity)] if self.kind == "change" else []
            return [(own, -debit), *bought]
        inflow = {"vente": gross - self.fees, "dividende": gross - self.fees, "depot": gross}
        return [(own, inflow.get(self.kind, -gross))]  # frais, retrait: cash out


def orders(closes: dict[str, dict[date, float]]) -> list[Trade]:
    """Every transaction but the dividends, in trade order; shares trade at the day's close."""
    currencies = {s.instrument_id: s.currency for s in SPECS}

    def at_close(day: date, account: str, kind: str, instrument_id: str, units: int) -> Trade:
        if day not in closes[instrument_id]:
            raise ValueError(f"{instrument_id} : pas de séance le {day}")
        price = Decimal(f"{closes[instrument_id][day]:.2f}")
        currency = currencies[instrument_id]
        fees = ORDER_FEES[currency]
        return Trade(day, account, kind, instrument_id, Decimal(units), currency, price, fees)

    def exchange(day: date, account: str, bought: str, amount: str) -> Trade:
        """Euros changed at the ECB rate of the day as published; the broker rounds the debit."""
        _, start, vol, decimals = next(fx for fx in FX if fx[0] == bought)
        rate = Decimal(f"{fx_rates(bought, start, vol)[day]:.{decimals}f}")
        price = (1 / rate).quantize(Decimal("0.000001"))
        debit = (Decimal(amount) / rate).quantize(CENT)
        return Trade(day, account, "change", bought, Decimal(amount), price=price, amount=debit)

    def cash(day: date, account: str, kind: str, amount: str, label: str) -> Trade:
        return Trade(day, account, kind, "", Decimal(amount), label=label)

    pea = (("FICT-ACME", 100), ("FICT-BOREAL", 150), ("FICT-CYGNE", 80), ("FICT-DELTA", 200))
    cto = (("FICT-GLOBEX", 60), ("FICT-EMERG", 200), ("FICT-HELIOS", 180), ("FICT-OAT35", 100))
    return [
        cash(FIRST, PEA, "depot", "60000.00", "Versement initial (fictif)"),
        cash(FIRST, CTO, "depot", "45000.00", "Versement initial (fictif)"),
        *(at_close(date(2023, 10, 17), PEA, "achat", i, n) for i, n in pea),
        at_close(date(2023, 10, 17), PEA, "achat", "FICT-MONDE", 150),
        exchange(date(2023, 10, 17), CTO, "USD", "22000.00"),
        exchange(date(2023, 10, 17), CTO, "GBP", "5000.00"),
        *(at_close(date(2023, 10, 18), CTO, "achat", i, n) for i, n in cto),
        at_close(date(2023, 10, 18), CTO, "achat", "FICT-OR", 100),
        cash(date(2024, 12, 31), CTO, "frais", "30.00", "Droits de garde 2024 (fictifs)"),
        at_close(date(2025, 3, 10), PEA, "vente", "FICT-DELTA", 40),
        cash(date(2025, 12, 31), CTO, "frais", "30.00", "Droits de garde 2025 (fictifs)"),
        cash(date(2026, 3, 2), PEA, "depot", "2000.00", "Versement (fictif)"),
        at_close(date(2026, 3, 3), PEA, "achat", "FICT-MONDE", 20),
        cash(date(2026, 6, 15), CTO, "retrait", "1000.00", "Retrait (fictif)"),
        # « Pourquoi la VaR a-t-elle augmenté depuis lundi ? » : GLOBEX reinforced on Monday.
        at_close(date(2026, 10, 12), CTO, "achat", "FICT-GLOBEX", 20),
    ]


def units(trades: list[Trade], account: str, instrument_id: str, day: date) -> Decimal:
    """Shares held at the start of ``day``: each earlier trade times the splits since."""
    total = Decimal(0)
    for t in trades:
        if t.kind not in ("achat", "vente") or t.day >= day:
            continue
        if (t.account, t.asset) != (account, instrument_id):
            continue
        factor = math.prod(
            Decimal(int(a.value))
            for a in ACTIONS
            if a.kind == "split" and a.instrument_id == instrument_id and t.day < a.ex_date <= day
        )
        total += (t.quantity if t.kind == "achat" else -t.quantity) * factor
    return total


def dividends(trades: list[Trade]) -> list[Trade]:
    """Each dividend received on the shares held at its ex-date, withholding deducted."""
    currencies = {s.instrument_id: s.currency for s in SPECS}
    paid = []
    for action in ACTIONS:
        payment = action.ex_date + PAYMENT_DELAY
        while not is_target_day(payment):  # paid on a TARGET business day
            payment += timedelta(days=1)
        if action.kind != "dividende" or payment > LAST:
            continue
        currency = currencies[action.instrument_id]
        for account in (PEA, CTO):
            held = units(trades, account, action.instrument_id, action.ex_date)
            if not held:
                continue
            gross = (Decimal(f"{action.value:.2f}") * held).quantize(CENT)
            withheld = (gross * WITHHOLDING.get(currency, Decimal(0))).quantize(CENT)
            paid.append(
                Trade(
                    payment,
                    account,
                    "dividende",
                    action.instrument_id,
                    gross,
                    currency,
                    None,
                    withheld,
                )
            )
    return paid


def transactions(closes: dict[str, dict[date, float]]) -> list[Trade]:
    """The ledger in trade order; within a day, the orders come before the dividends."""
    placed = orders(closes)
    return sorted([*placed, *dividends(placed)], key=lambda t: t.day)


def balances(trades: list[Trade]) -> Balances:
    """The cash of each account and currency, never negative along the way."""
    cash: Balances = {}
    for t in trades:
        for key, flow in t.flows():
            cash[key] = cash.get(key, Decimal(0)) + flow
            if cash[key] < 0:
                raise ValueError(f"{t.day} : cash négatif sur {key}")
    return cash


def statement(trades: list[Trade]) -> list[str]:
    """The broker's statement on the last day: shares, then cash, account by account."""
    rows = []
    cash = balances(trades)
    for account in (PEA, CTO):
        held = sorted({t.asset for t in trades if t.account == account and t.kind == "achat"})
        for instrument_id in held:
            quantity = units(trades, account, instrument_id, LAST + timedelta(days=1))
            if quantity < 0:
                raise ValueError(f"{instrument_id} : vente à découvert")
            if quantity:
                rows.append(f"{LAST.isoformat()},{account},titre,{instrument_id},{quantity:f}")
        for (owner, currency), balance in sorted(cash.items()):
            if owner == account and balance:
                rows.append(f"{LAST.isoformat()},{account},especes,{currency},{balance:f}")
    return rows


def build() -> dict[str, str]:
    """Every generated file, by name."""
    closes = all_closes()
    trades = transactions(closes)
    return {
        "instruments.csv": instruments_csv(),
        "cours.csv": closes_csv(closes),
        "operations.csv": actions_csv(),
        "bce_change.csv": ecb_fx_csv(),
        "bce_estr.csv": ecb_estr_csv(),
        "transactions.csv": _csv(TRANSACTIONS_HEADER, [t.row() for t in trades]),
        "releve.csv": _csv(STATEMENT_HEADER, statement(trades)),
    }


def main() -> None:
    for name, text in build().items():
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"{name} : {text.count(chr(10)) - 1} lignes")


if __name__ == "__main__":
    main()

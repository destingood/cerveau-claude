from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config.loader import ExecutionConfig, PaperRiskLimits, TradingCosts
from core.execution.broker import AckCode, BrokerAdapter
from core.execution.intent import OrderIntent
from core.execution.paper import (
    MONEY_MAX,
    PaperCosts,
    PaperSettings,
    PaperSimulator,
    SessionBar,
    SimulatorError,
    default_simulator_path,
    next_exchange_session,
)
from core.execution.states import ExecutionIncident
from core.finance.model import PARIS, utc_text
from tests.execution_cases import FILLED_AT, SESSION, make_intent
from tests.test_execution_intent import INJECTION

CAPITAL = Decimal("10000.00")
COSTS = PaperCosts(Decimal("0.10"), Decimal("2.00"), Decimal(5))
SETTINGS = PaperSettings(CAPITAL, COSTS, Decimal(5))
OPENED = datetime(2026, 10, 17, 9, 0, tzinfo=PARIS)
SUBMITTED = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)  # the example intent is from 14:05
CLOSED = datetime(2026, 10, 19, 18, 0, tzinfo=PARIS)  # after the close published at 17:35
TUESDAY = date(2026, 10, 20)


def weekdays(mic: str, day: date) -> date:
    """A calendar without holidays for XPAR, and no other exchange."""
    if mic != "XPAR":
        raise SimulatorError(f"calendrier inconnu pour la place {mic}")
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def bar(**changes: Any) -> SessionBar:
    data: dict[str, Any] = {
        "symbol": "FICT-ACME",
        "session": SESSION,
        "close": Decimal("123.00"),
        "volume": 1000,
        "currency": "EUR",
        "published_at": FILLED_AT,
    } | changes
    return SessionBar.model_validate(data)


class Market:
    def __init__(self, *bars: SessionBar) -> None:
        self.bars = {(b.symbol, b.session): b for b in bars}

    def bar(self, symbol: str, session: date) -> SessionBar | None:
        return self.bars.get((symbol, session))


def simulator(paper: PaperSettings = SETTINGS) -> PaperSimulator:
    return PaperSimulator.memory(paper, now=OPENED, sessions=weekdays)


def sell(n: int, quantity: int = 10, **changes: Any) -> OrderIntent:
    """A sell decided on Monday evening, worked on Tuesday."""
    return make_intent(
        n,
        side="SELL",
        quantity=quantity,
        created_at=datetime(2026, 10, 19, 18, 30, tzinfo=PARIS),
        decision_date=SESSION,
        **changes,
    )


def tuesday(**changes: Any) -> SessionBar:
    return bar(session=TUESDAY, published_at=FILLED_AT + timedelta(days=1), **changes)


def holding(sim: PaperSimulator, quantity: int = 10) -> None:
    """Buy ``quantity`` shares on Monday's close."""
    assert sim.submit(make_intent(0, quantity=quantity), now=SUBMITTED).accepted
    report = sim.close_session(SESSION, Market(bar()), now=CLOSED)
    assert sum(fill.quantity for fill in report.fills) == quantity


# Costs and settings -----------------------------------------------------------------------------


def test_the_commission_is_the_rate_to_the_cent_half_up_or_the_minimum() -> None:
    assert COSTS.commission(Decimal("2005.00")) == Decimal("2.01")  # 2.005, half up
    assert COSTS.commission(Decimal("2004.99")) == Decimal("2.00")
    assert COSTS.commission(Decimal("100.00")) == Decimal("2.00")  # the minimum
    assert COSTS.commission(Decimal("12345.00")) == Decimal("12.35")


def test_the_fill_price_moves_against_the_order_to_the_cent() -> None:
    assert COSTS.fill_price("BUY", Decimal("123.00")) == Decimal("123.07")  # 123.0615
    assert COSTS.fill_price("BUY", Decimal("123.40")) == Decimal("123.47")  # 123.4617
    assert COSTS.fill_price("SELL", Decimal("124.00")) == Decimal("123.93")  # 123.938
    assert COSTS.fill_price("SELL", Decimal("123.50")) == Decimal("123.43")  # 123.43825


@pytest.mark.parametrize(
    ("commission", "minimum", "slippage", "message"),
    [
        (Decimal(100), Decimal(2), Decimal(5), "commission_pct"),
        (Decimal(-1), Decimal(2), Decimal(5), "commission_pct"),
        (Decimal("NaN"), Decimal(2), Decimal(5), "commission_pct"),
        (Decimal("0.1"), Decimal("-0.01"), Decimal(5), "min_commission_eur"),
        (Decimal("0.1"), Decimal("2.001"), Decimal(5), "min_commission_eur"),
        (Decimal("0.1"), Decimal("Infinity"), Decimal(5), "min_commission_eur"),
        (Decimal("0.1"), Decimal(2), Decimal(10_000), "slippage_bps"),
        (Decimal("0.1"), Decimal(2), Decimal(-1), "slippage_bps"),
    ],
)
def test_invalid_costs_are_refused(
    commission: Decimal, minimum: Decimal, slippage: Decimal, message: str
) -> None:
    with pytest.raises(SimulatorError, match=message):
        PaperCosts(commission, minimum, slippage)


@pytest.mark.parametrize(
    ("capital", "participation", "message"),
    [
        (Decimal(0), Decimal(5), "capital"),
        (Decimal("10000.001"), Decimal(5), "capital"),
        (MONEY_MAX + 1, Decimal(5), "capital"),
        (CAPITAL, Decimal(0), "participation"),
        (CAPITAL, Decimal("100.01"), "participation"),
        (CAPITAL, Decimal("NaN"), "participation"),
    ],
)
def test_invalid_settings_are_refused(
    capital: Decimal, participation: Decimal, message: str
) -> None:
    with pytest.raises(SimulatorError, match=message):
        PaperSettings(capital, COSTS, participation)


def costs_config(**changes: Any) -> TradingCosts:
    values: dict[str, Any] = {
        "commission_pct": Decimal("0.10"),
        "min_commission_eur": Decimal("2.00"),
        "slippage_bps": Decimal(5),
        "fx_conversion_bps": Decimal(10),
    } | changes
    return TradingCosts(**values)


def test_the_settings_come_from_the_config() -> None:
    limits = PaperRiskLimits.model_construct(capital_reference_eur=10000.0)
    execution = ExecutionConfig(limit_offset_pct=0.5, max_participation_pct=5.0)
    assert PaperSettings.from_config(limits, execution, costs_config()) == SETTINGS


def test_an_unknown_setting_refuses_the_paper_account() -> None:
    limits = PaperRiskLimits.model_construct(capital_reference_eur="A_DEFINIR")
    execution = ExecutionConfig(limit_offset_pct=0.5, max_participation_pct="A_DEFINIR")
    known = PaperRiskLimits.model_construct(capital_reference_eur=10000.0)
    with pytest.raises(SimulatorError, match="capital_reference_eur, max_participation_pct"):
        PaperSettings.from_config(limits, execution, costs_config())
    with pytest.raises(SimulatorError, match=r"^max_participation_pct à définir"):
        PaperSettings.from_config(known, execution, costs_config())
    unknown_fx = costs_config(fx_conversion_bps="A_VERIFIER", slippage_bps="A_DEFINIR")
    with pytest.raises(SimulatorError, match=r"fx_conversion_bps, slippage_bps à définir"):
        PaperCosts.from_config(unknown_fx)


# The account ------------------------------------------------------------------------------------


def test_the_simulator_is_a_broker_adapter_kept_in_var_paper(tmp_path: Path) -> None:
    assert default_simulator_path(tmp_path) == tmp_path / "var" / "paper" / "simulator.db"
    with simulator() as sim:
        assert isinstance(sim, BrokerAdapter)
        statement = sim.account_snapshot()
    assert (statement.cash_eur, statement.positions, statement.cursor) == (CAPITAL, {}, 0)


def test_a_buy_fills_at_the_next_close_with_slippage_and_fees() -> None:
    sim = simulator()
    ack = sim.submit(make_intent(0), now=SUBMITTED)
    assert (ack.accepted, ack.duplicate, ack.code) == (True, False, AckCode.ACCEPTE)
    assert ack.reason == "ordre accepté pour la séance du 2026-10-19"  # Saturday → Monday
    (order,) = sim.open_orders()
    assert (order.remaining, order.session, order.limit_price) == (10, SESSION, Decimal("123.45"))
    report = sim.close_session(SESSION, Market(bar()), now=CLOSED)
    (fill,) = report.fills
    assert report.expired == ()
    assert (fill.quantity, fill.price, fill.fees) == (10, Decimal("123.07"), Decimal("2.00"))
    assert fill.executed_at == FILLED_AT
    assert fill.fill_id == f"paper:{make_intent(0).intent_id.hex}:1"
    statement = sim.account_snapshot()
    assert statement.cash_eur == CAPITAL - Decimal("1230.70") - Decimal("2.00")
    assert statement.positions == {"FICT-ACME": 10}
    assert sim.open_orders() == ()


def test_a_sell_frees_the_position_and_brings_in_the_amount_less_fees() -> None:
    sim = simulator()
    holding(sim)
    cash = sim.account_snapshot().cash_eur
    assert sim.submit(sell(1, limit_price=Decimal("120.00")), now=CLOSED + timedelta(hours=1))
    report = sim.close_session(TUESDAY, Market(tuesday()), now=CLOSED + timedelta(days=1))
    (fill,) = report.fills
    assert fill.price == Decimal("122.93")  # 123 × (1 − 5 bps) = 122.9385, floored
    statement = sim.account_snapshot()
    assert statement.cash_eur == cash + Decimal("1229.30") - Decimal("2.00")
    assert statement.positions == {}


def test_a_session_fills_at_most_its_participation_and_cancels_the_rest() -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=SUBMITTED)
    report = sim.close_session(SESSION, Market(bar(volume=100)), now=CLOSED)
    assert [fill.quantity for fill in report.fills] == [5]  # 5 % of 100
    ((intent_id, why),) = report.expired
    assert intent_id == make_intent(0).intent_id
    assert why == "reste de 5 titres annulé en fin de séance (participation de 5 % du volume)"
    assert sim.open_orders() == ()


@pytest.mark.parametrize(
    ("market", "why"),
    [
        (Market(), "pas de cours de clôture de l'instrument pour la séance"),
        (Market(bar(symbol="FICT-OTHER")), "pas de cours de clôture"),
        (Market(bar(close=Decimal("123.46"))), "limite non atteinte à la clôture"),
        # 123.40 moved by 5 bps is 123.47: past the 123.45 limit, no fill at the limit
        (Market(bar(close=Decimal("123.40"))), "limite non atteinte à la clôture, glissement"),
        (Market(bar(volume=None)), "volume de la séance inconnu"),
        (Market(bar(volume=19)), "participation de 5 % du volume : aucun titre"),
        (Market(bar(currency="USD")), "cours dans une autre devise que l'ordre"),
    ],
)
def test_an_order_the_close_cannot_fill_expires_with_the_session(market: Market, why: str) -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=SUBMITTED)
    report = sim.close_session(SESSION, market, now=CLOSED)
    assert report.fills == ()
    ((_, reason),) = report.expired
    assert reason.startswith(why)
    assert reason.endswith(": ordre expiré")
    assert sim.open_orders() == ()
    assert sim.account_snapshot().cash_eur == CAPITAL


def test_sells_are_worked_before_buys() -> None:
    sim = simulator()
    holding(sim)
    buy = make_intent(
        2, created_at=datetime(2026, 10, 19, 18, 30, tzinfo=PARIS), decision_date=SESSION
    )
    later = CLOSED + timedelta(hours=1)
    assert sim.submit(buy, now=later).accepted
    assert sim.submit(sell(1, limit_price=Decimal("120.00")), now=later).accepted
    report = sim.close_session(TUESDAY, Market(tuesday()), now=CLOSED + timedelta(days=1))
    assert [fill.intent_id for fill in report.fills] == [sell(1).intent_id, buy.intent_id]


# Rejections -------------------------------------------------------------------------------------


OUTSIDE = AckCode.HORS_PERIMETRE


@pytest.mark.parametrize(
    ("intent", "now", "code", "reason"),
    [
        (make_intent(0), SUBMITTED - timedelta(minutes=6), OUTSIDE, "envoyé avant la création"),
        (make_intent(0, instrument__currency="USD"), SUBMITTED, OUTSIDE, "devise USD"),
        (make_intent(0, instrument__venue="XXXX"), SUBMITTED, OUTSIDE, "calendrier inconnu"),
        (
            make_intent(0, quantity=81),
            SUBMITTED,
            AckCode.CASH_INSUFFISANT,
            "cash libre insuffisant, frais compris",
        ),
        (
            sell(0),
            CLOSED + timedelta(hours=1),
            AckCode.POSITION_INSUFFISANTE,
            "position insuffisante : pas de vente à découvert",
        ),
        (
            make_intent(0, quantity=100_000_000, limit_price=Decimal("100.00")),
            SUBMITTED,
            OUTSIDE,
            "montant au-delà de MONEY_MAX",
        ),
    ],
)
def test_an_order_beyond_the_account_is_rejected_and_kept(
    intent: OrderIntent, now: datetime, code: AckCode, reason: str
) -> None:
    sim = simulator()
    ack = sim.submit(intent, now=now)
    assert (ack.accepted, ack.duplicate, ack.code) == (False, False, code)
    assert ack.reason.startswith(reason)
    again = sim.submit(intent, now=now)
    assert (again.accepted, again.duplicate, again.reason) == (False, True, ack.reason)
    assert again.code == AckCode.DEJA_RECU
    assert sim.open_orders() == ()


def test_the_cash_kept_for_working_orders_is_not_free() -> None:
    sim = simulator()
    assert sim.submit(make_intent(0, quantity=40), now=SUBMITTED).accepted  # 4 938 € + 4.94 €
    assert sim.submit(make_intent(1, quantity=40), now=SUBMITTED).accepted
    ack = sim.submit(make_intent(2, quantity=1), now=SUBMITTED)
    assert ack.reason.startswith("cash libre insuffisant")


def test_a_sell_counts_the_sells_still_working() -> None:
    sim = simulator()
    holding(sim)
    later = CLOSED + timedelta(hours=1)
    assert sim.submit(sell(1, quantity=6), now=later).accepted
    assert sim.submit(sell(2, quantity=5), now=later).reason.startswith("position insuffisante")
    assert sim.submit(sell(3, quantity=4), now=later).accepted


def test_an_intent_id_is_received_once() -> None:
    sim = simulator()
    first = sim.submit(make_intent(0), now=SUBMITTED)
    again = sim.submit(make_intent(0), now=SUBMITTED + timedelta(minutes=1))
    assert (again.accepted, again.duplicate, again.code) == (True, True, AckCode.DEJA_RECU)
    assert again.reason == "ordre déjà reçu : aucun second ordre"
    other = sim.submit(make_intent(0, quantity=9), now=SUBMITTED)
    assert (other.accepted, other.duplicate, other.code) == (False, True, AckCode.AUTRE_CONTENU)
    assert other.reason == "intent_id déjà reçu avec un autre contenu"
    assert first.accepted
    assert len(sim.open_orders()) == 1


# Sessions ---------------------------------------------------------------------------------------


def test_a_session_closes_once_and_in_order() -> None:
    sim = simulator()
    sim.close_session(TUESDAY, Market(), now=CLOSED + timedelta(days=1))
    for session in (TUESDAY, SESSION):
        with pytest.raises(SimulatorError, match="déjà close"):
            sim.close_session(session, Market(), now=CLOSED + timedelta(days=1))
    ack = sim.submit(make_intent(0), now=SUBMITTED)
    assert ack.reason == f"séance du {SESSION} déjà close"
    assert ack.code == AckCode.SEANCE_CLOSE


def test_an_order_of_a_session_never_closed_expires_with_a_later_one() -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=SUBMITTED)
    report = sim.close_session(TUESDAY, Market(tuesday()), now=CLOSED + timedelta(days=1))
    assert report.expired == (
        (make_intent(0).intent_id, f"séance du {SESSION} jamais traitée : ordre expiré"),
    )


def test_a_close_published_after_now_refuses_the_whole_session() -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=SUBMITTED)
    with pytest.raises(
        SimulatorError, match=r"publiée après maintenant : séance non close \(R10\)"
    ):
        sim.close_session(SESSION, Market(bar()), now=FILLED_AT - timedelta(minutes=1))
    assert len(sim.open_orders()) == 1
    assert len(sim.close_session(SESSION, Market(bar()), now=CLOSED).fills) == 1


def test_an_order_received_after_its_close_is_never_filled() -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=FILLED_AT)
    report = sim.close_session(SESSION, Market(bar()), now=CLOSED)
    assert report.expired[0][1].startswith("ordre reçu après la clôture de sa séance (R10)")


def test_a_fill_beyond_money_max_expires() -> None:
    sim = simulator()
    holding(sim)
    sim.submit(sell(1, limit_price=Decimal("1.00")), now=CLOSED + timedelta(hours=1))
    market = Market(tuesday(close=Decimal(1_000_000_000)))
    report = sim.close_session(TUESDAY, market, now=CLOSED + timedelta(days=1))
    assert report.expired[0][1].startswith("montant au-delà de MONEY_MAX")


def test_costs_grown_since_the_order_expire_it_rather_than_borrow(tmp_path: Path) -> None:
    path = tmp_path / "simulator.db"
    with PaperSimulator.open(path, SETTINGS, now=OPENED, sessions=weekdays) as sim:
        assert sim.submit(make_intent(0, quantity=80), now=SUBMITTED).accepted
    dearer = PaperSettings(CAPITAL, PaperCosts(Decimal(5), Decimal(2), Decimal(5)), Decimal(5))
    with PaperSimulator.open(path, dearer, now=CLOSED, sessions=weekdays) as sim:
        report = sim.close_session(SESSION, Market(bar(volume=10_000)), now=CLOSED)
        assert report.expired[0][1].startswith("cash insuffisant à l'exécution")
        assert sim.account_snapshot().cash_eur == CAPITAL


def test_the_account_keeps_its_capital(tmp_path: Path) -> None:
    path = tmp_path / "var" / "paper" / "simulator.db"
    PaperSimulator.open(path, SETTINGS, now=OPENED).close()
    other = PaperSettings(Decimal(20_000), COSTS, Decimal(5))
    with pytest.raises(SimulatorError, match="ouvrir un nouveau compte"):
        PaperSimulator.open(path, other, now=OPENED)


# Cancellations ----------------------------------------------------------------------------------


def test_a_cancel_frees_the_rest_of_a_working_order_once() -> None:
    sim = simulator()
    sim.submit(make_intent(0), now=SUBMITTED)
    intent_id = make_intent(0).intent_id
    assert sim.cancel(intent_id, reason="demande de l'utilisateur", now=SUBMITTED)
    assert not sim.cancel(intent_id, reason="demande de l'utilisateur", now=SUBMITTED)
    assert not sim.cancel(make_intent(9).intent_id, reason="inconnu", now=SUBMITTED)
    assert sim.open_orders() == ()
    assert sim.close_session(SESSION, Market(bar()), now=CLOSED).fills == ()


def test_cancel_all_cancels_every_working_order() -> None:
    sim = simulator()
    for n in range(3):
        sim.submit(make_intent(n, quantity=5), now=SUBMITTED)
    cancelled = sim.cancel_all(reason="kill switch", now=SUBMITTED)
    assert cancelled == tuple(make_intent(n).intent_id for n in range(3))
    assert sim.cancel_all(reason="kill switch", now=SUBMITTED) == ()


@pytest.mark.parametrize("reason", ["", "x" * 201, "ligne\nsuivante", INJECTION])
def test_a_cancel_reason_must_be_plain_short_text(reason: str) -> None:
    sim = simulator()
    with pytest.raises(SimulatorError, match="raison"):
        sim.cancel(make_intent(0).intent_id, reason=reason, now=SUBMITTED)
    with pytest.raises(SimulatorError, match="raison"):
        sim.cancel_all(reason=reason, now=SUBMITTED)


# Fills and integrity ----------------------------------------------------------------------------


def test_fills_are_read_after_a_cursor() -> None:
    sim = simulator()
    holding(sim)
    batch = sim.fills_since(0)
    assert [fill.quantity for fill in batch.fills] == [10]
    assert sim.fills_since(batch.cursor).fills == ()
    assert sim.fills_since(batch.cursor).cursor == batch.cursor
    with pytest.raises(SimulatorError, match="curseur négatif"):
        sim.fills_since(-1)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE account SET capital_eur = '1'",
        "DELETE FROM orders",
        "DELETE FROM rejections",
        "UPDATE sessions SET closed_at = ''",
        "DELETE FROM events",
    ],
)
def test_the_simulator_only_grows(statement: str) -> None:
    sim = simulator()
    holding(sim)
    sim.submit(sell(1, quantity=11), now=CLOSED + timedelta(hours=1))
    with pytest.raises(sqlite3.IntegrityError, match="ne se"):
        sim._conn.execute(statement)


def test_an_altered_order_or_fill_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "simulator.db"
    with PaperSimulator.open(path, SETTINGS, now=OPENED, sessions=weekdays) as sim:
        holding(sim)
    raw = sqlite3.connect(path, autocommit=True)
    raw.execute("DROP TRIGGER events_no_update")
    raw.execute("""UPDATE events SET fill = replace(fill, '"quantity":10', '"quantity":9')""")
    with (
        PaperSimulator.open(path, SETTINGS, now=OPENED) as sim,
        pytest.raises(ExecutionIncident, match="empreinte"),
    ):
        sim.fills_since(0)
    raw.execute("DROP TRIGGER orders_no_update")
    raw.execute("""UPDATE orders SET intent = replace(intent, '"quantity":10', '"quantity":9')""")
    raw.close()
    with (
        PaperSimulator.open(path, SETTINGS, now=OPENED) as sim,
        pytest.raises(ExecutionIncident, match="empreinte") as caught,
    ):
        sim.open_orders()
    assert caught.value.intent_id == make_intent(0).intent_id


def test_a_sell_beyond_the_position_is_an_incident_and_closes_nothing() -> None:
    sim = simulator()
    holding(sim)
    intent = sell(1, quantity=11, limit_price=Decimal("120.00"))
    sim._conn.execute(  # an order that skipped the checks of submit
        "INSERT INTO orders VALUES (?, ?, ?, 'FICT-ACME', 'SELL', 11, ?, ?)",
        (
            str(intent.intent_id),
            intent.sha256(),
            intent.model_dump_json(),
            str(TUESDAY),
            utc_text(CLOSED),
        ),
    )
    with pytest.raises(ExecutionIncident, match="au-delà de la position") as caught:
        sim.close_session(TUESDAY, Market(tuesday()), now=CLOSED + timedelta(days=1))
    assert caught.value.kind == "execution_incoherente"
    assert len(sim.open_orders()) == 1


def test_a_write_the_database_refuses_is_an_incident() -> None:
    sim = simulator()
    holding(sim)
    with pytest.raises(ExecutionIncident) as caught, sim._write():
        sim._conn.execute("INSERT INTO sessions VALUES (?, 'x')", (str(SESSION),))
    # The simulator stands for the broker: its type only, never its text (B197).
    assert str(caught.value) == "le simulateur refuse l'écriture : IntegrityError"
    assert sim.account_snapshot().positions == {"FICT-ACME": 10}


def test_the_next_session_comes_from_the_exchange_calendar() -> None:
    assert next_exchange_session("XPAR", date(2026, 10, 16)) == SESSION  # Friday → Monday
    assert next_exchange_session("XPAR", date(2026, 12, 31)) == date(2027, 1, 4)
    with pytest.raises(SimulatorError, match="calendrier inconnu pour la place XXXX"):
        next_exchange_session("XXXX", SESSION)


# Properties -------------------------------------------------------------------------------------


def cents_half_up(value: Fraction) -> Fraction:
    return Fraction(math.floor(value * 100 + Fraction(1, 2)), 100)


ORDERS = st.lists(
    st.tuples(
        st.sampled_from(["BUY", "SELL"]),
        st.integers(1, 120),
        st.integers(5_000, 15_000),  # the limit, in cents
    ),
    max_size=4,
)
BARS = st.tuples(
    st.integers(50_000_000, 150_000_000),  # the close, in millionths
    st.one_of(st.none(), st.integers(0, 3_000)),
)
SESSIONS = (SESSION, TUESDAY, date(2026, 10, 21))


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(ORDERS, BARS), min_size=3, max_size=3))
def test_the_account_never_borrows_and_matches_an_exact_oracle(
    plan: list[tuple[list[tuple[str, int, int]], tuple[int, int | None]]],
) -> None:
    sim = simulator()
    intents: dict[Any, OrderIntent] = {}
    cash, held = Fraction(CAPITAL), 0
    decided = [datetime(2026, 10, 17, 18, 30, tzinfo=PARIS)]
    decided += [datetime(s.year, s.month, s.day, 18, 30, tzinfo=PARIS) for s in SESSIONS[:-1]]
    for (orders, (close, volume)), session, at in zip(plan, SESSIONS, decided, strict=True):
        for side, quantity, limit in orders:
            intent = make_intent(
                len(intents),
                side=side,
                quantity=quantity,
                limit_price=Decimal(limit).scaleb(-2),
                created_at=at,
                decision_date=at.date(),
            )
            intents[intent.intent_id] = intent
            sim.submit(intent, now=at + timedelta(minutes=1))
        published = datetime(session.year, session.month, session.day, 17, 35, tzinfo=PARIS)
        price = Decimal(close).scaleb(-6)
        market = Market(bar(session=session, close=price, volume=volume, published_at=published))
        report = sim.close_session(session, market, now=published + timedelta(minutes=25))
        for fill in report.fills:
            intent = intents[fill.intent_id]
            assert volume is not None
            assert fill.quantity <= volume * 5 // 100
            amount = Fraction(fill.quantity) * Fraction(fill.price)
            assert Fraction(fill.fees) == max(Fraction(2), cents_half_up(amount / 1000))
            moved = Fraction(price) * Fraction(10_005 if intent.side == "BUY" else 9_995, 10_000)
            if intent.side == "BUY":
                expected = min(Fraction(math.ceil(moved * 100), 100), Fraction(intent.limit_price))
                cash -= amount + Fraction(fill.fees)
                held += fill.quantity
            else:
                expected = max(Fraction(math.floor(moved * 100), 100), Fraction(intent.limit_price))
                cash += amount - Fraction(fill.fees)
                held -= fill.quantity
            assert Fraction(fill.price) == expected
        statement = sim.account_snapshot()
        assert Fraction(statement.cash_eur) == cash
        assert cash >= 0
        assert statement.positions == ({"FICT-ACME": held} if held else {})
        assert held >= 0

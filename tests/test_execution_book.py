from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.audit.chain import AuditJournal, verify
from core.execution.book import (
    LATEST_VERSION,
    BookedOrder,
    OrderBook,
    OrderBookError,
    default_book_path,
    slippage_bps,
)
from core.execution.intent import OrderIntent
from core.execution.states import TRANSITIONS, ExecutionIncident, OrderState
from core.finance.model import PARIS
from core.finance.schema import SchemaError
from tests.execution_cases import (
    BOOKED_AT,
    DECISION_PRICE,
    MemoryJournal,
    make_fill,
    make_intent,
    recorder,
)
from tests.test_execution_intent import INJECTION

S = OrderState
AMOUNT_KEYS = {"quantity", "price", "limit_price", "fees", "notional", "decision_price"}


def sent(book: OrderBook, intent: OrderIntent) -> None:
    book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
    book.transition(intent.intent_id, S.VALIDEE, reason="Porte de risque : ACCEPT")
    book.transition(intent.intent_id, S.ENVOYEE, reason="soumis au simulateur")


def journal_payloads(journal: AuditJournal) -> list[dict[str, Any]]:
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    assert {entry["event"] for entry in entries} == {"ORDER_STATE"}
    return [journal.read_payload(entry["payload_ref"]) for entry in entries]


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit" / "journal.jsonl")


@pytest.fixture
def book_path(tmp_path: Path) -> Path:
    return default_book_path(tmp_path)


def test_the_book_lives_in_var_paper(tmp_path: Path) -> None:
    assert default_book_path(tmp_path) == tmp_path / "var" / "paper" / "orders.db"


def test_the_database_holds_the_state_machine_of_adr_032(book_path: Path) -> None:
    with OrderBook.open(book_path) as book:
        assert book.schema_version == LATEST_VERSION
    conn = sqlite3.connect(book_path)
    rows = set(conn.execute("SELECT from_state, to_state FROM allowed_transitions"))
    conn.close()
    expected = {(a.value, b.value) for a, targets in TRANSITIONS.items() for b in targets}
    assert rows == {("", "INTENTION"), *expected}


def test_an_order_reaches_executee_through_its_fills_and_journals_each_step(
    book_path: Path, journal: AuditJournal
) -> None:
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(journal)) as book:
        sent(book, intent)
        assert book.record_fill(make_fill(intent, 1, 4), now=BOOKED_AT) == S.PARTIELLE
        assert book.record_fill(make_fill(intent, 2, 6), now=BOOKED_AT) == S.EXECUTEE
        order = book.order(intent.intent_id)
    assert (order.state, order.filled, order.remaining) == (S.EXECUTEE, 10, 0)
    assert order.decision_price == DECISION_PRICE
    payloads = journal_payloads(journal)
    assert [p["state"] for p in payloads] == [
        "INTENTION",
        "VALIDEE",
        "ENVOYEE",
        "PARTIELLE",
        "EXECUTEE",
    ]
    assert {p["intent_sha256"] for p in payloads} == {intent.sha256()}
    assert [p.get("fill_id") for p in payloads[3:]] == [f.fill_id for f in order.fills]
    assert all(not AMOUNT_KEYS & p.keys() for p in payloads)  # amounts stay in the book
    assert verify(journal.path).ok


def test_a_second_partial_fill_keeps_partielle_and_is_journaled(book_path: Path) -> None:
    journal = MemoryJournal()
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(journal)) as book:
        sent(book, intent)
        states = [book.record_fill(make_fill(intent, n, q)) for n, q in enumerate((2, 3, 5))]
    assert states == [S.PARTIELLE, S.PARTIELLE, S.EXECUTEE]
    assert [state for _, state in journal.states][3:] == ["PARTIELLE", "PARTIELLE", "EXECUTEE"]
    conn = sqlite3.connect(book_path)
    moves = [row[0] for row in conn.execute("SELECT state FROM transitions ORDER BY seq")]
    conn.close()
    assert moves == ["INTENTION", "VALIDEE", "ENVOYEE", "PARTIELLE", "EXECUTEE"]


def test_an_intent_id_never_gives_a_second_order(book_path: Path) -> None:
    journal = MemoryJournal()
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(journal)) as book:
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        with pytest.raises(OrderBookError, match="pas de second ordre"):
            book.record_intent(intent, decision_price=DECISION_PRICE, reason="renvoi")
        assert book.intent_ids() == {intent.intent_id}
    assert len(journal.entries) == 1


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ((), S.ENVOYEE),  # INTENTION → ENVOYEE skips the Risk Gate
        ((S.VALIDEE,), S.EXECUTEE),  # only a fill executes an order
        ((S.VALIDEE, S.ENVOYEE), S.PARTIELLE),
        ((S.REJETEE,), S.VALIDEE),  # a terminal state never moves
        ((S.VALIDEE, S.ANNULEE), S.ENVOYEE),
        ((S.VALIDEE,), S.VALIDEE),
    ],
)
def test_a_move_outside_the_state_machine_is_an_incident_and_records_nothing(
    path: tuple[OrderState, ...], target: OrderState
) -> None:
    journal = MemoryJournal()
    intent = make_intent()
    with OrderBook.memory(recorder(journal)) as book:
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        for state in path:
            book.transition(intent.intent_id, state, reason="étape")
        before = book.order(intent.intent_id).state
        with pytest.raises(ExecutionIncident, match="interdit par la machine") as caught:
            book.transition(intent.intent_id, target, reason="étape")
        assert caught.value.kind == "transition_interdite"
        assert caught.value.intent_id == intent.intent_id
        assert book.order(intent.intent_id).state == before
    assert len(journal.entries) == 1 + len(path)


def test_an_unknown_order_is_an_incident() -> None:
    stranger = make_intent(7)
    with OrderBook.memory(recorder(MemoryJournal())) as book:
        with pytest.raises(ExecutionIncident, match="absent du carnet") as moved:
            book.transition(stranger.intent_id, S.ANNULEE, reason="kill switch")
        with pytest.raises(ExecutionIncident, match="absent du carnet") as filled:
            book.record_fill(make_fill(stranger, 1, 1))
        with pytest.raises(OrderBookError, match="absent du carnet"):
            book.order(stranger.intent_id)
    assert moved.value.kind == filled.value.kind == "ordre_inconnu"


@pytest.mark.parametrize(
    ("side", "changes", "kind", "message"),
    [
        ("BUY", {"quantity": 11}, "quantite_depassee", "quantité cumulée"),
        ("BUY", {"price": Decimal("123.46")}, "execution_incoherente", "au-delà de la limite"),
        ("SELL", {"price": Decimal("123.44")}, "execution_incoherente", "au-delà de la limite"),
        ("BUY", {"currency": "USD"}, "execution_incoherente", "devise différente"),
        (
            "BUY",
            {"executed_at": datetime(2026, 10, 17, 14, 4, tzinfo=PARIS)},
            "execution_incoherente",
            "avant l'intention",
        ),
        ("BUY", {"session": date(2026, 10, 16)}, "execution_incoherente", "séance antérieure"),
    ],
)
def test_a_fill_the_order_cannot_have_is_an_incident_and_records_nothing(
    side: str, changes: dict[str, Any], kind: str, message: str
) -> None:
    journal = MemoryJournal()
    intent = make_intent(side=side)
    with OrderBook.memory(recorder(journal)) as book:
        sent(book, intent)
        others = {key: value for key, value in changes.items() if key != "quantity"}
        bad = make_fill(intent, 1, changes.get("quantity", 10), **others)
        with pytest.raises(ExecutionIncident, match=message) as caught:
            book.record_fill(bad)
        order = book.order(intent.intent_id)
    assert caught.value.kind == kind
    assert (order.state, order.fills) == (S.ENVOYEE, ())
    assert len(journal.entries) == 3


def test_a_buy_may_fill_below_its_limit_and_a_sell_above() -> None:
    buy, sell = make_intent(1), make_intent(2, side="SELL")
    with OrderBook.memory(recorder(MemoryJournal())) as book:
        sent(book, buy)
        sent(book, sell)
        assert book.record_fill(make_fill(buy, 1, 10, price=Decimal("120"))) == S.EXECUTEE
        assert book.record_fill(make_fill(sell, 1, 10, price=Decimal("130"))) == S.EXECUTEE


@pytest.mark.parametrize("path", [(), (S.VALIDEE,), (S.VALIDEE, S.ANNULEE), (S.REJETEE,)])
def test_a_fill_of_an_order_not_at_the_market_is_an_incident(
    path: tuple[OrderState, ...],
) -> None:
    intent = make_intent()
    with OrderBook.memory(recorder(MemoryJournal())) as book:
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        for state in path:
            book.transition(intent.intent_id, state, reason="étape")
        with pytest.raises(ExecutionIncident) as caught:
            book.record_fill(make_fill(intent, 1, 1))
        assert book.order(intent.intent_id).fills == ()
    assert caught.value.kind == "transition_interdite"


def test_a_fill_reported_again_changes_nothing_and_a_different_one_is_an_incident() -> None:
    journal = MemoryJournal()
    intent = make_intent()
    with OrderBook.memory(recorder(journal)) as book:
        sent(book, intent)
        fill = make_fill(intent, 1, 4)
        assert book.record_fill(fill) == S.PARTIELLE
        assert book.record_fill(fill) == S.PARTIELLE
        with pytest.raises(ExecutionIncident, match="autre contenu") as caught:
            book.record_fill(make_fill(intent, 1, 5))
        assert book.order(intent.intent_id).filled == 4
    assert caught.value.kind == "execution_incoherente"
    assert len(journal.entries) == 4


def test_a_cancel_after_a_partial_fill_frees_the_rest() -> None:
    intent = make_intent()
    with OrderBook.memory(recorder(MemoryJournal())) as book:
        sent(book, intent)
        book.record_fill(make_fill(intent, 1, 4))
        assert book.order(intent.intent_id).remaining == 6
        book.transition(intent.intent_id, S.ANNULEE, reason="fin de séance")
        order = book.order(intent.intent_id)
    assert (order.state, order.filled, order.remaining) == (S.ANNULEE, 4, 0)


def test_open_orders_are_those_that_still_commit_cash() -> None:
    validated, partial, done, rejected = (make_intent(n) for n in range(4))
    with OrderBook.memory(recorder(MemoryJournal())) as book:
        for intent in (validated, partial, done, rejected):
            book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        book.transition(validated.intent_id, S.VALIDEE, reason="Porte de risque : ACCEPT")
        sent_ids = (partial, done)
        for intent in sent_ids:
            book.transition(intent.intent_id, S.VALIDEE, reason="Porte de risque : ACCEPT")
            book.transition(intent.intent_id, S.ENVOYEE, reason="soumis au simulateur")
        book.record_fill(make_fill(partial, 1, 3))
        book.record_fill(make_fill(done, 1, 10))
        book.transition(rejected.intent_id, S.REJETEE, reason="Porte de risque : REJECT")
        assert [o.intent.intent_id for o in book.open_orders()] == [
            validated.intent_id,
            partial.intent_id,
        ]
        assert [o.state for o in book.orders()] == [S.VALIDEE, S.PARTIELLE, S.EXECUTEE, S.REJETEE]
        assert book.intent_ids() == {i.intent_id for i in (validated, partial, done, rejected)}


@pytest.mark.parametrize("reason", ["", "x" * 201, "ligne\nsuivante", INJECTION])
def test_a_reason_must_be_plain_short_text(reason: str) -> None:
    with (
        OrderBook.memory(recorder(MemoryJournal())) as book,
        pytest.raises(OrderBookError, match="raison"),
    ):
        book.record_intent(make_intent(), decision_price=DECISION_PRICE, reason=reason)


@pytest.mark.parametrize(
    "price",
    [Decimal(0), Decimal("-1"), Decimal("1.0000001"), Decimal("NaN"), Decimal("Infinity"), 1.5],
)
def test_a_decision_price_has_the_bounds_of_the_risk_gate_quote(price: Any) -> None:
    with (
        OrderBook.memory(recorder(MemoryJournal())) as book,
        pytest.raises(OrderBookError, match="prix de décision"),
    ):
        book.record_intent(make_intent(), decision_price=price, reason="intention rédigée")


def test_a_journal_that_refuses_leaves_the_book_unchanged(book_path: Path) -> None:
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(MemoryJournal(fail_at=1))) as book:
        with pytest.raises(OSError, match="journal indisponible"):
            book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        assert book.intent_ids() == frozenset()
    with OrderBook.open(book_path, recorder=recorder(MemoryJournal(fail_at=5))) as book:
        sent(book, intent)
        book.record_fill(make_fill(intent, 1, 4))
        with pytest.raises(OSError, match="journal indisponible"):
            book.record_fill(make_fill(intent, 2, 6))
        order = book.order(intent.intent_id)
    assert (order.state, order.filled) == (S.PARTIELLE, 4)


def test_without_a_journal_the_book_is_read_only(book_path: Path) -> None:
    with pytest.raises(OrderBookError, match="carnet d'ordres absent"):
        OrderBook.open(book_path, read_only=True)
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(MemoryJournal())) as book:
        sent(book, intent)
    for book in (OrderBook.open(book_path), OrderBook.open(book_path, read_only=True)):
        with book, pytest.raises(OrderBookError, match="lecture seule"):
            book.transition(intent.intent_id, S.ANNULEE, reason="kill switch")
    with OrderBook.open(book_path, recorder=recorder(MemoryJournal()), read_only=True) as book:
        assert book.order(intent.intent_id).state == S.ENVOYEE
        with pytest.raises(OrderBookError, match="lecture seule"):
            book.record_fill(make_fill(intent, 1, 1))


def test_a_book_newer_than_the_code_is_refused(book_path: Path) -> None:
    OrderBook.open(book_path).close()
    conn = sqlite3.connect(book_path, autocommit=True)
    conn.execute("INSERT INTO schema_version VALUES (?, ?)", (LATEST_VERSION + 1, "2026"))
    conn.close()
    with pytest.raises(SchemaError):
        OrderBook.open(book_path)
    with pytest.raises(SchemaError, match="attendu"):
        OrderBook.open(book_path, read_only=True)


@pytest.fixture
def raw(book_path: Path) -> Any:
    """A book with a sent order 4/10 filled, and a bare connection that skips the code."""
    intent = make_intent()
    with OrderBook.open(book_path, recorder=recorder(MemoryJournal())) as book:
        sent(book, intent)
        book.record_fill(make_fill(intent, 1, 4))
    conn = sqlite3.connect(book_path, autocommit=True)
    yield conn, str(intent.intent_id), make_fill(intent, 1, 4).fill_id
    conn.close()


NOW = "2026-10-19T16:00:00.000000Z"
FILL = (
    "INSERT INTO fills VALUES (FILL_ID, :id, '{sha}', :now, '2026-10-19', {q}, '123.45', "
    "'0', 'EUR', :now)".replace("{sha}", "0" * 64)
)
NEW_FILL = FILL.replace("FILL_ID", "'paper:x:9'")


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("UPDATE intents SET quantity = 1", "ne se modifie pas"),
        ("DELETE FROM intents", "ne se supprime pas"),
        ("UPDATE transitions SET state = 'ANNULEE'", "ne se modifie pas"),
        ("DELETE FROM transitions", "ne se supprime pas"),
        ("UPDATE fills SET quantity = 10", "ne se modifie pas"),
        ("DELETE FROM fills", "ne se supprime pas"),
        ("INSERT OR REPLACE INTO intents SELECT * FROM intents", "ne sert qu'une fois"),
        ("INSERT INTO transitions VALUES (:id, 5, 'EXECUTEE', 'x', :now)", "interdite"),
        ("INSERT INTO transitions VALUES (:id, 5, 'VALIDEE', 'x', :now)", "interdite"),
        ("INSERT INTO transitions VALUES (:id, 5, 'PARTIELLE', 'x', :now)", "interdite"),
        ("INSERT INTO transitions VALUES (:id, 9, 'ANNULEE', 'x', :now)", "interdite"),
        (
            "INSERT INTO transitions VALUES ('0199f1a2-0000-7000-8000-000000000000', 1, "
            "'INTENTION', 'x', :now)",
            "interdite",
        ),
        (NEW_FILL.replace("{q}", "7"), "hors de l'ordre"),  # 4 + 7 > 10
        (FILL.replace("FILL_ID", ":fid").replace("{q}", "1"), "hors de l'ordre"),  # same id
        ("INSERT INTO allowed_transitions VALUES ('EXECUTEE', 'VALIDEE')", "ne change pas"),
        ("UPDATE allowed_transitions SET to_state = 'ENVOYEE'", "ne se modifie pas"),
        ("DELETE FROM allowed_transitions", "ne se supprime pas"),
    ],
)
def test_the_database_refuses_what_the_code_never_writes(
    raw: tuple[sqlite3.Connection, str, str], sql: str, message: str
) -> None:
    conn, intent_id, fill_id = raw
    known = {"id": intent_id, "now": NOW, "fid": fill_id}
    params = {key: value for key, value in known.items() if f":{key}" in sql}
    with pytest.raises(sqlite3.IntegrityError, match=message):
        conn.execute(sql, params)


def test_the_database_accepts_the_fill_that_completes_the_order(
    raw: tuple[sqlite3.Connection, str, str],
) -> None:
    conn, intent_id, _ = raw
    params = {"id": intent_id, "now": NOW}
    conn.execute(NEW_FILL.replace("{q}", "6"), params)
    conn.execute("INSERT INTO transitions VALUES (:id, 5, 'EXECUTEE', 'x', :now)", params)
    assert conn.execute("SELECT SUM(quantity) FROM fills").fetchone() == (10,)


def test_an_altered_book_is_detected_on_read(
    raw: tuple[sqlite3.Connection, str, str], book_path: Path
) -> None:
    conn = raw[0]
    conn.execute("DROP TRIGGER intents_no_update")
    conn.execute("""UPDATE intents SET intent = replace(intent, '"quantity":10', '"quantity":9')""")
    with OrderBook.open(book_path) as book, pytest.raises(OrderBookError, match="empreinte"):
        book.orders()


# Slippage --------------------------------------------------------------------------------------


def booked(intent: OrderIntent, decision: Decimal, fills: list[tuple[int, Decimal]]) -> BookedOrder:
    return BookedOrder(
        intent=intent,
        decision_price=decision,
        state=S.EXECUTEE,
        fills=tuple(make_fill(intent, n, q, price=p) for n, (q, p) in enumerate(fills)),
    )


def test_slippage_is_a_cost_in_basis_points_of_the_decision_notional() -> None:
    buy = booked(make_intent(1), Decimal(100), [(4, Decimal("100.50")), (6, Decimal(101))])
    sell = booked(make_intent(2, side="SELL"), Decimal(50), [(5, Decimal("49.90"))])
    assert buy.slippage_bps == Decimal("80.00")  # 8 € paid above 1 000 €
    assert sell.slippage_bps == Decimal("20.00")  # 0.50 € received below 250 €
    assert slippage_bps([buy, sell]) == Decimal("68.00")  # 8.50 € over 1 250 €
    better = booked(make_intent(3), Decimal(100), [(10, Decimal("99.75"))])
    assert better.slippage_bps == Decimal("-25.00")  # a better price is a negative cost


def test_no_fill_no_slippage() -> None:
    assert slippage_bps([]) is None
    assert booked(make_intent(), DECISION_PRICE, []).slippage_bps is None


PRICES = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(100_000), places=6)
ORDERS = st.lists(
    st.tuples(
        st.sampled_from(["BUY", "SELL"]),
        PRICES,
        st.lists(st.tuples(st.integers(1, 10**9), PRICES), max_size=4),
    ),
    max_size=5,
)


@settings(max_examples=300, deadline=None, derandomize=True, database=None)
@given(ORDERS)
def test_slippage_matches_an_exact_fraction_oracle(
    orders: list[tuple[str, Decimal, list[tuple[int, Decimal]]]],
) -> None:
    built = [
        booked(make_intent(n, side=side), decision, fills)
        for n, (side, decision, fills) in enumerate(orders)
    ]
    cost = notional = Fraction(0)
    for side, decision, fills in orders:
        sign = 1 if side == "BUY" else -1
        for quantity, price in fills:
            cost += sign * quantity * (Fraction(price) - Fraction(decision))
            notional += quantity * Fraction(decision)
    result = slippage_bps(built)
    if not notional:
        assert result is None
        return
    assert result == Decimal(round(cost * 10_000 * 100 / notional)).scaleb(-2)  # half-even


def test_an_altered_fill_is_detected_on_read(
    raw: tuple[sqlite3.Connection, str, str], book_path: Path
) -> None:
    conn = raw[0]
    conn.execute("DROP TRIGGER fills_no_update")
    conn.execute("UPDATE fills SET price = '120.00'")
    with OrderBook.open(book_path) as book, pytest.raises(OrderBookError, match="empreinte"):
        book.orders()


def test_the_database_still_refuses_a_move_the_code_would_let_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.execution.book.check_move", lambda *_: None)
    journal = MemoryJournal()
    intent = make_intent()
    with OrderBook.memory(recorder(journal)) as book:
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        with pytest.raises(ExecutionIncident, match="le carnet refuse") as caught:
            book.transition(intent.intent_id, S.EXECUTEE, reason="étape")
        assert book.order(intent.intent_id).state == S.INTENTION
    assert caught.value.kind == "execution_incoherente"
    assert len(journal.entries) == 1

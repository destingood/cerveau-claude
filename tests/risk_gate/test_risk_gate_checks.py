"""The Risk Gate check by check, on hand-made worlds (ADR-031).

Each refusal is shown once with its reason, each limit is reached exactly without refusing, and
each size check reduces an order on its own. The failure paths a generator rarely reaches are
here too: an intent of the wrong type, a check that raises, the gate itself that raises.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.execution.intent import OrderIntent
from core.risk_gate import gate
from core.risk_gate.gate import UNKNOWN, RiskCheck, RiskGateResult, evaluate
from tests.risk_gate.cases import AS_OF, DROP, World, base_world, build, changed
from tests.risk_gate.oracle import FIXED, SIZED

INTENT_ID = base_world()["intent"]["intent_id"]


def run(world: World, form: str = "model") -> RiskGateResult:
    return evaluate(*build(world, form).args)


def check(result: RiskGateResult, name: str) -> RiskCheck:
    return next(c for c in result.checks if c.name == name)


def usd_world(**changes: Any) -> World:
    """A buy of 3 BBB at 50.50 USD, with 10 BBB already held."""
    world = changed(
        base_world(),
        intent__instrument={"symbol": "BBB", "isin": None, "venue": "XNYS", "currency": "USD"},
        intent__limit_price=Decimal("50.50"),
    )
    return changed(world, **changes)


# --- The base order ----------------------------------------------------------------------------


def test_the_base_order_passes_every_check_in_order() -> None:
    got = run(base_world())
    assert (got.result, got.quantity, got.requested_quantity) == ("ACCEPTE", 3, 3)
    assert [c.name for c in got.checks] == ["schema", *FIXED, *SIZED]
    assert all(c.ok for c in got.checks)
    assert got.reasons == ("toutes les vérifications passent",)
    intent = OrderIntent.model_validate(base_world()["intent"])
    assert (got.intent_id, got.intent_sha256) == (intent.intent_id, intent.sha256())


def test_the_policy_payload_carries_the_result_and_every_check() -> None:
    got = run(base_world())
    payload = got.policy_payload()
    assert payload["result"] == "ACCEPTE"
    assert payload["checks"][0] == {
        "name": "schema",
        "ok": True,
        "value": "OrderIntent",
        "limit": "Annexe C.2",
    }
    assert [c["name"] for c in payload["checks"]] == [c.name for c in got.checks]
    assert all(set(c) == {"name", "ok", "value", "limit"} for c in payload["checks"])


@pytest.mark.parametrize("form", ["dict", "json"])
def test_the_intent_may_come_as_a_mapping_or_as_json(form: str) -> None:
    assert run(base_world(), form) == run(base_world())


def test_the_intent_may_come_as_json_bytes() -> None:
    _, *rest = build(base_world()).args
    as_bytes = OrderIntent.model_validate(base_world()["intent"]).model_dump_json().encode()
    assert evaluate(as_bytes, *rest) == run(base_world())


# --- An invalid intent -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "error"),
    [
        (42, "TypeError"),
        ([("quantity", 3)], "TypeError"),
        ("{", "ValidationError"),
        ({**base_world()["intent"], "quantity": 0}, "ValidationError"),
        ({**base_world()["intent"], "environment": "live"}, "ValidationError"),
    ],
    ids=["int", "list", "bad-json", "zero-quantity", "live"],
)
def test_an_invalid_intent_is_refused_by_the_schema_alone(intent: object, error: str) -> None:
    _, *rest = build(base_world()).args
    got = evaluate(intent, *rest)  # type: ignore[arg-type]
    reason = f"schema : intention invalide ({error})"
    assert got == RiskGateResult(
        result="REFUSE",
        intent_id=None,
        intent_sha256=None,
        requested_quantity=None,
        quantity=0,
        checks=(
            RiskCheck(name="schema", ok=False, value="invalide", limit="Annexe C.2", reason=reason),
        ),
        reasons=(reason,),
    )


# --- Checks that refuse ------------------------------------------------------------------------

REFUSALS: list[tuple[str, dict[str, Any], str, str]] = [
    ("seen", {"snapshot__seen_intent_ids": frozenset({INTENT_ID})}, "idempotence", "déjà vu"),
    ("other-day", {"snapshot__as_of": AS_OF + timedelta(days=1)}, "decision", "autre décision"),
    (
        "price-after-snapshot",
        {
            "intent__price_source__as_of": AS_OF - timedelta(minutes=6),
            "snapshot__as_of": AS_OF - timedelta(minutes=7),
        },
        "decision",
        "publié après l'instantané",
    ),
    ("currency", {"intent__instrument__currency": "USD"}, "instrument", "Finance : currency"),
    ("venue", {"intent__instrument__venue": "XNYS"}, "instrument", "Finance : venue"),
    ("isin", {"intent__instrument__isin": "FR0000000002"}, "instrument", "Finance : isin"),
    (
        "no-facts",
        {"snapshot__instruments__AAA": DROP},
        "instrument",
        "données de référence absentes pour AAA",
    ),
    ("universe", {"limits__universe": ["BBB"]}, "universe", "hors de l'univers"),
    ("closed", {"snapshot__open_markets": frozenset({"XNYS"})}, "market_open", "marché fermé"),
    (
        "thin",
        {"snapshot__volumes__AAA__shares": Decimal(99_999)},
        "min_avg_daily_volume",
        "sous le minimum",
    ),
    ("no-volume", {"snapshot__volumes__AAA": DROP}, "min_avg_daily_volume", "volume moyen absent"),
    (
        "volume-sessions",
        {"snapshot__volumes__AAA__sessions": 10},
        "min_avg_daily_volume",
        "volume moyen sur 10 séances, la limite en veut 20",
    ),
    (
        "collar",
        {"intent__limit_price": Decimal("102.01")},
        "limit_price_collar_pct",
        "hors de la bande",
    ),
    ("stale", {"snapshot__quotes__AAA__sessions_old": 2}, "price_freshness", "trop anciens"),
    (
        "no-quote",
        {"snapshot__quotes__AAA": DROP},
        "price_freshness",
        "dernier cours absent pour AAA",
    ),
    (
        "daily-loss",
        {"snapshot__account__day_pnl_eur": Decimal("-200.01")},
        "max_daily_loss_pct",
        "au-delà de la limite",
    ),
    (
        "rolling-loss",
        {"snapshot__account__rolling_pnl_eur": Decimal("-500.01")},
        "max_rolling_loss_pct",
        "au-delà de la limite",
    ),
    (
        "rolling-sessions",
        {"snapshot__account__rolling_sessions": 19},
        "max_rolling_loss_pct",
        "perte glissante sur 19 séances, et non 20",
    ),
    (
        "drawdown",
        {"snapshot__account__equity_eur": Decimal("8999.99")},
        "max_drawdown_pct",
        "au-delà de la limite",
    ),
    ("hour", {"snapshot__orders_last_hour": 10}, "max_orders_per_hour", "trop d'ordres"),
    (
        "day",
        {"snapshot__orders_last_hour": 3, "snapshot__orders_today": 20},
        "max_orders_per_day",
        "trop d'ordres",
    ),
    ("leverage", {"limits__allow__leverage": True}, "allow", "ne modélise pas : leverage"),
    ("short", {"intent__side": "SELL"}, "short_selling", "au-delà de la position"),
    (
        "exclude-symbol",
        {"compliance__exclusions_personnelles": ["aaa"]},
        "compliance",
        "exclu par Lucas : aaa",
    ),
    (
        "exclude-sector",
        {"compliance__exclusions_personnelles": ["TECH"]},
        "compliance",
        "exclu par Lucas : tech",
    ),
    (
        "exclude-isin",
        {"compliance__exclusions_personnelles": ["fr0000000001"]},
        "compliance",
        "exclu par Lucas : fr0000000001",
    ),
    (
        "exclusion-marker",
        {"compliance__exclusions_personnelles": ["BBB", "A_VERIFIER"]},
        "compliance",
        "exclusions_personnelles contient A_VERIFIER (R7)",
    ),
    ("gap", {"snapshot__open_reconciliation_gaps": 1}, "reconciliation", "écart"),
]


@pytest.mark.parametrize(
    ("changes", "name", "fragment"),
    [r[1:] for r in REFUSALS],
    ids=[r[0] for r in REFUSALS],
)
def test_each_check_refuses_and_says_why(changes: dict[str, Any], name: str, fragment: str) -> None:
    got = run(changed(base_world(), **changes))
    assert (got.result, got.quantity) == ("REFUSE", 0)
    failed = check(got, name)
    assert not failed.ok
    assert fragment in failed.reason
    assert f"{name} : {failed.reason}" in got.reasons


def test_a_foreign_order_needs_a_fresh_rate() -> None:
    stale = run(usd_world(snapshot__fx__USD__sessions_old=2))
    assert check(stale, "price_freshness").reason == "cours ou change trop anciens"
    missing = run(usd_world(snapshot__fx__USD=DROP))
    assert missing.result == "REFUSE"
    assert check(missing, "price_freshness").reason == "taux de change absent pour USD"
    assert check(missing, "max_order_pct").value == UNKNOWN


def test_an_exclusion_that_matches_nothing_refuses_nothing() -> None:
    got = run(changed(base_world(), compliance__exclusions_personnelles=["BBB", "energie"]))
    assert got.result == "ACCEPTE"
    assert check(got, "compliance").limit == "2 exclusions"


def test_an_instrument_without_isin_is_matched_on_symbol_and_sector() -> None:
    got = run(usd_world(compliance__exclusions_personnelles=["FR0000000001"]))
    assert got.result == "ACCEPTE"
    assert check(got, "compliance").ok


# --- Limits reached exactly --------------------------------------------------------------------

EDGES: list[tuple[str, dict[str, Any]]] = [
    ("collar", {"intent__limit_price": Decimal("102.00")}),
    ("daily-loss", {"snapshot__account__day_pnl_eur": Decimal("-200")}),
    ("rolling-loss", {"snapshot__account__rolling_pnl_eur": Decimal("-500")}),
    ("drawdown", {"snapshot__account__equity_eur": Decimal("9000")}),
    ("hour", {"snapshot__orders_last_hour": 9}),
    ("day", {"snapshot__orders_today": 19}),
    ("volume", {"snapshot__volumes__AAA__shares": Decimal(100_000)}),
    ("freshness", {"snapshot__quotes__AAA__sessions_old": 1}),
    ("sale", {"intent__side": "SELL", "snapshot__holdings__AAA": 3}),
]


@pytest.mark.parametrize("changes", [e[1] for e in EDGES], ids=[e[0] for e in EDGES])
def test_a_limit_reached_exactly_is_respected(changes: dict[str, Any]) -> None:
    assert run(changed(base_world(), **changes)).result == "ACCEPTE"


# --- Size checks -------------------------------------------------------------------------------


def test_an_order_too_big_is_reduced_to_the_largest_that_fits() -> None:
    got = run(changed(base_world(), intent__quantity=6))
    assert (got.result, got.quantity, got.requested_quantity) == ("REDUIT", 4, 6)
    assert (check(got, "max_order_pct").value, check(got, "max_order_pct").limit) == ("6.03", "5")
    assert got.reasons == ("max_order_pct : ordre trop gros", "quantité ramenée de 6 à 4")
    assert run(changed(base_world(), intent__quantity=4)).result == "ACCEPTE"


@pytest.mark.parametrize(
    ("world", "name", "quantity"),
    [
        (changed(base_world(), snapshot__holdings__AAA=8), "max_position_pct", 1),
        (
            changed(
                base_world(),
                snapshot__open_orders=(
                    {"symbol": "AAA", "side": "BUY", "remaining": 8, "limit_price": Decimal(100)},
                ),
            ),
            "max_position_pct",
            1,
        ),
        (changed(base_world(), limits__max_sector_pct=7.5), "max_sector_pct", 2),
        (changed(base_world(), limits__max_country_pct=2.0), "max_country_pct", 1),
        (usd_world(limits__max_currency_pct=5.0), "max_currency_pct", 1),
        (changed(base_world(), snapshot__account__cash_eur=Decimal("300")), "cash", 2),
    ],
    ids=["position", "open-buy", "sector", "country", "currency", "cash"],
)
def test_each_size_check_reduces_on_its_own(world: World, name: str, quantity: int) -> None:
    got = run(world)
    assert (got.result, got.quantity) == ("REDUIT", quantity)
    assert [c.name for c in got.checks if not c.ok] == [name]


def test_a_sale_adds_to_no_exposure_and_pays_its_fees() -> None:
    got = run(changed(base_world(), intent__side="SELL", snapshot__holdings__AAA=3))
    assert {check(got, name).value for name in SIZED if name.startswith("max_p")} == {"vente"}
    assert check(got, "max_currency_pct").value == "vente"
    assert (check(got, "short_selling").value, check(got, "short_selling").limit) == ("3", "3")
    assert check(got, "cash").value == "1.1508"  # minimum commission and slippage, no amount


def test_open_sales_reserve_the_shares_they_sell() -> None:
    sale = {"symbol": "AAA", "side": "SELL", "remaining": 3, "limit_price": Decimal(100)}
    world = changed(base_world(), intent__side="SELL", snapshot__holdings__AAA=5)
    got = run(changed(world, snapshot__open_orders=(sale,)))
    assert got.result == "REFUSE"
    assert (check(got, "short_selling").value, check(got, "short_selling").limit) == ("3", "2")
    assert run(changed(world, snapshot__holdings__AAA=6, snapshot__open_orders=(sale,))).quantity


def test_an_order_in_euros_has_no_currency_cap() -> None:
    got = check(run(base_world()), "max_currency_pct")
    assert (got.value, got.reason) == ("euro", "l'euro n'est pas plafonné")


def test_open_orders_commit_cash_buys_with_their_amount_sales_with_their_fees() -> None:
    world = changed(
        base_world(),
        snapshot__account__cash_eur=Decimal("1000"),
        snapshot__open_orders=(
            {"symbol": "BBB", "side": "BUY", "remaining": 10, "limit_price": Decimal(50)},
            {"symbol": "CCC", "side": "SELL", "remaining": 5, "limit_price": Decimal(20)},
        ),
    )
    got = run(world)
    assert got.result == "ACCEPTE"
    # 1000 - (450 + 1 + 0.225 + 1.125) for the buy in dollars - (1 + 0.05) for the sale in euros
    assert check(got, "cash").limit == "546.6"


def test_no_quantity_that_fits_refuses() -> None:
    for quantity in (3, 1):
        world = changed(
            base_world(), snapshot__account__cash_eur=Decimal("50"), intent__quantity=quantity
        )
        got = run(world)
        assert (got.result, got.quantity) == ("REFUSE", 0)
        assert got.reasons == (
            "cash : cash insuffisant, frais compris",
            "aucune quantité entière ne respecte les limites de taille et de cash",
        )


def test_an_unknown_size_check_refuses_instead_of_reducing() -> None:
    got = run(changed(base_world(), intent__quantity=6, costs__slippage_bps="A_DEFINIR"))
    assert (got.result, got.quantity) == ("REFUSE", 0)
    assert check(got, "cash").reason == "slippage_bps vaut A_DEFINIR (R7)"
    assert not any(r.startswith("quantité ramenée") for r in got.reasons)


# --- Data needed only where it is used ---------------------------------------------------------


def test_a_holding_outside_the_order_needs_no_quote() -> None:
    got = run(changed(base_world(), snapshot__quotes__CCC=DROP))
    assert got.result == "ACCEPTE"  # CCC shares neither the sector, the country nor the currency


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"snapshot__quotes__BBB": DROP}, "dernier cours absent pour BBB"),
        ({"snapshot__fx__USD": DROP}, "taux de change absent pour USD"),
        ({"snapshot__holdings__EEE": 1}, "données de référence absentes pour EEE"),
    ],
    ids=["quote", "rate", "facts"],
)
def test_a_holding_in_the_same_sector_needs_its_data(changes: dict[str, Any], reason: str) -> None:
    got = run(changed(base_world(), **changes))
    assert (got.result, got.quantity) == ("REFUSE", 0)
    assert check(got, "max_sector_pct").reason == reason
    assert check(got, "max_sector_pct").value == UNKNOWN


# --- Failing closed ----------------------------------------------------------------------------


def _raises(*_: object) -> gate._Verdict:
    raise ZeroDivisionError


def test_a_fixed_check_that_raises_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    patched = tuple((n, _raises if n == "max_drawdown_pct" else c) for n, c in gate.FIXED_CHECKS)
    monkeypatch.setattr(gate, "FIXED_CHECKS", patched)
    got = run(base_world())
    assert [c.name for c in got.checks] == ["schema", *FIXED, *SIZED]
    assert (got.result, got.quantity) == ("REFUSE", 0)
    failed = check(got, "max_drawdown_pct")
    assert (failed.value, failed.limit, failed.reason) == (
        UNKNOWN,
        UNKNOWN,
        "erreur : ZeroDivisionError",
    )


def test_a_size_check_that_raises_refuses_instead_of_reducing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patched = tuple((n, _raises if n == "cash" else c) for n, c in gate.SIZE_CHECKS)
    monkeypatch.setattr(gate, "SIZE_CHECKS", patched)
    got = run(changed(base_world(), intent__quantity=6))
    assert (got.result, got.quantity) == ("REFUSE", 0)
    assert "cash : erreur : ZeroDivisionError" in got.reasons


def test_the_gate_that_raises_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: object) -> RiskGateResult:
        raise RuntimeError

    monkeypatch.setattr(gate, "_evaluate", broken)
    got = run(base_world())
    assert got == RiskGateResult(
        result="REFUSE",
        intent_id=None,
        intent_sha256=None,
        requested_quantity=None,
        quantity=0,
        checks=(),
        reasons=("erreur de la Porte : RuntimeError",),
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("-0.00001"), "0"),
        (Decimal("1.23456"), "1.2346"),
        (Decimal("100.5000"), "100.5"),
        (Decimal("1E+3"), "1000"),
        (7, "7"),
    ],
)
def test_numbers_are_recorded_as_plain_text(value: Decimal | int, text: str) -> None:
    assert gate._num(value) == text

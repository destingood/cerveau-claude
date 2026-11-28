"""The live Risk Gate (B353, ADR-075): every refusal, every limit crossed by one unit.

The gate is pure: each test builds a live configuration, a book and an intent in memory. A
configuration the loader would refuse is built with ``model_construct``, so that the gate's own
checks are proved, whatever the schema (defence in depth).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.config.loader import Allow, LiveConfig, LiveLimits, load_config
from core.finance.model import PARIS
from core.risk_gate import live as live_gate
from core.risk_gate.live import CHECK_NAMES, NO_BOOK, LiveBook, evaluate_live
from tests.execution_cases import make_intent
from tests.test_execution_live import REPO

NOW = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)  # make_intent(0) is drafted at 14:05
LIMITS: dict[str, Any] = {
    "max_order_pct": 2,
    "max_position_pct": 5,
    "max_daily_loss_pct": 1,
    "max_orders_per_day": 3,
}
LIVE: dict[str, Any] = {
    "enabled": True,
    "broker": "courtier-de-test",
    "limits": LIMITS,
    "allow": {"leverage": False, "short_selling": False, "derivatives": False},
    "instruments_whitelist": ["FICT-ACME"],
    "capital_reference_eur": 100_000,
    "timezone": "Europe/Paris",
}


def book_data(**changes: Any) -> dict[str, Any]:
    """20 FICT-ACME held at 120 EUR, 10 000 EUR of cash, 500 EUR lost and one order today."""
    data: dict[str, Any] = {
        "as_of": datetime(2026, 10, 17, 14, 6, tzinfo=PARIS),
        "day": date(2026, 10, 17),
        "instruments": {
            "FICT-ACME": {
                "asset_class": "equity",
                "currency": "EUR",
                "last_price": Decimal("120.00"),
                "priced_at": datetime(2026, 10, 17, 14, 5, tzinfo=PARIS),
            }
        },
        "fx": {},
        "holdings": {"FICT-ACME": 20},
        "open_orders": (),
        "cash_eur": Decimal("10000"),
        "day_pnl_eur": Decimal("-500"),
        "orders_today": 1,
    }
    return data | changes


def config(**changes: Any) -> LiveConfig:
    return LiveConfig.model_validate(LIVE | changes)


def raw(limits: dict[str, Any] | None = None, **changes: Any) -> LiveConfig:
    """A configuration the loader may refuse: built without validation."""
    fields = LIVE | changes
    fields["limits"] = LiveLimits.model_construct(**(LIMITS | (limits or {})))
    if isinstance(fields["allow"], dict):
        fields["allow"] = Allow.model_construct(**fields["allow"])
    return LiveConfig.model_construct(**fields)


def judge(
    live: LiveConfig | None = None,
    book: dict[str, Any] | LiveBook | None = None,
    *,
    now: datetime = NOW,
    **intent: Any,
) -> Any:
    given = LiveBook.model_validate(book_data()) if book is None else book
    if isinstance(given, dict):
        given = LiveBook.model_validate(given)
    return evaluate_live(make_intent(0, **intent), live or config(), given, now=now)


def failed(result: Any) -> dict[str, str]:
    return {check.name: check.reason for check in result.checks if not check.ok}


# The checks a buy passes without a book: a buy sells nothing short.
BOOKLESS = {"schema", "enabled", "instruments_whitelist", "allow", "short_selling"}
ORDER = {"symbol": "FICT-ACME", "remaining": 1, "limit_price": Decimal("0.01")}


# Acceptance --------------------------------------------------------------------------------


def test_an_order_within_every_limit_is_accepted() -> None:
    got = judge()
    assert got.result == "ACCEPTE"
    assert got.quantity == got.requested_quantity == 10
    assert [check.name for check in got.checks] == list(CHECK_NAMES)
    assert all(check.ok for check in got.checks)
    assert got.reasons == ("toutes les vérifications passent",)
    assert got.intent_sha256 == make_intent(0).sha256()


def test_the_gate_is_deterministic() -> None:
    assert judge() == judge()


def test_an_intent_given_as_a_mapping_is_judged_the_same() -> None:
    book = LiveBook.model_validate(book_data())
    mapping = make_intent(0).model_dump()
    assert evaluate_live(mapping, config(), book, now=NOW) == judge()


# The shipped live.yaml ---------------------------------------------------------------------


def test_the_shipped_live_file_refuses_every_order() -> None:
    got = judge(load_config(REPO / "config").live)
    assert got.result == "REFUSE"
    assert got.quantity == 0
    reasons = failed(got)
    assert reasons["enabled"] == "live désactivé (R3)"
    assert reasons["day"].startswith("timezone absent de live.yaml (A_DEFINIR)")
    assert reasons["max_order_pct"] == "max_order_pct vaut 0 : une valeur > 0 est requise"
    assert reasons["max_orders_per_day"] == (
        "max_orders_per_day vaut 0 : une valeur > 0 est requise"
    )
    assert reasons["instruments_whitelist"].startswith("instruments_whitelist vide")


# Values of live.yaml: absent, marker, wrong type, not finite, zero, negative ----------------

PCTS = ("max_order_pct", "max_position_pct", "max_daily_loss_pct")
BAD_NUMBERS: list[tuple[Any, str]] = [
    (None, " absent de live.yaml (A_DEFINIR)"),
    ("A_DEFINIR", " vaut A_DEFINIR (R7)"),
    ("A_VERIFIER", " vaut A_VERIFIER (R7)"),
    ("5", " : nombre attendu, texte trouvé"),
    (True, " : nombre attendu (bool)"),
    ([5], " : nombre attendu (list)"),
    (float("nan"), " n'est pas un nombre fini"),
    (float("inf"), " n'est pas un nombre fini"),
    (0, " vaut 0 : une valeur > 0 est requise"),
    (-1, " vaut -1 : une valeur > 0 est requise"),
]


@pytest.mark.parametrize("name", PCTS)
@pytest.mark.parametrize(
    ("value", "reason"), [*BAD_NUMBERS, (100.01, " vaut 100.01 : au-delà de 100 %")]
)
def test_a_bad_percentage_refuses(name: str, value: Any, reason: str) -> None:
    got = judge(raw({name: value}))
    assert got.result == "REFUSE"
    assert failed(got) == {name: f"{name}{reason}"}


def test_a_percentage_of_100_is_a_valid_limit() -> None:
    assert judge(raw(dict.fromkeys(PCTS, 100))).result == "ACCEPTE"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        *BAD_NUMBERS,
        (2.5, " : nombre entier attendu (float)"),
        (3.0, " : nombre entier attendu (float)"),
    ],
)
def test_a_bad_order_count_refuses(value: Any, reason: str) -> None:
    got = judge(raw({"max_orders_per_day": value}))
    assert failed(got) == {"max_orders_per_day": f"max_orders_per_day{reason}"}


@pytest.mark.parametrize(("value", "reason"), BAD_NUMBERS)
def test_a_bad_reference_capital_refuses_every_sized_check(value: Any, reason: str) -> None:
    got = judge(raw(capital_reference_eur=value))
    assert failed(got) == dict.fromkeys(PCTS, f"capital_reference_eur{reason}")


@pytest.mark.parametrize("marker", ["A_DEFINIR", "A_VERIFIER"])
def test_the_loader_keeps_a_marker_and_the_gate_refuses_it(marker: str) -> None:
    got = judge(config(capital_reference_eur=marker, timezone=marker))
    assert failed(got) == {
        **dict.fromkeys(PCTS, f"capital_reference_eur vaut {marker} (R7)"),
        "day": f"timezone vaut {marker} (R7)",
    }


def test_a_live_file_without_limits_refuses() -> None:
    base = config()
    got = judge(LiveConfig.model_construct(**{k: getattr(base, k) for k in LIVE if k != "limits"}))
    assert set(failed(got)) == {*PCTS, "max_orders_per_day"}
    assert "absent de live.yaml" in failed(got)["max_orders_per_day"]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "timezone absent de live.yaml (A_DEFINIR) : la journée est inconnue"),
        (1, "timezone : nom IANA attendu (int)"),
        ("Mars/Olympus_Mons", "timezone : fuseau inconnu de la base IANA (ZoneInfoNotFoundError)"),
        ("../etc/passwd", "timezone : fuseau inconnu de la base IANA (ValueError)"),
    ],
)
def test_an_unknown_time_zone_refuses(value: Any, reason: str) -> None:
    assert failed(judge(raw(timezone=value))) == {"day": reason}


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_live_not_enabled_refuses(value: Any) -> None:
    got = judge(raw(enabled=value))
    assert failed(got) == {"enabled": "live désactivé (R3)"}
    assert got.checks[1].value == ("false" if value is False else "inconnue")


# The whitelist and the instrument --------------------------------------------------------------


@pytest.mark.parametrize(
    ("entries", "reason"),
    [
        ([], "instruments_whitelist vide ou absente : aucun instrument autorisé"),
        (None, "instruments_whitelist vide ou absente : aucun instrument autorisé"),
        ("FICT-ACME", "instruments_whitelist vide ou absente : aucun instrument autorisé"),
        ([1], "instruments_whitelist : identifiants texte attendus"),
        (["FICT-ACME", "A_DEFINIR"], "instruments_whitelist contient A_DEFINIR (R7)"),
        (["AUTRE"], "hors de la liste blanche"),
    ],
)
def test_an_instrument_not_whitelisted_refuses(entries: Any, reason: str) -> None:
    assert failed(judge(raw(instruments_whitelist=entries))) == {"instruments_whitelist": reason}


def test_an_isin_in_the_whitelist_admits_the_instrument_the_book_confirms() -> None:
    isin = "FR0000000001"
    facts = book_data()["instruments"]["FICT-ACME"] | {"isin": isin}
    book = book_data(instruments={"FICT-ACME": facts})
    got = judge(config(instruments_whitelist=[isin]), book, instrument__isin=isin)
    assert got.result == "ACCEPTE"
    other = judge(config(instruments_whitelist=[isin]), book_data(), instrument__isin=isin)
    assert failed(other) == {"instrument": "diffère du livre live : isin"}


def test_an_instrument_missing_from_the_book_refuses() -> None:
    got = judge(book=book_data(instruments={}, holdings={}))
    assert set(failed(got)) == {
        "instrument",
        "derivatives",
        "max_order_pct",
        "max_position_pct",
        "leverage",
    }
    assert failed(got)["instrument"] == "FICT-ACME absent du livre live"


def test_a_currency_other_than_the_book_refuses() -> None:
    facts = book_data()["instruments"]["FICT-ACME"] | {"currency": "USD"}
    book = book_data(instruments={"FICT-ACME": facts}, fx={"USD": Decimal("0.9")})
    reasons = failed(judge(book=book))
    assert reasons["instrument"] == "diffère du livre live : currency"
    assert reasons["max_order_pct"] == "devise de l'intention EUR, du livre USD"


def test_a_foreign_order_is_valued_at_its_rate_or_refused_without_one() -> None:
    facts = book_data()["instruments"]["FICT-ACME"] | {"currency": "USD"}
    book = book_data(instruments={"FICT-ACME": facts}, fx={"USD": Decimal("0.4")})
    got = judge(book=book, instrument__currency="USD", instrument__venue="XNYS")
    assert got.result == "ACCEPTE"
    order = next(check for check in got.checks if check.name == "max_order_pct")
    assert order.value == "0.4938"  # 10 x 123.45 USD x 0.4 of 100 000 EUR
    no_rate = book_data(instruments={"FICT-ACME": facts})
    got = judge(book=no_rate, instrument__currency="USD", instrument__venue="XNYS")
    assert failed(got)["max_order_pct"] == "taux de change absent pour USD"


def test_a_book_built_with_an_unknown_asset_class_is_refused_whole() -> None:
    facts = book_data()["instruments"]["FICT-ACME"] | {"asset_class": "option"}
    instrument = live_gate.LiveInstrument.model_construct(**facts)
    book = LiveBook.model_construct(**(book_data() | {"instruments": {"FICT-ACME": instrument}}))
    reasons = failed(judge(book=book))
    assert reasons["leverage"] == "livre live invalide (ValidationError)"
    assert set(reasons) == set(CHECK_NAMES) - BOOKLESS


def test_a_class_outside_the_non_derivatives_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_gate, "NON_DERIVATIVES", frozenset({"bond"}))
    assert failed(judge()) == {"derivatives": "classe d'actifs dérivée ou inconnue"}


# Each limit, reached exactly then crossed by one unit --------------------------------------
# The order is 10 x 123.45 EUR = 1 234.50 EUR, valued at its limit price (above the last, 120).


@pytest.mark.parametrize(
    ("capital", "ok"), [(61_725, True), (61_724.99, False)], ids=["at", "over"]
)
def test_the_order_size_limit(capital: float, ok: bool) -> None:
    got = judge(config(capital_reference_eur=capital, limits=LIMITS | {"max_position_pct": 100}))
    assert got.result == ("ACCEPTE" if ok else "REFUSE")
    assert failed(got) == ({} if ok else {"max_order_pct": "ordre trop gros"})


@pytest.mark.parametrize(
    ("capital", "ok"), [(72_690, True), (72_689.99, False)], ids=["at", "over"]
)
def test_the_position_limit_counts_the_holding_and_the_order(capital: float, ok: bool) -> None:
    # 20 held x 120 + 1 234.50 = 3 634.50 EUR: 5 % of 72 690.
    got = judge(config(capital_reference_eur=capital))
    assert failed(got) == ({} if ok else {"max_position_pct": "la position au-delà de la limite"})


def test_the_position_limit_counts_the_open_buys_of_the_instrument() -> None:
    got = judge(
        config(capital_reference_eur=72_690), book_data(open_orders=(ORDER | {"side": "BUY"},))
    )
    assert failed(got) == {"max_position_pct": "la position au-delà de la limite"}


@pytest.mark.parametrize(
    ("pnl", "ok"),
    [("-999.99", True), ("-1000", False), ("-1000.01", False), ("250", True)],
    ids=["under", "at", "over", "gain"],
)
def test_a_day_loss_that_reaches_the_limit_stops_the_day(pnl: str, ok: bool) -> None:
    got = judge(book=book_data(day_pnl_eur=Decimal(pnl)))  # 1 % of 100 000 EUR
    want = {} if ok else {"max_daily_loss_pct": "perte du jour à la limite ou au-delà"}
    assert failed(got) == want


@pytest.mark.parametrize(("done", "ok"), [(2, True), (3, False)], ids=["last", "over"])
def test_the_orders_of_the_day(done: int, ok: bool) -> None:
    got = judge(book=book_data(orders_today=done))  # at most 3 a day
    assert failed(got) == ({} if ok else {"max_orders_per_day": "trop d'ordres aujourd'hui"})


@pytest.mark.parametrize(
    ("cash", "ok"), [("1234.50", True), ("1234.49", False)], ids=["at", "over"]
)
def test_a_buy_beyond_the_cash_would_be_leverage(cash: str, ok: bool) -> None:
    got = judge(book=book_data(cash_eur=Decimal(cash)))
    want = {} if ok else {"leverage": "achat au-delà du cash : ce serait du levier"}
    assert failed(got) == want


def test_the_open_buys_commit_cash() -> None:
    book = book_data(cash_eur=Decimal("1234.50"), open_orders=(ORDER | {"side": "BUY"},))
    assert failed(judge(book=book)) == {"leverage": "achat au-delà du cash : ce serait du levier"}


def test_an_open_buy_of_an_instrument_the_book_does_not_know_refuses() -> None:
    buy = ORDER | {"side": "BUY", "symbol": "FICT-OTHER"}
    assert failed(judge(book=book_data(open_orders=(buy,)))) == {
        "leverage": "FICT-OTHER absent du livre live"
    }


@pytest.mark.parametrize(
    ("held", "selling", "ok"),
    [(10, 0, True), (9, 0, False), (10, 1, False)],
    ids=["covered", "short", "already-sold"],
)
def test_a_sale_beyond_the_position_would_be_short(held: int, selling: int, ok: bool) -> None:
    sells = (ORDER | {"side": "SELL", "remaining": selling},) if selling else ()
    book = book_data(holdings={"FICT-ACME": held}, open_orders=sells)
    got = judge(book=book, side="SELL")
    want = {} if ok else {"short_selling": "vente au-delà de la position détenue"}
    assert failed(got) == want


def test_a_sale_is_sized_at_the_higher_of_its_limit_and_the_last_price() -> None:
    facts = book_data()["instruments"]["FICT-ACME"] | {"last_price": Decimal("200")}
    book = book_data(instruments={"FICT-ACME": facts}, holdings={"FICT-ACME": 10})
    # 10 x 200 = 2 000 EUR, just over 2 % of 99 999.99 EUR; neither the position nor the cash
    # grows with a sale.
    got = judge(config(capital_reference_eur=99_999.99), book, side="SELL")
    assert failed(got) == {"max_order_pct": "ordre trop gros"}
    checks = {check.name: check for check in got.checks}
    assert checks["max_position_pct"].reason == "une vente n'accroît pas la position"
    assert checks["leverage"].reason == "une vente n'emprunte rien"


# The decision's time and day (R10) --------------------------------------------------------


def test_a_book_from_after_the_decision_refuses() -> None:
    later = NOW + timedelta(seconds=1)
    facts = book_data()["instruments"]["FICT-ACME"] | {"priced_at": later}
    got = judge(book=book_data(as_of=later, instruments={"FICT-ACME": facts}))
    assert failed(got) == {
        "point_in_time": "postérieur à la décision (R10) : livre, cours de FICT-ACME"
    }


def test_an_intent_from_after_the_decision_refuses() -> None:
    early = datetime(2026, 10, 17, 14, 0, tzinfo=PARIS)  # make_intent(0) is drafted at 14:05
    facts = book_data()["instruments"]["FICT-ACME"] | {"priced_at": early}
    got = judge(now=early, book=book_data(as_of=early, instruments={"FICT-ACME": facts}))
    assert failed(got) == {"point_in_time": "postérieur à la décision (R10) : intention"}


def test_a_decision_time_without_a_zone_refuses() -> None:
    got = judge(now=datetime(2026, 10, 17, 14, 10))  # naive on purpose
    assert failed(got) == {
        "point_in_time": "heure de décision sans fuseau horaire",
        "day": "heure de décision sans fuseau horaire",
    }


def test_a_book_of_another_day_refuses() -> None:
    got = judge(book=book_data(day=date(2026, 10, 16)))
    assert failed(got) == {"day": "d'une autre journée : livre"}


def test_the_day_boundary_is_the_configured_zone() -> None:
    """23:30 UTC on the 17th: still the 17th in New York, already the 18th in Paris."""
    now = datetime(2026, 10, 17, 23, 30, tzinfo=UTC)
    book = book_data(as_of=now - timedelta(minutes=1))
    new_york = judge(config(timezone="America/New_York"), book, now=now)
    assert new_york.result == "ACCEPTE"
    paris = judge(config(timezone="Europe/Paris"), book, now=now)
    assert failed(paris) == {"day": "d'une autre journée : livre, intention"}
    day = next(check for check in paris.checks if check.name == "day")
    assert (day.value, day.limit) == ("2026-10-18", "Europe/Paris")


# The book's source ------------------------------------------------------------------------


def test_without_a_book_every_check_that_needs_it_refuses() -> None:
    reasons = failed(evaluate_live(make_intent(0), config(), None, now=NOW))
    assert set(reasons) == set(CHECK_NAMES) - BOOKLESS
    assert set(reasons.values()) == {NO_BOOK}
    custom = evaluate_live(make_intent(0), config(), None, now=NOW, missing_book="panne")
    assert set(failed(custom).values()) == {"panne"}


@pytest.mark.parametrize(
    "changes",
    [{"fx": {"EUR": Decimal(1)}}, {"orders_today": -1}, {"open_orders": [1]}],
    ids=["euro-rate", "negative-count", "bad-order"],
)
def test_an_incoherent_book_is_an_unknown_one(changes: dict[str, Any]) -> None:
    book = LiveBook.model_construct(**(book_data() | changes))
    assert set(failed(judge(book=book)).values()) == {"livre live invalide (ValidationError)"}


def test_a_book_priced_after_its_own_time_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="cours publiés après le livre"):
        LiveBook.model_validate(book_data(as_of=datetime(2026, 10, 17, 14, 4, tzinfo=PARIS)))


# Malformed input and errors ---------------------------------------------------------------


def test_a_malformed_intent_refuses_before_any_check() -> None:
    got = evaluate_live({"intent_id": "x"}, config(), None, now=NOW)
    assert got.result == "REFUSE"
    assert [check.name for check in got.checks] == ["schema"]
    assert got.reasons == ("schema : intention invalide (ValidationError)",)


def test_an_error_inside_a_check_refuses_that_check() -> None:
    got = judge(LiveConfig.model_construct(**(LIVE | {"allow": 7, "limits": 7})))
    assert got.result == "REFUSE"
    assert failed(got)["allow"] == "allow.leverage : true ou false attendu (R7)"
    assert "absent de live.yaml" in failed(got)["max_order_pct"]


def test_an_error_of_the_gate_itself_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_inputs: Any) -> Any:
        raise RuntimeError("panne")

    monkeypatch.setattr(live_gate, "_evaluate", broken)
    got = judge()
    assert got.result == "REFUSE"
    assert got.reasons == ("erreur de la Porte live : RuntimeError",)


def test_a_decision_time_that_is_not_a_datetime_refuses() -> None:
    got = judge(now="2026-10-17T14:10:00+02:00")  # type: ignore[arg-type]
    assert failed(got)["point_in_time"] == "erreur : AttributeError"


# allow ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", live_gate.ALLOW_FLAGS)
def test_a_permission_switched_on_refuses_every_order(flag: str) -> None:
    allow = LIVE["allow"] | {flag: True}
    got = judge(config(allow=allow))
    assert failed(got) == {
        "allow": f"la Porte live ne modélise pas {flag} : tout ordre refusé tant que c'est permis"
    }


@pytest.mark.parametrize("value", ["A_DEFINIR", None, 0, "false"])
def test_a_permission_that_is_not_a_boolean_refuses(value: Any) -> None:
    allow = type("Allow", (), {"leverage": False, "short_selling": value, "derivatives": False})
    got = judge(raw(allow=allow()))
    assert failed(got) == {"allow": "allow.short_selling : true ou false attendu (R7)"}

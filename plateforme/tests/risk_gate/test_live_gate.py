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

from core.config.loader import LiveAllow, LiveConfig, LiveLimits, load_config
from core.execution.intent import OrderIntent
from core.finance.model import PARIS
from core.risk_gate import live as live_gate
from core.risk_gate.live import (
    CHECK_NAMES,
    MASKED,
    NO_BOOK,
    NO_JOURNAL,
    JournaledOrder,
    LiveBook,
    evaluate_live,
    fingerprint,
)
from tests.execution_cases import make_intent
from tests.test_execution_live import REPO

NOW = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)  # make_intent(0) is drafted at 14:05
BOOK_AT = datetime(2026, 10, 17, 14, 6, tzinfo=PARIS)
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
    "max_book_age_s": 600,
}


def book_data(**changes: Any) -> dict[str, Any]:
    """20 FICT-ACME held at 120 EUR, 10 000 EUR of cash, 500 EUR lost and one order today."""
    data: dict[str, Any] = {
        "as_of": BOOK_AT,
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


def rate(eur_per_unit: str, as_of: datetime = BOOK_AT) -> dict[str, Any]:
    return {"eur_per_unit": Decimal(eur_per_unit), "as_of": as_of}


def config(**changes: Any) -> LiveConfig:
    return LiveConfig.model_validate(LIVE | changes)


def raw(limits: dict[str, Any] | None = None, **changes: Any) -> LiveConfig:
    """A configuration the loader may refuse: built without validation."""
    fields = LIVE | changes
    fields["limits"] = LiveLimits.model_construct(**(LIMITS | (limits or {})))
    if isinstance(fields["allow"], dict):
        fields["allow"] = LiveAllow.model_construct(**fields["allow"])
    return LiveConfig.model_construct(**fields)


def judge(
    live: LiveConfig | None = None,
    book: dict[str, Any] | LiveBook | None = None,
    *,
    now: datetime = NOW,
    journaled: tuple[JournaledOrder, ...] | None = (),
    **intent: Any,
) -> Any:
    given = LiveBook.model_validate(book_data()) if book is None else book
    if isinstance(given, dict):
        given = LiveBook.model_validate(given)
    return evaluate_live(
        make_intent(0, **intent), live or config(), given, now=now, journaled=journaled
    )


def failed(result: Any) -> dict[str, str]:
    return {check.name: check.reason for check in result.checks if not check.ok}


# The checks a buy passes without a book: a buy sells nothing short.
BOOKLESS = {"schema", "enabled", "instruments_whitelist", "allow", "short_selling"}
# The checks of a buy that need the day, hence the zone: the day itself, and those that count
# the orders accepted today (M4).
ZONED = ("day", "max_position_pct", "max_orders_per_day", "leverage")
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
        **dict.fromkeys(ZONED, f"timezone vaut {marker} (R7)"),
        **dict.fromkeys(PCTS, f"capital_reference_eur vaut {marker} (R7)"),
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
    assert failed(judge(raw(timezone=value))) == dict.fromkeys(ZONED, reason)


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
    book = book_data(instruments={"FICT-ACME": facts}, fx={"USD": rate("0.9")})
    reasons = failed(judge(book=book))
    assert reasons["instrument"] == "diffère du livre live : currency"
    assert reasons["max_order_pct"] == "devise de l'intention EUR, du livre USD"


def test_a_foreign_order_is_valued_at_its_rate_or_refused_without_one() -> None:
    facts = book_data()["instruments"]["FICT-ACME"] | {"currency": "USD"}
    book = book_data(
        instruments={"FICT-ACME": facts}, fx={"USD": rate("0.4")}, day_pnl_eur=Decimal(0)
    )
    usd = {"instrument__currency": "USD", "instrument__venue": "XNYS"}
    roomy = LIMITS | {"max_position_pct": 100}
    # 10 x 123.45 USD x 0.4 = 493.80 EUR: 2 % of 24 690 EUR exactly, a cent of capital less over.
    at = judge(config(capital_reference_eur=24_690, limits=roomy), book, **usd)
    assert at.result == "ACCEPTE"
    over = judge(config(capital_reference_eur=24_689.99, limits=roomy), book, **usd)
    assert failed(over) == {"max_order_pct": "ordre trop gros"}
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
    reason = "FICT-OTHER absent du livre live"
    got = judge(book=book_data(open_orders=(buy,)))
    assert failed(got) == dict.fromkeys(("max_position_pct", "leverage"), reason)


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
    reason = "heure de décision sans fuseau horaire"
    timed = ("point_in_time", "max_book_age_s", *ZONED)
    assert failed(got) == dict.fromkeys(timed, reason)


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
    [{"fx": {"EUR": rate("1")}}, {"orders_today": -1}, {"open_orders": [1]}],
    ids=["euro-rate", "negative-count", "bad-order"],
)
def test_an_incoherent_book_is_an_unknown_one(changes: dict[str, Any]) -> None:
    book = LiveBook.model_construct(**(book_data() | changes))
    assert set(failed(judge(book=book)).values()) == {"livre live invalide (ValidationError)"}


def test_a_book_priced_after_its_own_time_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="lu après le livre"):
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


# M1: no figure of the book in the result ------------------------------------------------------

# Figures no limit, date or fingerprint could spell by chance.
SECRET_BOOK = book_data(
    holdings={"FICT-ACME": 437},
    cash_eur=Decimal("98765.43"),
    day_pnl_eur=Decimal("-543.21"),
)
BOOK_CHECKS = (
    "max_book_age_s",
    "max_order_pct",
    "max_position_pct",
    "max_daily_loss_pct",
    "max_orders_per_day",
    "short_selling",
    "leverage",
)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_a_check_that_reads_the_book_records_none_of_its_figures(side: str) -> None:
    roomy = config(capital_reference_eur=10_000_000)
    got = judge(roomy, SECRET_BOOK, side=side)
    assert got.result == "ACCEPTE"
    checks = {check.name: check for check in got.checks}
    for name in BOOK_CHECKS:
        if checks[name].value not in ("achat", "vente"):  # a side's no-op, not a figure
            assert checks[name].value == MASKED, name
    text = got.model_dump_json()
    for figure in ("437", "98765", "543.21", "53674"):
        assert figure not in text, figure


def test_the_limits_recorded_are_those_of_live_yaml() -> None:
    checks = {check.name: check for check in judge().checks}
    assert checks["max_order_pct"].limit == "2"
    assert checks["max_position_pct"].limit == "5"
    assert checks["max_daily_loss_pct"].limit == "1"
    assert checks["max_orders_per_day"].limit == "3"
    assert checks["max_book_age_s"].limit == "600 s"
    assert checks["leverage"].limit == "cash disponible"


# M2: every part of the book is validated again ------------------------------------------------


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_an_open_order_built_without_validation_is_refused(side: str) -> None:
    """A negative remaining would free cash or shares the account does not have."""
    forged = live_gate.LiveOpenOrder.model_construct(
        symbol="FICT-ACME", side=side, remaining=-1000, limit_price=Decimal("120")
    )
    book = LiveBook.model_construct(
        **(book_data(cash_eur=Decimal("1000")) | {"open_orders": (forged,)})
    )
    got = judge(book=book, side=side)
    assert got.result == "REFUSE"
    assert "livre live invalide (ValidationError)" in failed(got).values()


def test_an_open_order_of_the_paper_snapshot_is_not_a_live_one() -> None:
    from core.risk_gate.snapshot import OpenOrder

    paper = OpenOrder.model_construct(
        symbol="FICT-ACME", side="BUY", remaining=-1000, limit_price=Decimal("120")
    )
    with pytest.raises(ValueError, match="open_orders"):
        LiveBook.model_validate(book_data(open_orders=(paper,)))


@pytest.mark.parametrize(
    "changes",
    [{"holdings": {"FICT-ACME": -5}}, {"fx": {"USD": rate("-1")}}, {"cash_eur": "beaucoup"}],
    ids=["negative-holding", "negative-rate", "text-cash"],
)
def test_a_book_built_without_validation_is_validated_again(changes: dict[str, Any]) -> None:
    book = LiveBook.model_construct(**(book_data() | changes))
    assert judge(book=book).result == "REFUSE"


# M3: the intent is validated again, and fingerprinted here ------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": -500},
        {"quantity": 0},
        {"limit_price": Decimal("NaN")},
        {"limit_price": Decimal("-1")},
        {"side": "HOLD"},
    ],
    ids=["negative", "zero", "nan-price", "negative-price", "unknown-side"],
)
def test_an_intent_built_without_validation_is_refused(changes: dict[str, Any]) -> None:
    forged = make_intent(0).model_copy(update=changes)  # model_copy does not validate
    got = evaluate_live(forged, config(), LiveBook.model_validate(book_data()), now=NOW)
    assert got.result == "REFUSE"
    assert [check.name for check in got.checks] == ["schema"]


def test_a_subclass_of_the_intent_is_refused() -> None:
    class Forged(OrderIntent):
        def sha256(self) -> str:
            return "a" * 64

    forged = Forged.model_validate(make_intent(0).model_dump())
    got = evaluate_live(forged, config(), LiveBook.model_validate(book_data()), now=NOW)
    assert got.reasons == ("schema : intention invalide (TypeError)",)


def test_the_fingerprint_is_the_intent_content_hash() -> None:
    intent = make_intent(0)
    assert fingerprint(intent) == intent.sha256() == judge().intent_sha256


# M4: the orders accepted today, and the book's age ---------------------------------------------


def accepted(n: int, **changes: Any) -> JournaledOrder:
    """The n-th order the gate accepted today: a buy of 10 FICT-ACME at 123.45 EUR."""
    fields: dict[str, Any] = {
        "intent_sha256": fingerprint(make_intent(n)),
        "decided_at": NOW - timedelta(minutes=2),
        "symbol": "FICT-ACME",
        "side": "BUY",
        "quantity": 10,
        "limit_price": Decimal("123.45"),
        "currency": "EUR",
    }
    return JournaledOrder.model_validate(fields | changes)


def test_an_order_accepted_but_not_yet_in_the_book_spends_its_cash() -> None:
    """Two buys of 1 234.50 EUR judged on the same book of 1 500 EUR: the second is refused."""
    book = book_data(cash_eur=Decimal("1500"))
    assert judge(book=book).result == "ACCEPTE"
    second = judge(book=book, journaled=(accepted(1),))
    assert failed(second) == {"leverage": "achat au-delà du cash : ce serait du levier"}


def test_an_order_accepted_counts_among_the_orders_of_the_day() -> None:
    sales = (accepted(1, side="SELL", quantity=1), accepted(2, side="SELL", quantity=1))
    got = judge(book=book_data(orders_today=1), journaled=sales)
    assert failed(got) == {"max_orders_per_day": "trop d'ordres aujourd'hui"}  # 1 + 2 + 1 > 3


def test_an_order_accepted_counts_in_the_position() -> None:
    # 20 x 120 + 1 234.50 + 1 234.50 = 4 869 EUR: over 5 % of 72 690 EUR.
    got = judge(config(capital_reference_eur=72_690), journaled=(accepted(1),))
    assert failed(got) == {"max_position_pct": "la position au-delà de la limite"}


def test_a_sale_accepted_counts_against_the_holding() -> None:
    book = book_data(holdings={"FICT-ACME": 15})
    sold = accepted(1, side="SELL", quantity=6)
    got = judge(book=book, side="SELL", journaled=(sold,))
    assert failed(got) == {"short_selling": "vente au-delà de la position détenue"}


@pytest.mark.parametrize(
    "order",
    [
        accepted(1, intent_sha256="b" * 64),  # known to the book, below
        accepted(0),  # this very intent, judged again
        accepted(1, decided_at=NOW - timedelta(days=1)),  # another day
        accepted(1, decided_at=NOW + timedelta(seconds=1)),  # after the decision (R10)
    ],
    ids=["in-the-book", "itself", "yesterday", "later"],
)
def test_an_order_the_book_shows_or_of_another_day_is_not_counted(order: JournaledOrder) -> None:
    book = book_data(cash_eur=Decimal("1500"), known_intents=frozenset({"b" * 64}))
    assert judge(book=book, journaled=(order,)).result == "ACCEPTE"


def test_an_order_journaled_twice_is_counted_once() -> None:
    book = book_data(cash_eur=Decimal("2469"))  # room for exactly two buys
    assert judge(book=book, journaled=(accepted(1), accepted(1))).result == "ACCEPTE"


def test_without_the_journal_the_counted_checks_refuse() -> None:
    got = judge(journaled=None)
    assert failed(got) == dict.fromkeys(
        ("max_position_pct", "max_orders_per_day", "leverage"), NO_JOURNAL
    )


@pytest.mark.parametrize(("age_s", "ok"), [(600, True), (600.001, False)], ids=["at", "over"])
def test_a_book_older_than_max_book_age_refuses(age_s: float, ok: bool) -> None:
    as_of = NOW - timedelta(seconds=age_s)
    facts = book_data()["instruments"]["FICT-ACME"] | {"priced_at": as_of}
    got = judge(book=book_data(as_of=as_of, instruments={"FICT-ACME": facts}))
    assert failed(got) == ({} if ok else {"max_book_age_s": "trop ancien : livre"})


def test_a_rate_older_than_max_book_age_refuses() -> None:
    old = rate("0.9", NOW - timedelta(seconds=601))
    got = judge(book=book_data(fx={"USD": old}))
    assert failed(got) == {"max_book_age_s": "trop ancien : taux USD"}


def test_a_rate_read_after_the_decision_refuses() -> None:
    later = NOW + timedelta(seconds=5)
    facts = book_data()["instruments"]["FICT-ACME"] | {"priced_at": later}
    book = book_data(as_of=later, instruments={"FICT-ACME": facts}, fx={"USD": rate("1", later)})
    reasons = failed(judge(book=book))
    assert reasons["point_in_time"] == (
        "postérieur à la décision (R10) : livre, cours de FICT-ACME, taux USD"
    )


@pytest.mark.parametrize(("value", "reason"), BAD_NUMBERS)
def test_a_bad_book_age_limit_refuses(value: Any, reason: str) -> None:
    assert failed(judge(raw(max_book_age_s=value))) == {"max_book_age_s": f"max_book_age_s{reason}"}

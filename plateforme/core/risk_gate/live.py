"""The live Risk Gate (B353, ADR-075): the limits of ``config/live.yaml`` on one real order.

A pure function, shaped like the paper gate (ADR-031): ``evaluate_live`` reads its arguments and
nothing else but the time zone database, to resolve the zone that ``live.yaml`` names. It writes
nothing, calls no network and reads no clock: the decision time ``now`` is an argument, and the
book (positions, open orders, cash, the day's P&L and order count) comes from a source the
caller passes, as do the orders the gate already accepted today, read from the journal. It never
reads ``live.yaml`` itself: the caller hands it the validated configuration, read only.

It accepts or refuses; it never reduces, since an approval is bound to the intent's exact
content (D4). Every check is evaluated, so that a refusal gives all its reasons, and every check
fails closed (R7): a value absent, still ``A_DEFINIR`` or ``A_VERIFIER``, of the wrong type, not
finite, zero or negative, or a percentage above 100 refuses; so do an instrument off the
whitelist or missing from the book, a permission of ``allow`` switched on (the gate models no
leverage, short sale or derivative), a book or an intent from another day in the configured
time zone, a book or a rate older than ``max_book_age_s``, a datum published after the decision
(R10), and any error.

Nothing is taken as given: the intent must be an exact ``OrderIntent`` and is validated again
(an instance built without validation, or a subclass, is refused), the book and each of its
parts are validated again, and the values of ``live.yaml`` are checked here whatever the
loader's schema already checked (defence in depth). The orders accepted today that the book
does not show yet count as open orders and as orders of the day, so that two orders judged on
the same book cannot both spend the same cash (M4).

A check that reads the book records no figure of it: its value is ``MASKED`` and its limit is
the one ``live.yaml`` sets, so that the journal never holds the account's cash, holdings, P&L or
exposure (ADR-071). Percentages (1 means 1 %) are of ``capital_reference_eur``; amounts are in
euros, at the higher of the limit price and the last price, in exact decimals.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from core.config.loader import MARKERS, LiveConfig
from core.execution.intent import OrderIntent
from core.finance.model import AssetClass, Currency, InstrumentId, canonical_json, local_date
from core.risk_gate.gate import (
    _EXACT,
    UNKNOWN,
    RiskCheck,
    RiskGateResult,
    _as_intent,
    _num,
    _record,
    _refused,
    _run,
    _Unknown,
    _Verdict,
)
from core.risk_gate.snapshot import Amount, Positive, Quantity, Sessions

ALLOW_FLAGS = ("leverage", "short_selling", "derivatives")
# Every asset class the finance store knows; none is a derivative (``AssetClass``).
NON_DERIVATIVES: frozenset[str] = frozenset(get_args(AssetClass))
NO_BOOK = "livre live inconnu : aucune source de positions, de cash ni de P&L du jour (B353)"
NO_JOURNAL = "ordres acceptés du jour inconnus : journal des décisions live illisible (R7)"
MASKED = "masqué (livre)"  # what a check that reads the book records in place of its figure
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def fingerprint(intent: OrderIntent) -> str:
    """The SHA-256 of an intent's content, computed here, never by a method of the object (an
    approval is bound to it); the same as ``OrderIntent.sha256`` for a genuine intent."""
    content = OrderIntent.model_dump(intent, mode="json")
    return hashlib.sha256(canonical_json(content).encode()).hexdigest()


def live_intent(intent: object) -> OrderIntent:
    """An exact ``OrderIntent``, validated again from its content: an instance built without
    validation, or of a subclass, raises; so does anything the schema refuses."""
    if isinstance(intent, OrderIntent):
        if type(intent) is not OrderIntent:
            raise TypeError(f"sous-classe de OrderIntent refusée ({type(intent).__name__})")
        return OrderIntent.model_validate_json(OrderIntent.model_dump_json(intent))
    return _as_intent(intent)


class _Frozen(BaseModel):
    # Revalidated even when an instance is passed: a book built without validation is checked.
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class LiveInstrument(_Frozen):
    """An instrument's facts as the live source gives them at ``as_of``."""

    asset_class: AssetClass
    currency: Currency
    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] | None = None
    last_price: Positive  # in the instrument's currency
    priced_at: AwareDatetime


class LiveRate(_Frozen):
    """Euros for one unit of a currency, and when the rate was read."""

    eur_per_unit: Positive
    as_of: AwareDatetime


class LiveOpenOrder(_Frozen):
    """An order the broker holds, not yet filled or cancelled: it still commits cash and shares.
    Its own model, revalidated, rather than the paper snapshot's (M2)."""

    symbol: InstrumentId
    side: Literal["BUY", "SELL"]
    remaining: Quantity
    limit_price: Positive


class LiveBook(_Frozen):
    """What the live account holds at ``as_of``, for the day ``day`` of the configured time zone.

    No account number, no broker name: nothing here identifies the account. The gate journals
    only its SHA-256 (ADR-071). ``known_intents`` names, by fingerprint, the orders of the day the
    broker already shows (open or filled): the gate's acceptances it does not show yet are added
    to it (M4)."""

    as_of: AwareDatetime
    day: date  # the trading day that ``day_pnl_eur`` and ``orders_today`` cover
    instruments: dict[InstrumentId, LiveInstrument]
    fx: dict[Currency, LiveRate]  # every currency but the euro
    holdings: dict[InstrumentId, Quantity]  # long positions only
    open_orders: tuple[LiveOpenOrder, ...] = ()
    cash_eur: Amount
    day_pnl_eur: Amount
    orders_today: Sessions  # orders sent to the broker during ``day``
    known_intents: frozenset[Sha256] = frozenset()

    @model_validator(mode="after")
    def _point_in_time(self) -> LiveBook:
        late = sorted(s for s, facts in self.instruments.items() if facts.priced_at > self.as_of)
        late += sorted(f"taux {c}" for c, rate in self.fx.items() if rate.as_of > self.as_of)
        if late:
            raise ValueError(f"lu après le livre (R10) : {', '.join(late)}")
        if "EUR" in self.fx:
            raise ValueError("fx : l'euro n'a pas de taux, il vaut 1")
        return self

    def sha256(self) -> str:
        """The fingerprint the journal keeps in place of the book (ADR-071)."""
        content = LiveBook.model_dump(self, mode="json")
        return hashlib.sha256(canonical_json(content).encode()).hexdigest()


class JournaledOrder(BaseModel):
    """An order the gate accepted, as its journal entry gives it back (M4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_sha256: Sha256
    decided_at: AwareDatetime
    symbol: InstrumentId
    side: Literal["BUY", "SELL"]
    quantity: Quantity
    limit_price: Positive
    currency: Currency


@dataclass(frozen=True)
class _Inputs:
    intent: OrderIntent
    live: LiveConfig
    book: LiveBook | None
    missing_book: str  # why ``book`` is None
    journaled: tuple[JournaledOrder, ...] | None  # None: the journal could not be read
    now: datetime


@dataclass(frozen=True)
class _Open:
    """An order still committing: one the book shows, or one accepted that it does not show."""

    side: str
    symbol: str
    remaining: int
    limit_price: Decimal
    currency: str


# --- Values of live.yaml, checked again (R7) ---------------------------------------------------


def _read(owner: object, name: str) -> object:
    return getattr(owner, name, None)


def _limit(inputs: _Inputs, name: str) -> object:
    return _read(_read(inputs.live, "limits"), name)


def _number(value: object, name: str) -> Decimal:
    """A finite number above 0, or the reason it is not one."""
    if value is None:
        raise _Unknown(f"{name} absent de live.yaml (A_DEFINIR)")
    if isinstance(value, str):
        if value in MARKERS:
            raise _Unknown(f"{name} vaut {value} (R7)")
        raise _Unknown(f"{name} : nombre attendu, texte trouvé")
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise _Unknown(f"{name} : nombre attendu ({type(value).__name__})")
    number = Decimal(str(value))
    if not number.is_finite():
        raise _Unknown(f"{name} n'est pas un nombre fini")
    if number <= 0:
        raise _Unknown(f"{name} vaut {_num(number)} : une valeur > 0 est requise")
    return number


def _pct(value: object, name: str) -> Decimal:
    number = _number(value, name)
    if number > 100:
        raise _Unknown(f"{name} vaut {_num(number)} : au-delà de 100 %")
    return number


def _count(value: object, name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value <= 0:
            raise _Unknown(f"{name} vaut {value} : une valeur > 0 est requise")
        return value
    _number(value, name)  # names why: absent, marker, text, boolean, not finite, not > 0
    raise _Unknown(f"{name} : nombre entier attendu ({type(value).__name__})")


def _capital(inputs: _Inputs) -> Decimal:
    return _number(_read(inputs.live, "capital_reference_eur"), "capital_reference_eur")


def _zone(inputs: _Inputs) -> ZoneInfo:
    name = _read(inputs.live, "timezone")
    if name is None:
        raise _Unknown("timezone absent de live.yaml (A_DEFINIR) : la journée est inconnue")
    if not isinstance(name, str):
        raise _Unknown(f"timezone : nom IANA attendu ({type(name).__name__})")
    if name in MARKERS:
        raise _Unknown(f"timezone vaut {name} (R7)")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        reason = f"timezone : fuseau inconnu de la base IANA ({type(error).__name__})"
        raise _Unknown(reason) from error


# --- Data of the book and of the journal -----------------------------------------------------


def _book(inputs: _Inputs) -> LiveBook:
    if inputs.book is None:
        raise _Unknown(inputs.missing_book)
    return inputs.book


def _now(inputs: _Inputs) -> datetime:
    now = inputs.now
    if now.tzinfo is None or now.utcoffset() is None:
        raise _Unknown("heure de décision sans fuseau horaire")
    return now


def _facts(inputs: _Inputs, symbol: str) -> LiveInstrument:
    facts = _book(inputs).instruments.get(symbol)
    if facts is None:
        raise _Unknown(f"{symbol} absent du livre live")
    return facts


def _rate(inputs: _Inputs, currency: str) -> Decimal:
    if currency == "EUR":
        return Decimal(1)
    rate = _book(inputs).fx.get(currency)
    if rate is None:
        raise _Unknown(f"taux de change absent pour {currency}")
    return rate.eur_per_unit


def _unit_eur(inputs: _Inputs) -> Decimal:
    """One share of the order in euros, at the higher of its limit price and the last price:
    a buy pays at most its limit, a sale may fetch more than its own."""
    given = inputs.intent.instrument
    facts = _facts(inputs, given.symbol)
    if facts.currency != given.currency:
        raise _Unknown(f"devise de l'intention {given.currency}, du livre {facts.currency}")
    price = max(inputs.intent.limit_price, facts.last_price)
    return price * _rate(inputs, given.currency)


def _pending(inputs: _Inputs) -> list[JournaledOrder]:
    """The orders accepted today, up to ``now``, that the book does not show yet: each counted
    once, in the order of their fingerprints; this very intent is not one of them."""
    if inputs.journaled is None:
        raise _Unknown(NO_JOURNAL)
    zone, now, book = _zone(inputs), _now(inputs), _book(inputs)
    today = local_date(now, zone)
    own = fingerprint(inputs.intent)
    pending = {
        order.intent_sha256: order
        for order in inputs.journaled
        if order.intent_sha256 not in book.known_intents
        and order.intent_sha256 != own
        and order.decided_at <= now
        and local_date(order.decided_at, zone) == today
    }
    return [pending[key] for key in sorted(pending)]


def _open(inputs: _Inputs, side: str, symbol: str | None = None) -> list[_Open]:
    orders = [
        _Open(o.side, o.symbol, o.remaining, o.limit_price, _facts(inputs, o.symbol).currency)
        for o in _book(inputs).open_orders
    ]
    orders += [
        _Open(o.side, o.symbol, o.quantity, o.limit_price, o.currency) for o in _pending(inputs)
    ]
    return [o for o in orders if o.side == side and symbol in (None, o.symbol)]


# --- Checks -----------------------------------------------------------------------------------
# A check that reads the book records ``MASKED`` as its value: the gate decides on the figures,
# the journal keeps none of them (ADR-071).


def _enabled(inputs: _Inputs) -> _Verdict:
    enabled = _read(inputs.live, "enabled")
    ok = enabled is True
    value = str(enabled).lower() if isinstance(enabled, bool) else UNKNOWN
    reason = "live activé à la main par l'utilisateur" if ok else "live désactivé (R3)"
    return _Verdict(ok, value, "true", reason)


def _point_in_time(inputs: _Inputs) -> _Verdict:
    now, book, intent = _now(inputs), _book(inputs), inputs.intent
    moments = {
        "intention": intent.created_at,
        "cours cité": intent.price_source.as_of,
        "livre": book.as_of,
        **{f"cours de {s}": facts.priced_at for s, facts in sorted(book.instruments.items())},
        **{f"taux {c}": rate.as_of for c, rate in sorted(book.fx.items())},
    }
    late = [name for name, moment in moments.items() if moment > now]
    reason = (
        f"postérieur à la décision (R10) : {', '.join(late)}"
        if late
        else "aucune donnée postérieure à la décision"
    )
    return _Verdict(not late, now.isoformat(), "heure de décision", reason)


def _day(inputs: _Inputs) -> _Verdict:
    zone, now, book = _zone(inputs), _now(inputs), _book(inputs)
    today = local_date(now, zone)
    days = {
        "livre": book.day,
        "relevé du livre": local_date(book.as_of, zone),
        "intention": local_date(inputs.intent.created_at, zone),
    }
    other = [name for name, day in days.items() if day != today]
    reason = f"d'une autre journée : {', '.join(other)}" if other else "même journée"
    return _Verdict(not other, today.isoformat(), str(zone), reason)


def _book_age(inputs: _Inputs) -> _Verdict:
    """The book and each of its rates read at most ``max_book_age_s`` before the decision."""
    limit = _number(_read(inputs.live, "max_book_age_s"), "max_book_age_s")
    now, book = _now(inputs), _book(inputs)
    moments = {"livre": book.as_of, **{f"taux {c}": r.as_of for c, r in sorted(book.fx.items())}}
    old = [
        name for name, moment in moments.items() if Decimal((now - moment).total_seconds()) > limit
    ]
    reason = f"trop ancien : {', '.join(old)}" if old else "livre et taux assez récents"
    return _Verdict(not old, MASKED, f"{_num(limit)} s", reason)


def _whitelist(inputs: _Inputs) -> _Verdict:
    entries = _read(inputs.live, "instruments_whitelist")
    if not isinstance(entries, list | tuple) or not entries:
        raise _Unknown("instruments_whitelist vide ou absente : aucun instrument autorisé")
    if not all(isinstance(entry, str) for entry in entries):
        raise _Unknown("instruments_whitelist : identifiants texte attendus")
    marked = [entry for entry in entries if entry in MARKERS]
    if marked:
        raise _Unknown(f"instruments_whitelist contient {marked[0]} (R7)")
    given = inputs.intent.instrument
    inside = given.symbol in entries or (given.isin is not None and given.isin in entries)
    reason = "dans la liste blanche" if inside else "hors de la liste blanche"
    return _Verdict(inside, given.symbol, f"{len(entries)} instruments", reason)


def _instrument(inputs: _Inputs) -> _Verdict:
    given = inputs.intent.instrument
    facts = _facts(inputs, given.symbol)
    differs = [
        name
        for name, ok in (
            ("currency", given.currency == facts.currency),
            ("isin", given.isin is None or given.isin == facts.isin),
        )
        if not ok
    ]
    reason = f"diffère du livre live : {', '.join(differs)}" if differs else "conforme au livre"
    return _Verdict(not differs, given.symbol, "livre live", reason)


def _derivatives(inputs: _Inputs) -> _Verdict:
    facts = _facts(inputs, inputs.intent.instrument.symbol)
    ok = facts.asset_class in NON_DERIVATIVES
    reason = "aucun dérivé" if ok else "classe d'actifs dérivée ou inconnue"
    return _Verdict(ok, facts.asset_class, "hors dérivés", reason)


def _allow(inputs: _Inputs) -> _Verdict:
    allow = _read(inputs.live, "allow")
    flags = {name: _read(allow, name) for name in ALLOW_FLAGS}
    unknown = [name for name, value in flags.items() if not isinstance(value, bool)]
    if unknown:
        raise _Unknown(f"allow.{unknown[0]} : true ou false attendu (R7)")
    on = [name for name, value in flags.items() if value]
    reason = (
        f"la Porte live ne modélise pas {', '.join(on)} : tout ordre refusé tant que c'est permis"
        if on
        else "ni levier, ni vente à découvert, ni dérivés"
    )
    return _Verdict(not on, ", ".join(on) or "aucun", "aucun", reason)


def _order_size(inputs: _Inputs) -> _Verdict:
    limit = _pct(_limit(inputs, "max_order_pct"), "max_order_pct")
    capital = _capital(inputs)
    amount = inputs.intent.quantity * _unit_eur(inputs)
    ok = amount * 100 <= limit * capital
    reason = "taille de l'ordre dans la limite" if ok else "ordre trop gros"
    return _Verdict(ok, MASKED, _num(limit), reason)


def _committed(inputs: _Inputs, orders: list[_Open]) -> Decimal:
    return sum(
        (o.remaining * o.limit_price * _rate(inputs, o.currency) for o in orders), Decimal(0)
    )


def _position(inputs: _Inputs) -> _Verdict:
    limit = _pct(_limit(inputs, "max_position_pct"), "max_position_pct")
    capital = _capital(inputs)
    intent = inputs.intent
    if intent.side == "SELL":
        return _Verdict(True, "vente", _num(limit), "une vente n'accroît pas la position")
    symbol = intent.instrument.symbol
    facts = _facts(inputs, symbol)
    held = _book(inputs).holdings.get(symbol, 0) * facts.last_price * _rate(inputs, facts.currency)
    buying = _committed(inputs, _open(inputs, "BUY", symbol))
    after = held + buying + intent.quantity * _unit_eur(inputs)
    ok = after * 100 <= limit * capital
    reason = "la position dans la limite" if ok else "la position au-delà de la limite"
    return _Verdict(ok, MASKED, _num(limit), reason)


def _daily_loss(inputs: _Inputs) -> _Verdict:
    """A loss that reaches the limit stops the day: no new order (strict comparison)."""
    limit = _pct(_limit(inputs, "max_daily_loss_pct"), "max_daily_loss_pct")
    capital = _capital(inputs)
    loss = max(-_book(inputs).day_pnl_eur, Decimal(0))
    ok = loss * 100 < limit * capital
    reason = "perte du jour sous la limite" if ok else "perte du jour à la limite ou au-delà"
    return _Verdict(ok, MASKED, _num(limit), reason)


def _orders_per_day(inputs: _Inputs) -> _Verdict:
    limit = _count(_limit(inputs, "max_orders_per_day"), "max_orders_per_day")
    after = _book(inputs).orders_today + len(_pending(inputs)) + 1
    ok = after <= limit
    reason = "ordres du jour dans la limite" if ok else "trop d'ordres aujourd'hui"
    return _Verdict(ok, MASKED, str(limit), reason)


def _short_selling(inputs: _Inputs) -> _Verdict:
    intent = inputs.intent
    if intent.side == "BUY":
        return _Verdict(True, "achat", "position", "un achat ne vend rien à découvert")
    symbol = intent.instrument.symbol
    selling = sum(o.remaining for o in _open(inputs, "SELL", symbol))
    available = _book(inputs).holdings.get(symbol, 0) - selling
    ok = intent.quantity <= available
    reason = "vente couverte par la position" if ok else "vente au-delà de la position détenue"
    return _Verdict(ok, MASKED, "position détenue", reason)


def _leverage(inputs: _Inputs) -> _Verdict:
    """A buy must be paid from the cash left after the open buys: anything more borrows."""
    intent = inputs.intent
    if intent.side == "SELL":
        return _Verdict(True, "vente", "cash", "une vente n'emprunte rien")
    need = _committed(inputs, _open(inputs, "BUY")) + intent.quantity * _unit_eur(inputs)
    ok = need <= _book(inputs).cash_eur
    reason = "payé par le cash disponible" if ok else "achat au-delà du cash : ce serait du levier"
    return _Verdict(ok, MASKED, "cash disponible", reason)


CHECKS = (
    ("enabled", _enabled),
    ("point_in_time", _point_in_time),
    ("day", _day),
    ("max_book_age_s", _book_age),
    ("instruments_whitelist", _whitelist),
    ("instrument", _instrument),
    ("derivatives", _derivatives),
    ("allow", _allow),
    ("max_order_pct", _order_size),
    ("max_position_pct", _position),
    ("max_daily_loss_pct", _daily_loss),
    ("max_orders_per_day", _orders_per_day),
    ("short_selling", _short_selling),
    ("leverage", _leverage),
)
CHECK_NAMES: tuple[str, ...] = ("schema", *(name for name, _ in CHECKS))


def _evaluate(inputs: _Inputs) -> RiskGateResult:
    intent = inputs.intent
    verdicts = [(name, _run(lambda c=check: c(inputs))) for name, check in CHECKS]
    schema = ("schema", _Verdict(True, "OrderIntent", "Annexe C.2", "intention valide"))
    failed = tuple(f"{name} : {verdict.reason}" for name, verdict in verdicts if not verdict.ok)
    return RiskGateResult(
        result="REFUSE" if failed else "ACCEPTE",
        intent_id=intent.intent_id,
        intent_sha256=fingerprint(intent),
        requested_quantity=intent.quantity,
        quantity=0 if failed else intent.quantity,
        checks=tuple(_record(name, verdict) for name, verdict in [schema, *verdicts]),
        reasons=failed or ("toutes les vérifications passent",),
    )


def evaluate_live(
    intent: object,
    live: LiveConfig,
    book: LiveBook | None,
    *,
    now: datetime,
    missing_book: str = NO_BOOK,
    journaled: tuple[JournaledOrder, ...] | None = (),
) -> RiskGateResult:
    """Accept or refuse one real order against ``live.yaml`` and the book at ``now``.

    ``book`` is None when the source could not give it, for the reason ``missing_book``: every
    check that needs it refuses with that reason. ``journaled`` holds the orders the gate
    accepted, from the journal; None when the journal could not be read, and every check that
    needs them refuses."""
    try:
        checked = live_intent(intent)
    except Exception as error:  # a malformed intent never reaches the other checks
        return schema_refusal(error)
    missing = missing_book
    try:
        valid = None if book is None else LiveBook.model_validate(book)
    except Exception as error:  # an incoherent book is an unknown one
        valid, missing = None, f"livre live invalide ({type(error).__name__})"
    try:
        with localcontext(_EXACT):
            return _evaluate(_Inputs(checked, live, valid, missing, journaled, now))
    except Exception as error:  # fail closed (R7)
        return _refused((f"erreur de la Porte live : {type(error).__name__}",))


def schema_refusal(error: Exception) -> RiskGateResult:
    """The refusal of an object that is no valid intent: only the error's type is named."""
    reason = f"schema : intention invalide ({type(error).__name__})"
    check = RiskCheck(name="schema", ok=False, value="invalide", limit="Annexe C.2", reason=reason)
    return _refused((reason,), (check,))


def refusal(intent: OrderIntent, name: str, reason: str) -> RiskGateResult:
    """A refusal decided before the checks could run (kill switch, configuration unreadable,
    journal unavailable): one failed check ``name``, the intent still named."""
    check = RiskCheck(name=name, ok=False, value=UNKNOWN, limit=UNKNOWN, reason=reason)
    return RiskGateResult(
        result="REFUSE",
        intent_id=intent.intent_id,
        intent_sha256=fingerprint(intent),
        requested_quantity=intent.quantity,
        quantity=0,
        checks=(check,),
        reasons=(f"{name} : {reason}",),
    )

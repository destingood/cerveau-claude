"""The Risk Gate (section 8.4, ADR-031): a pure function between an order intent and the book.

``evaluate`` reads its arguments and nothing else: no model, no I/O, no clock. Every check is
evaluated, so that a refusal gives all its reasons. A limit still at ``A_DEFINIR``, a missing
datum or an exception refuses (R7): the gate fails closed.

Only the size and cash checks can reduce an order (D6), to the largest whole quantity that
respects them all; any other failure refuses, and so does a reduction to zero. The checks are
reported at the requested quantity, so that a reduction shows what it cured.

Exposures are in euros and in percent of the reference capital. A buy adds to the market value
of the holdings and to the open buys of the same instrument, sector, country or currency; a sale
adds to none of them. Classifying a holding or an open buy needs its reference data, valuing it
needs its last close and its currency's rate: a datum is required only where it is used, and a
required datum that is missing refuses. Cash must cover the order and its fees after what the
open orders already commit; a limit price is the most a buy pays, so it values the order.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.config.loader import (
    ComplianceConfig,
    DataQuality,
    Marker,
    PaperRiskLimits,
    TradingCosts,
)
from core.execution.intent import OrderIntent, sizing_tool
from core.finance.model import local_date
from core.risk_gate.snapshot import GateSnapshot, InstrumentFacts

Result = Literal["ACCEPTE", "REFUSE", "REDUIT"]
UNKNOWN = "inconnue"
_MARKERS: frozenset[str] = frozenset(get_args(Marker))
# Exact arithmetic for every amount the checks compare: 60 digits hold any product of their
# bounded inputs, so no comparison rounds; an invalid operation raises instead of guessing.
_EXACT = Context(prec=60, traps=[InvalidOperation, DivisionByZero, Overflow])


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskCheck(_Frozen):
    name: str
    ok: bool
    value: str
    limit: str
    reason: str


class RiskGateResult(_Frozen):
    result: Result
    intent_id: UUID | None
    intent_sha256: str | None
    requested_quantity: int | None
    quantity: int  # the quantity retained; 0 when refused
    checks: tuple[RiskCheck, ...]
    reasons: tuple[str, ...]

    def policy_payload(self) -> dict[str, Any]:
        """The ``risk_gate`` block of a policy decision (Annex C.4)."""
        return {
            "result": self.result,
            "checks": [
                {"name": c.name, "ok": c.ok, "value": c.value, "limit": c.limit}
                for c in self.checks
            ],
        }


class _Unknown(Exception):
    """A limit or a datum the check needs is missing: the check refuses and cannot reduce."""


@dataclass(frozen=True)
class _Verdict:
    ok: bool
    value: str
    limit: str
    reason: str
    known: bool = True


@dataclass(frozen=True)
class _Inputs:
    intent: OrderIntent
    snapshot: GateSnapshot
    limits: PaperRiskLimits
    costs: TradingCosts
    compliance: ComplianceConfig
    quality: DataQuality


def _num(value: Decimal | int) -> str:
    """A decimal as plain text, to four places at most, for the record."""
    text = format(Decimal(value).quantize(Decimal("0.0001")).normalize(), "f")
    return "0" if text == "-0" else text


def _known(value: float | Decimal | str, name: str) -> Decimal:
    if isinstance(value, str):
        raise _Unknown(f"{name} vaut {value} (R7)")
    return Decimal(str(value))


def _count(value: int | str, name: str) -> int:
    if isinstance(value, str):
        raise _Unknown(f"{name} vaut {value} (R7)")
    return value


def _facts(inputs: _Inputs, symbol: str) -> InstrumentFacts:
    facts = inputs.snapshot.instruments.get(symbol)
    if facts is None:
        raise _Unknown(f"données de référence absentes pour {symbol}")
    return facts


def _rate(inputs: _Inputs, currency: str) -> Decimal:
    if currency == "EUR":
        return Decimal(1)
    fx = inputs.snapshot.fx.get(currency)
    if fx is None:
        raise _Unknown(f"taux de change absent pour {currency}")
    return fx.eur_per_unit


def _close(inputs: _Inputs, symbol: str) -> Decimal:
    quote = inputs.snapshot.quotes.get(symbol)
    if quote is None:
        raise _Unknown(f"dernier cours absent pour {symbol}")
    return quote.price


def _unit_eur(inputs: _Inputs) -> Decimal:
    """What one share of the order is worth in euros, at its limit price."""
    return inputs.intent.limit_price * _rate(inputs, inputs.intent.instrument.currency)


def _committed(inputs: _Inputs, match: Callable[[str], bool]) -> Decimal:
    """Market value of the matching holdings plus their open buys, in euros."""
    total = Decimal(0)
    for symbol, quantity in inputs.snapshot.holdings.items():
        if match(symbol):
            currency = _facts(inputs, symbol).currency
            total += quantity * _close(inputs, symbol) * _rate(inputs, currency)
    for order in inputs.snapshot.open_orders:
        if order.side == "BUY" and match(order.symbol):
            currency = _facts(inputs, order.symbol).currency
            total += order.remaining * order.limit_price * _rate(inputs, currency)
    return total


def _fee(inputs: _Inputs, gross: Decimal, currency: str) -> Decimal:
    """Commission, slippage and conversion on an amount in euros (R10, ``trading_costs``)."""
    costs = inputs.costs
    # All four are read, even for an order in euros: an unknown cost refuses the cash check (R7).
    commission_pct = _known(costs.commission_pct, "commission_pct")
    minimum = _known(costs.min_commission_eur, "min_commission_eur")
    slippage_bps = _known(costs.slippage_bps, "slippage_bps")
    conversion_bps = _known(costs.fx_conversion_bps, "fx_conversion_bps")
    fee = max(gross * commission_pct / 100, minimum) + gross * slippage_bps / 10_000
    if currency != "EUR":
        fee += gross * conversion_bps / 10_000
    return fee


# --- Checks that never reduce ------------------------------------------------------------------


def _idempotence(inputs: _Inputs) -> _Verdict:
    seen = inputs.intent.intent_id in inputs.snapshot.seen_intent_ids
    reason = "intent_id déjà vu : l'ordre existe" if seen else "intent_id jamais vu"
    return _Verdict(not seen, str(inputs.intent.intent_id), "unique", reason)


def _decision(inputs: _Inputs) -> _Verdict:
    day = local_date(inputs.snapshot.as_of)
    same_day = inputs.intent.decision_date == day
    known_price = inputs.intent.price_source.as_of <= inputs.snapshot.as_of
    ok = same_day and known_price
    reason = (
        "intention et instantané de la même décision"
        if ok
        else "intention d'une autre décision, ou cours cité publié après l'instantané (R10)"
    )
    return _Verdict(ok, inputs.intent.decision_date.isoformat(), day.isoformat(), reason)


def _instrument(inputs: _Inputs) -> _Verdict:
    given = inputs.intent.instrument
    facts = _facts(inputs, given.symbol)
    differs = [
        field
        for field, ok in (
            ("currency", given.currency == facts.currency),
            ("venue", given.venue == facts.mic),
            ("isin", given.isin is None or given.isin == facts.isin),
        )
        if not ok
    ]
    reason = f"diffère de la base Finance : {', '.join(differs)}" if differs else "conforme"
    return _Verdict(not differs, given.symbol, "base Finance", reason)


def _universe(inputs: _Inputs) -> _Verdict:
    universe = inputs.limits.universe
    if isinstance(universe, str):
        raise _Unknown(f"universe vaut {universe} (R7)")
    inside = inputs.intent.instrument.symbol in universe
    reason = "dans l'univers" if inside else "hors de l'univers autorisé"
    return _Verdict(inside, inputs.intent.instrument.symbol, f"{len(universe)} instruments", reason)


def _market_open(inputs: _Inputs) -> _Verdict:
    venue = inputs.intent.instrument.venue
    is_open = venue in inputs.snapshot.open_markets
    reason = "marché ouvert à la séance d'exécution" if is_open else "marché fermé"
    return _Verdict(is_open, venue, "ouvert", reason)


def _volume(inputs: _Inputs) -> _Verdict:
    minimum = _known(inputs.limits.min_avg_daily_volume, "min_avg_daily_volume")
    sessions = _count(inputs.limits.avg_volume_sessions, "avg_volume_sessions")
    volume = inputs.snapshot.volumes.get(inputs.intent.instrument.symbol)
    if volume is None:
        raise _Unknown("volume moyen absent")
    if volume.sessions != sessions:
        raise _Unknown(f"volume moyen sur {volume.sessions} séances, la limite en veut {sessions}")
    ok = volume.shares >= minimum
    reason = "volume suffisant" if ok else "volume moyen sous le minimum"
    return _Verdict(ok, _num(volume.shares), _num(minimum), reason)


def _collar(inputs: _Inputs) -> _Verdict:
    collar = _known(inputs.limits.limit_price_collar_pct, "limit_price_collar_pct")
    last = _close(inputs, inputs.intent.instrument.symbol)
    gap = abs(inputs.intent.limit_price - last)
    ok = gap * 100 <= collar * last
    reason = "prix limite dans la bande" if ok else "prix limite hors de la bande du dernier cours"
    return _Verdict(ok, _num(gap * 100 / last), _num(collar), reason)


def _freshness(inputs: _Inputs) -> _Verdict:
    limit = _count(inputs.quality.max_staleness_sessions, "max_staleness_sessions")
    symbol = inputs.intent.instrument.symbol
    quote = inputs.snapshot.quotes.get(symbol)
    if quote is None:
        raise _Unknown(f"dernier cours absent pour {symbol}")
    ages = [quote.sessions_old]
    currency = inputs.intent.instrument.currency
    if currency != "EUR":
        fx = inputs.snapshot.fx.get(currency)
        if fx is None:
            raise _Unknown(f"taux de change absent pour {currency}")
        ages.append(fx.sessions_old)
    ok = max(ages) <= limit
    reason = "cours et change assez récents" if ok else "cours ou change trop anciens"
    return _Verdict(ok, str(max(ages)), str(limit), reason)


def _daily_loss(inputs: _Inputs) -> _Verdict:
    limit = _known(inputs.limits.max_daily_loss_pct, "max_daily_loss_pct")
    capital = _known(inputs.limits.capital_reference_eur, "capital_reference_eur")
    loss = max(-inputs.snapshot.account.day_pnl_eur, Decimal(0))
    ok = loss * 100 <= limit * capital
    reason = "perte du jour dans la limite" if ok else "perte du jour au-delà de la limite"
    return _Verdict(ok, _num(loss * 100 / capital), _num(limit), reason)


def _rolling_loss(inputs: _Inputs) -> _Verdict:
    limit = _known(inputs.limits.max_rolling_loss_pct, "max_rolling_loss_pct")
    capital = _known(inputs.limits.capital_reference_eur, "capital_reference_eur")
    sessions = _count(inputs.limits.rolling_loss_sessions, "rolling_loss_sessions")
    account = inputs.snapshot.account
    if account.rolling_sessions != sessions:
        raise _Unknown(f"perte glissante sur {account.rolling_sessions} séances, et non {sessions}")
    loss = max(-account.rolling_pnl_eur, Decimal(0))
    ok = loss * 100 <= limit * capital
    reason = "perte glissante dans la limite" if ok else "perte glissante au-delà de la limite"
    return _Verdict(ok, _num(loss * 100 / capital), _num(limit), reason)


def _drawdown(inputs: _Inputs) -> _Verdict:
    limit = _known(inputs.limits.max_drawdown_pct, "max_drawdown_pct")
    account = inputs.snapshot.account
    drop = account.peak_equity_eur - account.equity_eur
    ok = drop * 100 <= limit * account.peak_equity_eur
    reason = "drawdown dans la limite" if ok else "drawdown au-delà de la limite"
    return _Verdict(ok, _num(drop * 100 / account.peak_equity_eur), _num(limit), reason)


def _rate_limit(name: str, done: Callable[[GateSnapshot], int]) -> Callable[[_Inputs], _Verdict]:
    def check(inputs: _Inputs) -> _Verdict:
        limit = _count(getattr(inputs.limits, name), name)
        after = done(inputs.snapshot) + 1
        ok = after <= limit
        reason = "fréquence dans la limite" if ok else "trop d'ordres sur la période"
        return _Verdict(ok, str(after), str(limit), reason)

    return check


def _allow(inputs: _Inputs) -> _Verdict:
    allowed = [name for name, on in inputs.limits.allow.model_dump().items() if on]
    reason = (
        f"phase 4 ne modélise pas : {', '.join(allowed)}"
        if allowed
        else "ni levier, ni vente à découvert, ni dérivés (aucune classe d'actifs dérivée)"
    )
    return _Verdict(not allowed, ", ".join(allowed) or "aucun", "aucun", reason)


def _short_selling(inputs: _Inputs) -> _Verdict:
    intent = inputs.intent
    if intent.side == "BUY":
        return _Verdict(True, "achat", "position", "un achat ne vend rien à découvert")
    symbol = intent.instrument.symbol
    pending = sum(
        o.remaining for o in inputs.snapshot.open_orders if o.side == "SELL" and o.symbol == symbol
    )
    available = inputs.snapshot.holdings.get(symbol, 0) - pending
    ok = intent.quantity <= available
    reason = "vente couverte par la position" if ok else "vente au-delà de la position détenue"
    return _Verdict(ok, str(intent.quantity), str(available), reason)


def _rationale(inputs: _Inputs) -> _Verdict:
    """The schema checks the rationale's fields; here, that the size comes from the one tool
    that sizes the intent's origin (B195). The Gate reads no journal: that the call is in it is
    the loop's duty, checked by the journal's completeness test."""
    tool = inputs.intent.sizing_source.tool
    allowed = sizing_tool(inputs.intent.origin)
    ok = tool == allowed
    reason = (
        "thèse, catalyseur, invalidation, horizon et source de la taille présents"
        if ok
        else f"taille calculée par {tool}, qui ne dimensionne pas cette origine"
    )
    return _Verdict(ok, tool, allowed, reason)


def _compliance(inputs: _Inputs) -> _Verdict:
    exclusions = inputs.compliance.exclusions_personnelles
    unknown = [entry for entry in exclusions if entry in _MARKERS]
    if unknown:
        raise _Unknown(f"exclusions_personnelles contient {unknown[0]} (R7)")
    given = inputs.intent.instrument
    facts = _facts(inputs, given.symbol)
    names = {given.symbol, facts.sector, *([facts.isin] if facts.isin else [])}
    excluded = {entry.casefold() for entry in exclusions} & {name.casefold() for name in names}
    reason = (
        f"exclu par l'utilisateur : {', '.join(sorted(excluded))}"
        if excluded
        else "aucune exclusion ; aucun actif crypto dans la base Finance"
    )
    return _Verdict(not excluded, given.symbol, f"{len(exclusions)} exclusions", reason)


def _reconciliation(inputs: _Inputs) -> _Verdict:
    gaps = inputs.snapshot.open_reconciliation_gaps
    reason = (
        "aucun écart de réconciliation ouvert" if gaps == 0 else "écart de réconciliation ouvert"
    )
    return _Verdict(gaps == 0, str(gaps), "0", reason)


FIXED_CHECKS: tuple[tuple[str, Callable[[_Inputs], _Verdict]], ...] = (
    ("idempotence", _idempotence),
    ("decision", _decision),
    ("instrument", _instrument),
    ("universe", _universe),
    ("market_open", _market_open),
    ("min_avg_daily_volume", _volume),
    ("limit_price_collar_pct", _collar),
    ("price_freshness", _freshness),
    ("max_daily_loss_pct", _daily_loss),
    ("max_rolling_loss_pct", _rolling_loss),
    ("max_drawdown_pct", _drawdown),
    ("max_orders_per_hour", _rate_limit("max_orders_per_hour", lambda s: s.orders_last_hour)),
    ("max_orders_per_day", _rate_limit("max_orders_per_day", lambda s: s.orders_today)),
    ("allow", _allow),
    ("short_selling", _short_selling),
    ("rationale", _rationale),
    ("compliance", _compliance),
    ("reconciliation", _reconciliation),
)


# --- Checks that may reduce: size and cash, at a given quantity --------------------------------


def _order_size(inputs: _Inputs, quantity: int) -> _Verdict:
    limit = _known(inputs.limits.max_order_pct, "max_order_pct")
    capital = _known(inputs.limits.capital_reference_eur, "capital_reference_eur")
    amount = quantity * _unit_eur(inputs)
    ok = amount * 100 <= limit * capital
    reason = "taille de l'ordre dans la limite" if ok else "ordre trop gros"
    return _Verdict(ok, _num(amount * 100 / capital), _num(limit), reason)


def _exposure(
    name: str, label: str, match: Callable[[_Inputs], Callable[[str], bool] | None]
) -> Callable[[_Inputs, int], _Verdict]:
    """A cap on the exposure that a buy adds to; ``match`` is None when nothing is capped."""

    def check(inputs: _Inputs, quantity: int) -> _Verdict:
        limit = _known(getattr(inputs.limits, name), name)
        capital = _known(inputs.limits.capital_reference_eur, "capital_reference_eur")
        if inputs.intent.side == "SELL":
            return _Verdict(True, "vente", _num(limit), f"une vente n'accroît pas {label}")
        selector = match(inputs)
        if selector is None:
            return _Verdict(True, "euro", _num(limit), "l'euro n'est pas plafonné")
        after = _committed(inputs, selector) + quantity * _unit_eur(inputs)
        ok = after * 100 <= limit * capital
        reason = f"{label} dans la limite" if ok else f"{label} au-delà de la limite"
        return _Verdict(ok, _num(after * 100 / capital), _num(limit), reason)

    return check


def _same_instrument(inputs: _Inputs) -> Callable[[str], bool]:
    symbol = inputs.intent.instrument.symbol
    return lambda other: other == symbol


def _same(attribute: str) -> Callable[[_Inputs], Callable[[str], bool]]:
    def selector(inputs: _Inputs) -> Callable[[str], bool]:
        target = getattr(_facts(inputs, inputs.intent.instrument.symbol), attribute)
        return lambda other: getattr(_facts(inputs, other), attribute) == target

    return selector


def _same_foreign_currency(inputs: _Inputs) -> Callable[[str], bool] | None:
    currency = inputs.intent.instrument.currency
    if currency == "EUR":
        return None
    return lambda other: _facts(inputs, other).currency == currency


def _per_euro(inputs: _Inputs, currency: str) -> Decimal:
    """The fees charged on each euro of an order, beyond the minimum commission."""
    costs = inputs.costs
    rate = _known(costs.commission_pct, "commission_pct") / 100
    rate += _known(costs.slippage_bps, "slippage_bps") / 10_000
    if currency != "EUR":
        rate += _known(costs.fx_conversion_bps, "fx_conversion_bps") / 10_000
    return rate


def _cash(inputs: _Inputs, quantity: int) -> _Verdict:
    committed = Decimal(0)
    for order in inputs.snapshot.open_orders:
        currency = _facts(inputs, order.symbol).currency
        gross = order.remaining * order.limit_price * _rate(inputs, currency)
        committed += _fee(inputs, gross, currency) + (gross if order.side == "BUY" else 0)
    available = inputs.snapshot.account.cash_eur - committed
    currency = inputs.intent.instrument.currency
    gross = quantity * _unit_eur(inputs)
    fee = _fee(inputs, gross, currency)
    if inputs.intent.side == "BUY":
        need = fee + gross
    else:
        # A sale pays its fees out of what it brings in: only what they exceed is needed (B188,
        # D24). That shrinks as the sale grows, which the size search relies on, as long as the
        # fees on each euro stay under one euro.
        if _per_euro(inputs, currency) >= 1:
            raise _Unknown("frais d'au moins 100 % du montant : une vente ne les couvre jamais")
        need = max(fee - gross, Decimal(0))
    ok = need <= available
    reason = "cash suffisant, frais compris" if ok else "cash insuffisant, frais compris"
    return _Verdict(ok, _num(need), _num(available), reason)


SIZE_CHECKS: tuple[tuple[str, Callable[[_Inputs, int], _Verdict]], ...] = (
    ("max_order_pct", _order_size),
    ("max_position_pct", _exposure("max_position_pct", "la position", _same_instrument)),
    ("max_sector_pct", _exposure("max_sector_pct", "le secteur", _same("sector"))),
    ("max_country_pct", _exposure("max_country_pct", "le pays", _same("country"))),
    ("max_currency_pct", _exposure("max_currency_pct", "la devise", _same_foreign_currency)),
    ("cash", _cash),
)


# --- Evaluation --------------------------------------------------------------------------------


def _run(check: Callable[[], _Verdict]) -> _Verdict:
    """One check; a missing datum or an error refuses it, and nothing can reduce it."""
    try:
        return check()
    except _Unknown as missing:
        return _Verdict(False, UNKNOWN, UNKNOWN, str(missing), known=False)
    except Exception as error:  # fail closed (R7): the reason names the error, never hides it
        return _Verdict(False, UNKNOWN, UNKNOWN, f"erreur : {type(error).__name__}", known=False)


def _record(name: str, verdict: _Verdict) -> RiskCheck:
    return RiskCheck(
        name=name, ok=verdict.ok, value=verdict.value, limit=verdict.limit, reason=verdict.reason
    )


def _refused(reasons: tuple[str, ...], checks: tuple[RiskCheck, ...] = ()) -> RiskGateResult:
    return RiskGateResult(
        result="REFUSE",
        intent_id=None,
        intent_sha256=None,
        requested_quantity=None,
        quantity=0,
        checks=checks,
        reasons=reasons,
    )


def _as_intent(intent: object) -> OrderIntent:
    if isinstance(intent, OrderIntent):
        return intent
    if isinstance(intent, str | bytes):
        return OrderIntent.model_validate_json(intent)
    if not isinstance(intent, Mapping):
        raise TypeError(type(intent).__name__)
    return OrderIntent.model_validate(intent)


def _fits(inputs: _Inputs, quantity: int, *, growing_only: bool = False) -> bool:
    """Whether every size check accepts ``quantity``; with ``growing_only``, all but a sale's
    cash, the one check whose need shrinks as the quantity grows (B188)."""
    sale = inputs.intent.side == "SELL"
    return all(
        _run(lambda c=check: c(inputs, quantity)).ok
        for name, check in SIZE_CHECKS
        if not (growing_only and sale and name == "cash")
    )


def _largest_fit(inputs: _Inputs, requested: int) -> int:
    """The largest whole quantity below ``requested`` that every size check accepts, or 0.

    Every size check but a sale's cash grows with the quantity, so the quantities they accept
    form ``[1, q]``: the search finds ``q``. A sale's cash need shrinks as the sale grows
    (B188), so it accepts ``[p, ∞[`` and is checked at ``q`` alone: if it fails there, it fails
    at every smaller quantity too.
    """
    low, high, best = 1, requested - 1, 0
    while low <= high:
        middle = (low + high) // 2
        if _fits(inputs, middle, growing_only=True):
            best, low = middle, middle + 1
        else:
            high = middle - 1
    return best if best and _fits(inputs, best) else 0


def _evaluate(inputs: _Inputs) -> RiskGateResult:
    intent = inputs.intent
    requested = intent.quantity
    fixed = [(name, _run(lambda c=check: c(inputs))) for name, check in FIXED_CHECKS]
    sized = [(name, _run(lambda c=check: c(inputs, requested))) for name, check in SIZE_CHECKS]
    schema = ("schema", _Verdict(True, "OrderIntent", "Annexe C.2", "intention valide"))
    checks = tuple(_record(name, verdict) for name, verdict in [schema, *fixed, *sized])
    failed = [f"{name} : {verdict.reason}" for name, verdict in [*fixed, *sized] if not verdict.ok]

    result: Result = "ACCEPTE"
    quantity = requested
    if any(not verdict.ok for _, verdict in fixed) or any(not v.known for _, v in sized):
        result, quantity = "REFUSE", 0
    elif failed:
        quantity = _largest_fit(inputs, requested)
        result = "REDUIT" if quantity else "REFUSE"
        failed.append(
            f"quantité ramenée de {requested} à {quantity}"
            if quantity
            else "aucune quantité entière ne respecte les limites de taille et de cash"
        )
    return RiskGateResult(
        result=result,
        intent_id=intent.intent_id,
        intent_sha256=intent.sha256(),
        requested_quantity=requested,
        quantity=quantity,
        checks=checks,
        reasons=tuple(failed) or ("toutes les vérifications passent",),
    )


def evaluate(
    intent: OrderIntent | Mapping[str, object] | str | bytes,
    snapshot: GateSnapshot,
    limits: PaperRiskLimits,
    costs: TradingCosts,
    compliance: ComplianceConfig,
    quality: DataQuality,
) -> RiskGateResult:
    """Accept, reduce or refuse one order intent against a frozen snapshot (ADR-031)."""
    try:
        checked = _as_intent(intent)
    except Exception as error:  # a malformed intent never reaches the other checks
        reason = f"schema : intention invalide ({type(error).__name__})"
        check = RiskCheck(
            name="schema", ok=False, value="invalide", limit="Annexe C.2", reason=reason
        )
        return _refused((reason,), (check,))
    try:
        with localcontext(_EXACT):
            return _evaluate(_Inputs(checked, snapshot, limits, costs, compliance, quality))
    except Exception as error:  # fail closed (R7)
        return _refused((f"erreur de la Porte : {type(error).__name__}",))

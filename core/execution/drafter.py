"""The order-intent drafter: target orders become intents, every figure from code (ADR-029, B108).

The model never writes a figure of an intent (R1). The quantity comes from the tool that sized
the order; the limit price is the last price of the Risk Gate's own snapshot, moved by
``limit_offset_pct`` toward a fill and rounded to the cent on the cautious side (down for a buy,
up for a sell), then checked against the collar the Gate applies (D17). The price cited is
therefore the price the Gate checks, published before the decision (R10). An unknown offset or
collar blocks the drafter (R7).

Two sources propose the orders (D7):

- a ``candidate`` strategy, which replays its backtest rule each day: its card gives the thesis,
  the invalidation and the horizon, and the code writes the catalyst, the rule's signal;
- a committee sitting that decided to act on a rebalancing proposal: the quantities are those of
  ``rebalance_proposal``, bound to the call the sitting read; the manager's texts give the
  rationale, and its categories become numbers through fixed tables (ADR-029).

A text longer than an intent allows is cut at a word, with an ellipsis: the whole text stays in
the strategy card or in the sitting's record, which the intent's origin names.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from core.committee.engine import Sitting
from core.committee.rules import NO_CATALYST, SIZE_PENDING, LimitCheck, final_verdict
from core.committee.schemas import Horizon, ManagerDecision
from core.config.loader import ExecutionConfig, PaperRiskLimits
from core.execution.intent import (
    MAX_HORIZON_DAYS,
    RATIONALE_CHARS,
    REBALANCE_TOOL,
    IntentOrigin,
    IntentRationale,
    OrderInstrument,
    OrderIntent,
    PriceSource,
    SizingSource,
)
from core.execution.uuid7 import uuid7
from core.finance.model import local_date
from core.finance.rebalance import RebalanceProposal
from core.finance.research.execution import Order
from core.finance.research.registry import StrategySpec
from core.orchestrator.state import Confidence
from core.risk_gate.snapshot import GateSnapshot
from core.verification.trace import tool_output

CENT = Decimal("0.01")
ELLIPSIS = "…"
# The manager's categories as numbers (ADR-029, hypotheses): the upper bound of each horizon
# (``HORIZONS``: up to 3 months, 3 to 12 months, beyond), the centre of each third of [0, 1].
HORIZON_DAYS: dict[Horizon, int] = {"court": 92, "moyen": 365, "long": MAX_HORIZON_DAYS}
CONFIDENCE: dict[Confidence, float] = {"faible": 0.17, "moyen": 0.5, "eleve": 0.83}
STRATEGY_CONFIDENCE: Confidence = "faible"  # a candidate in paper has proven nothing yet
_EXACT = Context(prec=60, traps=[InvalidOperation, DivisionByZero, Overflow])

Side = Literal["BUY", "SELL"]


class DraftError(ValueError):
    """No intent can be drafted; the reason says why, and no figure is guessed (R7)."""


@dataclass(frozen=True)
class TargetOrder:
    """One order to draft: an instrument, a signed whole quantity, the call that sized it."""

    symbol: str
    quantity: int  # above zero buys, below zero sells
    sizing: SizingSource


def limit_price(last: Decimal, side: Side, offset_pct: Decimal) -> Decimal:
    """``last`` moved by ``offset_pct`` % toward a fill, to the cent on the cautious side."""
    with localcontext(_EXACT):
        if side == "BUY":
            return (last * (100 + offset_pct) / 100).quantize(CENT, rounding=ROUND_FLOOR)
        return (last * (100 - offset_pct) / 100).quantize(CENT, rounding=ROUND_CEILING)


def within_collar(limit: Decimal, last: Decimal, collar_pct: Decimal) -> bool:
    """The Risk Gate's collar check (``core.risk_gate.gate._collar``), to the same formula."""
    with localcontext(_EXACT):
        return abs(limit - last) * 100 <= collar_pct * last


def _known(value: float | str, name: str) -> Decimal:
    if isinstance(value, str):
        raise DraftError(f"{name} vaut {value} : aucune intention n'est rédigée (R7)")
    return Decimal(str(value))


def clip(text: str, limit: int = RATIONALE_CHARS) -> str:
    """``text`` within ``limit`` characters, cut at a word with an ellipsis when too long."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[: limit - len(ELLIPSIS)]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(" ,;:") + ELLIPSIS


def _rationale(
    *, thesis: str, catalyst: str, invalidation: str, horizon_days: int, confidence: float
) -> IntentRationale:
    try:
        return IntentRationale(
            thesis=clip(thesis),
            catalyst=clip(catalyst),
            invalidation=clip(invalidation),
            horizon_days=horizon_days,
            confidence=confidence,
        )
    except ValidationError as error:
        raise DraftError(f"justification refusée : {_first_error(error)}") from None


def _first_error(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where} : {first['msg']}" if where else str(first["msg"])


class IntentDrafter:
    """Drafts the intents of one decision from target orders and the Gate's snapshot."""

    def __init__(
        self,
        execution: ExecutionConfig,
        limits: PaperRiskLimits,
        *,
        ids: Callable[[], UUID] = uuid7,
    ) -> None:
        self._offset = _known(execution.limit_offset_pct, "execution.yaml › limit_offset_pct")
        self._collar = _known(
            limits.limit_price_collar_pct, "risk_limits.paper.yaml › limit_price_collar_pct"
        )
        if self._offset > self._collar:
            raise DraftError(
                f"limit_offset_pct ({self._offset} %) dépasse la bande de prix de la Porte "
                f"({self._collar} %) (D17)"
            )
        self._ids = ids

    def draft(
        self,
        orders: Sequence[TargetOrder],
        snapshot: GateSnapshot,
        *,
        price_tool: str,
        price_call: str,
        rationale: IntentRationale,
        origin: IntentOrigin,
    ) -> tuple[OrderIntent, ...]:
        """One intent per order, all at the snapshot's instant; any refusal drafts none."""
        symbols = [order.symbol for order in orders]
        twice = sorted({s for s in symbols if symbols.count(s) > 1})
        if twice:
            raise DraftError(f"deux ordres pour un même instrument : {', '.join(twice)}")
        return tuple(
            self._intent(order, snapshot, price_tool, price_call, rationale, origin)
            for order in orders
        )

    def _intent(
        self,
        order: TargetOrder,
        snapshot: GateSnapshot,
        price_tool: str,
        price_call: str,
        rationale: IntentRationale,
        origin: IntentOrigin,
    ) -> OrderIntent:
        symbol = order.symbol
        if order.quantity == 0:
            raise DraftError(f"{symbol} : quantité nulle, aucun ordre à rédiger")
        facts = snapshot.instruments.get(symbol)
        quote = snapshot.quotes.get(symbol)
        if facts is None or quote is None:
            missing = "référentiel" if facts is None else "dernier cours"
            raise DraftError(f"{symbol} : {missing} absent du snapshot de la Porte (R7)")
        side: Side = "BUY" if order.quantity > 0 else "SELL"
        limit = limit_price(quote.price, side, self._offset)
        if limit <= 0 or not within_collar(limit, quote.price, self._collar):
            raise DraftError(
                f"{symbol} : prix limite {limit} hors de la bande de {self._collar} % autour du "
                f"dernier cours {quote.price} (D17)"
            )
        try:
            return OrderIntent(
                intent_id=self._ids(),
                created_at=snapshot.as_of,
                decision_date=local_date(snapshot.as_of),
                environment="paper",
                instrument=OrderInstrument(
                    symbol=symbol, isin=facts.isin, venue=facts.mic, currency=facts.currency
                ),
                side=side,
                order_type="LIMIT",
                quantity=abs(order.quantity),
                limit_price=limit,
                time_in_force="DAY",
                price_source=PriceSource(
                    tool=price_tool, call_id=price_call, as_of=quote.published_at
                ),
                sizing_source=order.sizing,
                rationale=rationale,
                origin=origin,
                committee_record_id=origin.id if origin.kind == "committee" else None,
            )
        except ValidationError as error:
            raise DraftError(f"{symbol} : intention refusée : {_first_error(error)}") from None


# Strategy source --------------------------------------------------------------------------------


def strategy_orders(orders: Iterable[Order], sizing: SizingSource) -> tuple[TargetOrder, ...]:
    """The orders of ``target_orders``, sized by the call that ran the strategy."""
    return tuple(TargetOrder(o.instrument_id, o.quantity, sizing) for o in orders)


def strategy_rationale(spec: StrategySpec, *, signal_date: date) -> IntentRationale:
    """The rationale of a ``candidate`` strategy: its card's texts, the code's catalyst."""
    if spec.statut != "candidate":
        raise DraftError(
            f"{spec.id} : stratégie au statut « {spec.statut} » ; seule une « candidate » "
            "propose des ordres (ADR-027)"
        )
    if spec.invalidation is None or spec.horizon_jours is None:
        raise DraftError(f"{spec.id} : fiche sans invalidation ou sans horizon (ADR-029)")
    return _rationale(
        thesis=spec.hypothese,
        catalyst=f"Signal de la règle « {spec.nom} » à la clôture du {signal_date:%d/%m/%Y}.",
        invalidation=spec.invalidation,
        horizon_days=spec.horizon_jours,
        confidence=CONFIDENCE[STRATEGY_CONFIDENCE],
    )


def strategy_origin(spec: StrategySpec) -> IntentOrigin:
    return IntentOrigin(kind="strategy", id=spec.id)


# Committee source -------------------------------------------------------------------------------


def _size_checked(checks: Sequence[LimitCheck]) -> list[LimitCheck]:
    """The committee's checks once the size is known: the Gate measures it on each intent."""
    return [
        LimitCheck(check.name, True, check.reason) if check.reason == SIZE_PENDING else check
        for check in checks
    ]


def _acting(sitting: Sitting) -> ManagerDecision:
    """The decision of ``sitting``, if it acts and nothing but the size blocked it."""
    decision, report = sitting.decision, sitting.controller
    if not sitting.concluded or decision is None or report is None:
        raise DraftError(f"séance {sitting.record_id} non conclue : aucune intention")
    if decision.decision != "agir":
        raise DraftError(f"séance {sitting.record_id} : décision « {decision.decision} »")
    verdict, reasons = final_verdict(_size_checked(sitting.checks), report, decision=decision)
    if verdict != "OK":
        raise DraftError(f"séance {sitting.record_id} bloquée : {' ; '.join(reasons)}")
    return decision


def committee_orders(
    sitting: Sitting, proposal: RebalanceProposal, *, call: str
) -> tuple[TargetOrder, ...]:
    """The operations of ``proposal``, if it is the one the sitting read in ``call``.

    The proposal is bound to the call by its figures and its texts: a proposal computed again
    with the same inputs matches, any other does not.
    """
    _acting(sitting)
    read = next((o for o in sitting.tool_outputs() if o.call == call), None)
    if read is None or read.tool != REBALANCE_TOOL:
        raise DraftError(f"{call} : aucun appel {REBALANCE_TOOL} de la séance ne porte ce nom")
    again = tool_output(call, read.tool, proposal.model_dump(mode="json"))
    if (again.figures, again.texts) != (read.figures, read.texts):
        raise DraftError(f"{call} : la proposition diffère de celle que la séance a lue")
    if proposal.trades is None:
        raise DraftError("proposition sans opérations chiffrées : coûts inconnus (D13, R7)")
    if not proposal.trades:
        raise DraftError("proposition sans opération : aucun ordre à rédiger")
    sizing = SizingSource(tool=REBALANCE_TOOL, call_id=call)
    orders: list[TargetOrder] = []
    for trade in proposal.trades:
        units = trade.quantity.value
        if not units.is_integer() or units <= 0:
            raise DraftError(f"{trade.line} : quantité {trade.quantity.display} non entière")
        signed = int(units) if trade.side == "achat" else -int(units)
        orders.append(TargetOrder(trade.line, signed, sizing))
    return tuple(orders)


def committee_rationale(sitting: Sitting) -> IntentRationale:
    """The rationale of a decision to act: the manager's texts, its categories as numbers."""
    decision = _acting(sitting)
    if decision.catalyseur is None:  # already a reason of the verdict
        raise DraftError(NO_CATALYST)
    return _rationale(
        thesis=decision.proposition,
        catalyst=decision.catalyseur.texte,
        invalidation=" ; ".join(item.condition for item in decision.invalidation),
        horizon_days=HORIZON_DAYS[decision.horizon],
        confidence=CONFIDENCE[decision.confiance],
    )


def committee_origin(sitting: Sitting) -> IntentOrigin:
    return IntentOrigin(kind="committee", id=sitting.record_id)

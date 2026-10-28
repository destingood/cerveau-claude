"""What the Copilot may compute on a registered strategy, and how its backtests become trials.

``strategy_lab`` (plugin finance_research, ADR-027) answers three questions on an entry of the
registry: its signals at a decision, one backtest of one grid point, its latest verdict. The
backtest runs here, on the home engine only, over a window ``config/research.yaml`` bounds and on
the history as published by as_of (R10): replayed later, it gives the same curve.

Every backtest the Copilot obtained is a trial of the family: choosing among them without the
protocol would be the overfitting the deflated Sharpe ratio corrects. ``cerveau strategy protocol``
therefore reads the TOOL_CALL entries the MCP adapter journaled (``copilot_requests``), replays
each with the current code (``copilot_trials``) and records it once, with origin ``copilote`` and
the entry as its source. An entry it cannot replay refuses the protocol: N is never under-counted.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, TypeAdapter

from core.audit import AuditError, AuditJournal
from core.config.loader import ResearchConfig
from core.finance.model import ParamValue, ResearchTrial, params_sha256
from core.finance.research import engine
from core.finance.research.execution import Costs
from core.finance.research.protocol import ENGINE
from core.finance.research.registry import StrategySpec, expanded_grid
from core.finance.research.strategy import Strategy
from core.finance.research.trials import make_trial, strategy_code_sha256
from core.finance.research.view import MarketHistory, decision_time

PLUGIN = "finance_research"
TOOL = "strategy_lab"
Mode = Literal["signaux", "backtest", "protocole"]
MODES: tuple[Mode, ...] = ("signaux", "backtest", "protocole")
_MOMENT = TypeAdapter(AwareDatetime)
_DAY = TypeAdapter(date)


class CopilotError(ValueError):
    """A request outside the registered strategy, or a journal entry that cannot be replayed."""


def grid_point(spec: StrategySpec, params: Mapping[str, ParamValue]) -> dict[str, ParamValue]:
    """The grid point equal to ``params``, types included (``10`` is not ``10.0``).

    The message names the grid, never the values asked: they come from the planner.
    """
    wanted = params_sha256(params)
    grid = expanded_grid(spec)
    for point in grid:
        if params_sha256(point) == wanted:
            return point
    raise CopilotError(
        f"paramètres hors de la grille de {spec.id} ({', '.join(spec.grille)} ; "
        f"{len(grid)} point(s) : `cerveau strategy show {spec.id}`)"
    )


def decision_day(at: datetime, cutoff: time) -> date:
    """The last day whose decision cut-off has passed at ``at``."""
    day = at.astimezone(UTC).date()
    return day if decision_time(day, cutoff) <= at else day - timedelta(days=1)


@dataclass(frozen=True)
class Window:
    """A backtest window and the history as known at the request (R10)."""

    history: MarketHistory
    start: date
    end: date
    sessions: int


def backtest_window(
    spec: StrategySpec,
    history: MarketHistory,
    *,
    at: datetime,
    cutoff: time,
    max_sessions: int,
    start: date | None = None,
    end: date | None = None,
) -> Window:
    """The window of a Copilot backtest, inside the declared period and known at ``at``.

    Without ``start`` the window keeps the last ``max_sessions`` sessions; an explicit window
    longer than that is refused, never shortened behind the caller's back.
    """
    latest = min(decision_day(at, cutoff), spec.periode.fin)
    last = latest if end is None else end
    if last > latest:
        raise CopilotError(
            f"fin du {last:%d/%m/%Y} postérieure au {latest:%d/%m/%Y}, dernière décision connue à "
            "as_of dans la période déclarée (R10)"
        )
    first = spec.periode.debut if start is None else start
    if first < spec.periode.debut:
        raise CopilotError(
            f"début du {first:%d/%m/%Y} antérieur à la période déclarée "
            f"({spec.periode.debut:%d/%m/%Y})"
        )
    if first >= last:
        raise CopilotError("la fenêtre du backtest doit compter au moins deux jours")
    cut = history.known_by(at, last)
    sessions, _ = engine.common_calendar(cut, first, last)
    if len(sessions) > max_sessions:
        if start is not None:
            raise CopilotError(
                f"fenêtre de {len(sessions)} séances : au plus {max_sessions} "
                "(config/research.yaml › copilot.max_window_sessions)"
            )
        sessions = sessions[-max_sessions:]
    return Window(cut, sessions[0], sessions[-1], len(sessions))


@dataclass(frozen=True)
class CopilotBacktest:
    window: Window
    params: dict[str, ParamValue]
    result: engine.BacktestResult
    measures: engine.BacktestMeasures


def backtest(
    spec: StrategySpec,
    strategy: Strategy,
    params: Mapping[str, ParamValue],
    history: MarketHistory,
    *,
    at: datetime,
    research: ResearchConfig,
    costs: Costs,
    initial_cash: float,
    sessions_per_year: int,
    start: date | None = None,
    end: date | None = None,
) -> CopilotBacktest:
    """One grid point over its window: what ``strategy_lab`` returns and the protocol replays."""
    point = grid_point(spec, params)
    cutoff = research.execution.decision_cutoff_utc
    window = backtest_window(
        spec,
        history,
        at=at,
        cutoff=cutoff,
        max_sessions=research.copilot.max_window_sessions,
        start=start,
        end=end,
    )
    result = engine.run(
        strategy,
        point,
        window.history,
        start=window.start,
        end=window.end,
        cutoff=cutoff,
        costs=costs,
        initial_cash=initial_cash,
    )
    return CopilotBacktest(window, point, result, engine.measures(result, sessions_per_year))


@dataclass(frozen=True)
class CopilotRequest:
    """A ``strategy_lab`` backtest the adapter journaled as answered, as the protocol replays it."""

    source: str  # "audit#<seq> <hash>": the entry, at most 85 characters
    at: datetime
    params: dict[str, ParamValue]
    start: date | None
    end: date | None


def _request(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> CopilotRequest:
    source = f"audit#{int(entry['seq'])} {entry['hash']}"
    arguments = payload["arguments"]
    raw = arguments.get("params")
    try:
        params = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(params, dict):
            raise TypeError("params absents")
        # The tool's own types: any form the server accepted reads back the same here.
        # Without as_of the tool read its clock when called, before the adapter journaled it.
        at = (
            _MOMENT.validate_python(arguments["as_of"])
            if arguments.get("as_of") is not None
            else _MOMENT.validate_python(entry["ts"])
            - timedelta(milliseconds=float(payload.get("duration_ms") or 0))
        )
        start, end = (
            _DAY.validate_python(arguments[key]) if arguments.get(key) is not None else None
            for key in ("debut", "fin")
        )
    except (TypeError, ValueError) as exc:
        raise CopilotError(f"entrée {source} illisible : {type(exc).__name__}") from None
    return CopilotRequest(source, at, params, start, end)


def copilot_requests(journal: Path, strategy_id: str) -> list[CopilotRequest]:
    """The answered ``strategy_lab`` backtests of ``strategy_id`` in the audit journal (R11).

    The chain itself is checked by ``cerveau audit verify``; an unreadable line or payload refuses
    the lookup rather than drop a trial.
    """
    if not journal.is_file():
        return []
    audit, found = AuditJournal(journal), list[CopilotRequest]()
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if (entry.get("event"), entry.get("actor")) != ("TOOL_CALL", "orchestrator"):
                continue
            payload = audit.read_payload(entry["payload_ref"]) if entry["payload_ref"] else None
            if not isinstance(payload, dict):
                continue
            if (payload.get("plugin"), payload.get("tool"), payload.get("status")) != (
                PLUGIN,
                TOOL,
                "ok",
            ):
                continue
            arguments = payload.get("arguments")
            if not isinstance(arguments, dict) or (
                arguments.get("mode"),
                arguments.get("strategie"),
            ) != ("backtest", strategy_id):
                continue
            found.append(_request(entry, payload))
    except (OSError, ValueError, KeyError, AuditError) as exc:
        if isinstance(exc, CopilotError):
            raise
        raise CopilotError(f"journal d'audit illisible : {exc}") from exc
    return found


def copilot_trials(
    requests: Sequence[CopilotRequest],
    *,
    recorded: Collection[str],
    spec: StrategySpec,
    strategy: Strategy,
    history: MarketHistory,
    research: ResearchConfig,
    costs: Costs,
    initial_cash: float,
    sessions_per_year: int,
) -> list[ResearchTrial]:
    """The trials of the requests not yet ``recorded`` (their sources), replayed with the current
    code; a request that no longer replays refuses them all."""
    code = strategy_code_sha256(strategy)
    trials: list[ResearchTrial] = []
    for request in requests:
        if request.source in recorded:
            continue
        try:
            run = backtest(
                spec,
                strategy,
                request.params,
                history,
                at=request.at,
                research=research,
                costs=costs,
                initial_cash=initial_cash,
                sessions_per_year=sessions_per_year,
                start=request.start,
                end=request.end,
            )
        except ValueError as exc:
            raise CopilotError(
                f"essai du Copilote {request.source} non rejouable ({exc}) : il compte dans N, "
                "le protocole ne peut pas l'ignorer"
            ) from exc
        trials.append(
            make_trial(
                strategy=spec.id,
                code_sha256=code,
                params=run.params,
                origin="copilote",
                values=run.result.values,
                sessions_per_year=sessions_per_year,
                costs=costs.name,
                engine=ENGINE,
                source=request.source,
            )
        )
    return trials

"""The snapshot refuses an incoherent book or a datum published after the decision (R10)."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from core.risk_gate.snapshot import GateSnapshot
from tests.risk_gate.cases import AS_OF, base_world, changed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"snapshot__account__equity_eur": Decimal("10000.01")},
            "au-dessus du plus haut",
        ),
        (
            {"snapshot__quotes__BBB__published_at": AS_OF + timedelta(seconds=1)},
            "publiés après la décision (R10) : BBB",
        ),
        (
            {"snapshot__fx__EUR": {"eur_per_unit": Decimal("1"), "sessions_old": 0}},
            "l'euro n'a pas de taux",
        ),
    ],
    ids=["equity-above-peak", "quote-after-decision", "euro-rate"],
)
def test_an_incoherent_snapshot_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        GateSnapshot.model_validate(changed(base_world(), **changes)["snapshot"])


def test_a_quote_published_at_the_decision_is_known() -> None:
    world = changed(base_world(), snapshot__quotes__BBB__published_at=AS_OF)
    assert GateSnapshot.model_validate(world["snapshot"]).quotes["BBB"].published_at == AS_OF

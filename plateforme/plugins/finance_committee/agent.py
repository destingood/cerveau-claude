"""Entry point of the finance committee: its members, cards and toolboxes, and its limit checks.

The registry loads this function after validating the manifest (``core.registry.agents``); it
returns the committee's specification, which ``core.committee.run_committee`` runs as a LangGraph
subgraph. The tiers of the members are in ``config/committee.yaml``, the paper limits in
``config/risk_limits.paper.yaml``.
"""

from __future__ import annotations

from pathlib import Path

from core.committee.cards import load_committee
from core.committee.engine import CommitteeSpec
from core.config.loader import Config
from core.orchestrator.packs import PACKS_DIR
from plugins.finance_committee.limits import paper_limit_checks

PACK = "finance"
FEATURE = "finance.committee"


def finance_committee(config: Config, packs_dir: Path = PACKS_DIR) -> CommitteeSpec:
    """The finance committee, as ``domain_packs/finance/committee.yaml`` and its cards say."""
    return load_committee(
        packs_dir / PACK,
        pack=PACK,
        feature=FEATURE,
        limit_checks=paper_limit_checks(config.risk_limits_paper),
    )

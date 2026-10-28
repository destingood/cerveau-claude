"""Entry point of the deep research of the Recherche pack (ADR-045).

The registry loads this function after validating the manifest (``core.registry.agents``); it
returns the research's prompts and version, which ``core.research.run_research`` runs. The limits
of a research are ``per_deep_research`` in ``config/budgets.yaml`` (D13), read when it runs; the
pack's tools are those of ``domain_packs/recherche/manifest.yaml``.
"""

from __future__ import annotations

from pathlib import Path

from core.config.loader import Config
from core.research import ResearchSpec, load_research

PACK = "recherche"
FEATURE = "recherche.deep_research"
VERSION = "0.1.0"  # the manifest's; load_research adds the digest of the prompts (R9)
PLUGIN_DIR = Path(__file__).resolve().parent


def deep_research(config: Config, directory: Path = PLUGIN_DIR) -> ResearchSpec:
    """The deep research of the Recherche pack, as ``prompts/plan.md`` and ``write.md`` say."""
    del config  # the same signature as every agent's; the limits are read from run.config
    return load_research(directory, pack=PACK, feature=FEATURE, version=VERSION)

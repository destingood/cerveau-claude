"""Which PISTE environment the tools use: read from ``config/data_sources.yaml`` at each call.

``sources.legifrance.url`` names production or the sandbox (H4); while it is ``A_DEFINIR``, the
source disabled or the configuration invalid, every call answers « source officielle
indisponible » with the reason (R7).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core.config.loader import BlockedFeatureError, ConfigError, load_config
from plugins.legifrance.client import UNAVAILABLE, Environment, environment
from plugins.legifrance.legi import LegiError

FEATURE = "data.legifrance"
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"

Target = Callable[[], Environment]


def config_target(directory: Path) -> Target:
    """The environment to call, checked again before every request."""

    def target() -> Environment:
        try:
            config = load_config(directory)
            config.require(FEATURE)
        except ConfigError:
            raise LegiError(f"{UNAVAILABLE} : {INVALID_CONFIG}") from None
        except BlockedFeatureError as exc:
            raise LegiError(f"{UNAVAILABLE} : {exc}") from None
        return environment(config.data_sources.sources["legifrance"].url)

    return target

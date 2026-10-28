"""Configuration loading with blocking markers (R7)."""

from core.config.loader import (
    FEATURES,
    MARKERS,
    BlockedFeatureError,
    Config,
    ConfigError,
    MarkerHit,
    config_digest,
    find_markers,
    load_config,
)

__all__ = [
    "FEATURES",
    "MARKERS",
    "BlockedFeatureError",
    "Config",
    "ConfigError",
    "MarkerHit",
    "config_digest",
    "find_markers",
    "load_config",
]

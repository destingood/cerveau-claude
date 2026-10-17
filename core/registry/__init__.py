"""Plugin registry (section 6, R8)."""

from core.registry.manifest import (
    EXPECTED_ANNOTATIONS,
    MIN_EVAL_QUESTIONS,
    PluginManifest,
    PluginReport,
    RegistryReport,
    validate_all,
    validate_plugin,
)

__all__ = [
    "EXPECTED_ANNOTATIONS",
    "MIN_EVAL_QUESTIONS",
    "PluginManifest",
    "PluginReport",
    "RegistryReport",
    "validate_all",
    "validate_plugin",
]

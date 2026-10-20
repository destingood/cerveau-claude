"""Plugin registry (section 6, R8)."""

from core.registry.agents import AgentLoadError, load_agent
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
    "AgentLoadError",
    "PluginManifest",
    "PluginReport",
    "RegistryReport",
    "load_agent",
    "validate_all",
    "validate_plugin",
]

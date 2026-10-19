"""Strategy research: point-in-time backtests, cross-checked engines and the protocol (phase 3).

- ``view``: what a strategy may read at its decision date (R10, ADR-026);
- ``strategy``: the contract of a strategy and the check of its weights (ADR-024);
- ``execution``: orders, fills and costs shared by the engines (ADR-024);
- ``engine``: the in-house daily engine, the reference of every cross-check (ADR-024);
- ``lookahead``: the truncation-invariance check that fails a decision reading later data (ADR-026);
- ``nautilus``: the NautilusTrader replay and its cross-check with the reference (ADR-024, D12).

Nothing here calls a language model: every figure comes from these deterministic functions (R1).
"""

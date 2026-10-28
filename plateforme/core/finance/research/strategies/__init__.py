"""The strategies of the registry, one module each (ADR-027).

A module here is named after the strategy id of its ``domain_packs/finance/strategies/<id>.yaml``
entry: the SHA-256 of its source is the code fingerprint a protocol verdict and a promotion are
tied to, so a change to the module invalidates both.
"""

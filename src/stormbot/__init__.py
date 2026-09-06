"""StormBot — reference implementation of a governed AI execution runtime.

This package is a clean-room, dependency-free distillation of the safety and
assurance patterns used by a private revenue-automation system. It is published
as engineering evidence, not as the production system itself.

The public surface is deliberately small and falls into two halves:

``stormbot.governance``
    Runtime controls that decide whether an agent is permitted to take a
    consequential real-world action (send an SMS, email a prospect, charge a
    card). Fail-closed by construction.

``stormbot.assurance``
    Build-time controls that decide whether a candidate release is permitted to
    ship, by checking product claims against machine-readable evidence.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"

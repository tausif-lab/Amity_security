"""
translator/__init__.py
Deterministic Cisco IOS -> Junos translation engine.

Lives alongside the chatbot's `core/` retrieval package: retrieval (evidence)
is provided by core.store.search; this package turns a Cisco config into a
validated, confidence-scored Junos `set` command list.
"""

from .engine import translate_config

__all__ = ["translate_config"]
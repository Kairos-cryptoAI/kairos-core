"""Canonical message-bus topics / subjects.

Centralising the strings here prevents typos and lets every service agree on a
single namespace. The naming convention is ``kairos.<layer>.<event>``.
"""
from __future__ import annotations


class Topics:
    MARKET_SNAPSHOT = "kairos.market.snapshot"        # Quant Scouts  -> Router
    SENTIMENT_SIGNAL = "kairos.sentiment.signal"      # Text Scouts   -> Router
    ROUTER_DECISION = "kairos.router.decision"        # Router        -> Aggregator
    TACTICAL_COMMAND = "kairos.aggregator.command"    # Aggregator    -> Risk Manager
    STRATEGIC_ALLOCATION = "kairos.macro.allocation"  # Macro         -> Risk Manager
    VALIDATED_ORDER = "kairos.risk.validated_order"   # Risk Manager  -> Execution
    EXECUTION_REPORT = "kairos.execution.report"      # Execution     -> everyone
    SYSTEM_CONTROL = "kairos.system.control"          # Circuit Breaker broadcast
    LLM_HEALTH = "kairos.llm.health"                  # per-call LLM health -> Risk breakers


ALL_TOPICS = [
    value
    for key, value in vars(Topics).items()
    if not key.startswith("_") and isinstance(value, str)
]

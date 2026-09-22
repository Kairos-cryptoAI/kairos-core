"""Canonical message-bus topics / subjects.

Centralising the strings here prevents typos and lets every service agree on a
single namespace. The naming convention is ``kairos.<layer>.<event>``.
"""

from __future__ import annotations


class Topics:
    # Strict Strategy Parity -> PAPER route.  These topics never carry legacy
    # TacticalCommand/ValidatedOrder mutations.
    CLOSED_BAR = "kairos.market.closed_bar.v1"  # Binance collector -> Strategy Engine
    STRATEGY_INTENT = "kairos.strategy.intent.v1"  # Strategy Engine -> Router
    STRATEGY_ROUTE = "kairos.strategy.route.v1"  # Router -> Aggregator
    CANDIDATE_REVIEW = "kairos.aggregator.review.v1"  # Aggregator -> Risk Manager
    # Advisory research output only.  Topic names are not an ACL; consumers
    # must still validate their exact contract and must not subscribe to this
    # topic from Risk Manager or Execution.
    LLM_TRADE_PROPOSAL = "kairos.research.llm_trade_proposal.v1"
    VENUE_QUALITY = "kairos.venue.quality.v1"  # EVEDEX gate -> Risk Manager/TCA
    RISK_TRADE_DECISION = "kairos.risk.trade_decision.v1"  # Risk Manager -> PAPER execution
    TRADE_EXECUTION_EVENT = "kairos.execution.trade_event.v1"  # Execution -> persistence/audit
    ACCOUNT_SNAPSHOT_V2 = "kairos.account.snapshot.v2"  # Reconciler -> Risk/Macro

    # Legacy DRY_RUN route retained unchanged.
    MARKET_SNAPSHOT = "kairos.market.snapshot"  # Quant Scouts  -> Router
    SENTIMENT_SIGNAL = "kairos.sentiment.signal"  # Text Scouts   -> Router
    ROUTER_DECISION = "kairos.router.decision"  # Router        -> Aggregator
    TACTICAL_COMMAND = "kairos.aggregator.command"  # Aggregator    -> Risk Manager
    STRATEGIC_ALLOCATION = "kairos.macro.allocation"  # Macro         -> Risk Manager
    VALIDATED_ORDER = "kairos.risk.validated_order"  # Risk Manager  -> Execution
    EXECUTION_REPORT = "kairos.execution.report"  # Execution     -> everyone
    ACCOUNT_SNAPSHOT = "kairos.account.snapshot"  # Reconciler    -> Risk/Macro
    SYSTEM_CONTROL = "kairos.system.control"  # Circuit Breaker broadcast
    LLM_HEALTH = "kairos.llm.health"  # per-call LLM health -> Risk breakers


ALL_TOPICS = [
    value for key, value in vars(Topics).items() if not key.startswith("_") and isinstance(value, str)
]

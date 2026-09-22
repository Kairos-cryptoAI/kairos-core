"""Enumerations shared across the whole system.

Using ``str`` mixin enums keeps the wire format human-readable (the values are
exactly what appears in the JSON on the bus) while still giving us type safety
inside Python.
"""

from __future__ import annotations

from enum import StrEnum


class ReasoningEffort(StrEnum):
    """Logical analysis depth, mapped to a concrete provider+model in :mod:`kairos-llm`.

    Workload-specific routing (the enum remains a provider-neutral wire value):
      * ``LOW``    — DeepSeek-V4-Flash, non-thinking (Text Scouts; no reasoning effort).
      * ``MEDIUM`` — GPT-5.6 Luna, ``reasoning.effort=medium`` (Aggregator normal path).
      * ``HIGH``   — GPT-5.6 Terra, ``reasoning.effort=high`` (Aggregator conflict path).
      * ``XHIGH``  — GPT-5.6 Sol, ``reasoning.effort=xhigh`` (Macro-Strategist).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class RouterMode(StrEnum):
    """Flag emitted by the Router selecting the Aggregator analytics contour.

    The historical wire names are retained for compatibility:
      * ``ROUTE_PRO`` — routine Aggregator flow on GPT-5.6 Luna.
      * ``ROUTE_GPT`` — conflict escalation to GPT-5.6 Terra.
    """

    ROUTE_PRO = "ROUTE_PRO"
    ROUTE_GPT = "ROUTE_GPT"


class SystemMode(StrEnum):
    """Global operating mode, owned by the Risk Manager / Circuit Breaker.

    Per-model Circuit Breaker degradation (severity increases downward):
      * ``NORMAL`` — all analytics layers healthy.
      * ``TEXT_LOCAL_FILTER`` — DeepSeek-V4-Flash down; Text Scouts filter locally.
      * ``CONFLICT_SAFE`` — GPT-5.6 down; conflict decisions forced to WAIT_CONFIRMATION.
      * ``LOCAL_QUANT_MODE`` — several models down; local stop-loss scripts only.
    """

    NORMAL = "NORMAL"
    TEXT_LOCAL_FILTER = "TEXT_LOCAL_FILTER"
    CONFLICT_SAFE = "CONFLICT_SAFE"
    LOCAL_QUANT_MODE = "LOCAL_QUANT_MODE"


class Side(StrEnum):
    """Directional bias of a signal or an open position."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderSide(StrEnum):
    """Side of a concrete exchange order."""

    BUY = "BUY"
    SELL = "SELL"


class ImpactDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MarketRegime(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    CHOP = "CHOP"  # hard sideways / flat


class TacticalStatus(StrEnum):
    """High-level tactical state produced by the Aggregator."""

    STABLE_TREND_ENTRY = "STABLE_TREND_ENTRY"
    HOLD_GRID = "HOLD_GRID"
    SHIFT_GRID = "SHIFT_GRID"
    WAIT_CONFIRMATION = "WAIT_CONFIRMATION"
    REDUCE_LEVERAGE = "REDUCE_LEVERAGE"
    EXIT = "EXIT"


class ReasonCode(StrEnum):
    """Machine-actionable code consumed by the Execution Engine.

    The Execution Engine NEVER interprets free text — it only switches on this
    code, which has already been validated by the Risk Manager.
    """

    ENTER_LONG_TREND = "ENTER_LONG_TREND"
    ENTER_SHORT_TREND = "ENTER_SHORT_TREND"
    HOLD = "HOLD"
    REDUCE_LEVERAGE = "REDUCE_LEVERAGE"
    CLOSE_POSITION = "CLOSE_POSITION"
    REBALANCE = "REBALANCE"
    NO_TRADE = "NO_TRADE"


class StrategicTrigger(StrEnum):
    SCHEDULE = "schedule"
    SHOCK_EVENT = "shock_event"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"  # default for limit orders
    IOC = "IOC"  # default for market orders
    FOK = "FOK"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class ReviewDecision(StrEnum):
    """The only changes an LLM review may make to a strategy candidate."""

    ALLOW = "ALLOW"
    VETO = "VETO"
    DEFER = "DEFER"


class LLMProposalAction(StrEnum):
    """Research-only direction emitted by an LLM proposal experiment.

    These values are advisory labels, not :class:`Side`, a strategy intent,
    an approval, or an execution instruction.
    """

    LONG_BIAS = "LONG_BIAS"
    SHORT_BIAS = "SHORT_BIAS"
    NO_PROPOSAL = "NO_PROPOSAL"
    DEFER = "DEFER"


class CandidateReviewTier(StrEnum):
    """Aggregator path selected by the deterministic candidate router."""

    NORMAL = "NORMAL"
    CONFLICT = "CONFLICT"


class EntryPolicy(StrEnum):
    """Deterministic runtime entry semantics owned by the strategy contract."""

    NEXT_BAR_MARKET = "NEXT_BAR_MARKET"


class TradingMode(StrEnum):
    """Execution authority; legacy booleans must never be mapped to LIVE."""

    DRY_RUN = "DRY_RUN"
    PAPER = "PAPER"
    LIVE = "LIVE"


class EvedexProfile(StrEnum):
    """Official EVEDEX deployment profiles."""

    DEV = "DEV"
    DEMO = "DEMO"
    PROD = "PROD"


class TradeLifecycleState(StrEnum):
    """Durable state machine for a protected PAPER trade."""

    RECEIVED = "RECEIVED"
    ENTRY_PENDING = "ENTRY_PENDING"
    PROTECTING = "PROTECTING"
    ACTIVE = "ACTIVE"
    EXITING_STOP = "EXITING_STOP"
    EXITING_TARGET = "EXITING_TARGET"
    EXITING_TIMEOUT = "EXITING_TIMEOUT"
    EXITING_EMERGENCY = "EXITING_EMERGENCY"
    FLAT = "FLAT"
    CANCELLED = "CANCELLED"
    FAILED_BLOCKED = "FAILED_BLOCKED"


class TradeExecutionEventType(StrEnum):
    """Append-only facts that move a trade through its lifecycle."""

    DECISION_RECEIVED = "DECISION_RECEIVED"
    EFFECT_PREPARED = "EFFECT_PREPARED"
    VENUE_ACK = "VENUE_ACK"
    ENTRY_PARTIAL_FILL = "ENTRY_PARTIAL_FILL"
    ENTRY_FILLED = "ENTRY_FILLED"
    ENTRY_CANCELLED = "ENTRY_CANCELLED"
    STOP_CREATED = "STOP_CREATED"
    STOP_RECONCILED = "STOP_RECONCILED"
    TARGET_CREATED = "TARGET_CREATED"
    TARGET_RECONCILED = "TARGET_RECONCILED"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    EXIT_FILLED = "EXIT_FILLED"
    RECONCILIATION = "RECONCILIATION"
    RECOVERY_BLOCKED = "RECOVERY_BLOCKED"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"
    FAILED = "FAILED"


class OrderRole(StrEnum):
    """Stable role of an order in one trade lineage."""

    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIMEOUT_EXIT = "TIMEOUT_EXIT"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"


class TradeExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIMEOUT = "TIMEOUT"
    EMERGENCY = "EMERGENCY"
    CANCELLED = "CANCELLED"

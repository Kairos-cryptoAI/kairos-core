"""Enumerations shared across the whole system.

Using ``str`` mixin enums keeps the wire format human-readable (the values are
exactly what appears in the JSON on the bus) while still giving us type safety
inside Python.
"""
from __future__ import annotations

from enum import Enum


class ReasoningEffort(str, Enum):
    """Logical analysis depth, mapped to a concrete provider+model in :mod:`kairos-llm`.

    DeepSeek-first + GPT escalation:
      * ``LOW``    — DeepSeek-V4-Flash, non-thinking (Text Scouts; no reasoning effort).
      * ``MEDIUM`` — DeepSeek-V4-Pro (Aggregator, calm market).
      * ``HIGH``   — GPT-5.5, ``reasoning.effort=high`` (Aggregator, signal conflict).
      * ``XHIGH``  — GPT-5.5, ``reasoning.effort=xhigh`` (Macro-Strategist).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class RouterMode(str, Enum):
    """Flag emitted by the Router selecting the Aggregator analytics contour.

    DeepSeek-first + GPT escalation:
      * ``ROUTE_PRO`` — routine flow on DeepSeek-V4-Pro (calm market, signals agree).
      * ``ROUTE_GPT`` — escalation to GPT-5.5 (signal conflict, high cost of error).
    """

    ROUTE_PRO = "ROUTE_PRO"
    ROUTE_GPT = "ROUTE_GPT"


class SystemMode(str, Enum):
    """Global operating mode, owned by the Risk Manager / Circuit Breaker.

    Per-model Circuit Breaker degradation (severity increases downward):
      * ``NORMAL`` — all analytics layers healthy.
      * ``TEXT_LOCAL_FILTER`` — DeepSeek-V4-Flash down; Text Scouts filter locally.
      * ``CONFLICT_SAFE`` — GPT-5.5 down; conflict decisions forced to WAIT_CONFIRMATION.
      * ``LOCAL_QUANT_MODE`` — several models down; local stop-loss scripts only.
    """

    NORMAL = "NORMAL"
    TEXT_LOCAL_FILTER = "TEXT_LOCAL_FILTER"
    CONFLICT_SAFE = "CONFLICT_SAFE"
    LOCAL_QUANT_MODE = "LOCAL_QUANT_MODE"


class Side(str, Enum):
    """Directional bias of a signal or an open position."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderSide(str, Enum):
    """Side of a concrete exchange order."""

    BUY = "BUY"
    SELL = "SELL"


class ImpactDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MarketRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    CHOP = "CHOP"  # hard sideways / flat


class TacticalStatus(str, Enum):
    """High-level tactical state produced by the Aggregator."""

    STABLE_TREND_ENTRY = "STABLE_TREND_ENTRY"
    HOLD_GRID = "HOLD_GRID"
    SHIFT_GRID = "SHIFT_GRID"
    WAIT_CONFIRMATION = "WAIT_CONFIRMATION"
    REDUCE_LEVERAGE = "REDUCE_LEVERAGE"
    EXIT = "EXIT"


class ReasonCode(str, Enum):
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


class StrategicTrigger(str, Enum):
    SCHEDULE = "schedule"
    SHOCK_EVENT = "shock_event"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"  # default for limit orders
    IOC = "IOC"  # default for market orders
    FOK = "FOK"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

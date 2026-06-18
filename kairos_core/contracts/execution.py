"""Execution-side contracts (Layers 5 and 6)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from ..enums import OrderSide, OrderStatus, OrderType, ReasonCode, TimeInForce
from .base import KairosMessage


class OrderIntent(KairosMessage):
    """A desired order BEFORE risk validation."""

    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0, description="Required for LIMIT / STOP_LIMIT.")
    stop_price: Optional[float] = Field(None, gt=0)
    leverage: float = Field(1.0, gt=0, le=125)
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    reason_code: ReasonCode


class ValidatedOrder(KairosMessage):
    """An order AFTER the Risk Manager has approved (and possibly mutated) it."""

    intent: OrderIntent
    approved: bool
    reason_code: ReasonCode
    adjustments: List[str] = Field(default_factory=list, description="e.g. 'leverage capped 10x -> 5x'")
    risk_notes: str = ""


class ExecutionReport(KairosMessage):
    client_order_id: str
    exchange_order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    status: OrderStatus
    filled_qty: float = Field(0.0, ge=0)
    avg_price: float = Field(0.0, ge=0)
    fees_usd: float = Field(0.0, ge=0)
    message: str = ""

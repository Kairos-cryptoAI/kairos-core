"""Execution-side contracts (Layers 5 and 6)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field

from .base import utcnow

from ..enums import OrderSide, OrderStatus, OrderType, ReasonCode, TimeInForce
from .base import KairosMessage


class OrderIntent(KairosMessage):
    """A desired order BEFORE risk validation."""

    client_order_id: Optional[str] = Field(
        default=None, min_length=8, max_length=64,
        description="Stable idempotency key assigned before exchange submission.",
    )
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
    client_order_id: str = Field(..., min_length=1, max_length=64)
    exchange_order_id: Optional[str] = None
    exchange: str = ""
    symbol: str
    side: OrderSide
    status: OrderStatus
    requested_qty: float = Field(0.0, ge=0)
    filled_qty: float = Field(0.0, ge=0)
    remaining_qty: float = Field(0.0, ge=0)
    avg_price: float = Field(0.0, ge=0)
    fees_usd: float = Field(0.0, ge=0)
    exchange_created_at: Optional[datetime] = None
    exchange_updated_at: datetime = Field(default_factory=utcnow)
    rejection_code: Optional[str] = None
    retryable: bool = False
    message: str = ""

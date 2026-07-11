"""Authoritative exchange account and position snapshots."""
from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import KairosMessage, utcnow


class PositionSnapshot(KairosMessage):
    exchange: str
    account_id: str
    symbol: str
    signed_quantity: float = 0.0
    entry_price: float | None = Field(default=None, gt=0)
    mark_price: float | None = Field(default=None, gt=0)
    leverage: float = Field(default=1.0, gt=0)
    liquidation_price: float | None = Field(default=None, gt=0)
    unrealized_pnl_usd: float = 0.0
    protective_stop_order_id: str | None = None
    captured_at: datetime = Field(default_factory=utcnow)


class AccountSnapshot(KairosMessage):
    exchange: str
    account_id: str
    equity_usd: float = Field(..., gt=0)
    available_balance_usd: float = Field(..., ge=0)
    margin_used_usd: float = Field(default=0.0, ge=0)
    peak_equity_usd: float = Field(..., gt=0)
    daily_pnl_pct: float = 0.0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    positions: list[PositionSnapshot] = Field(default_factory=list)
    open_order_ids: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=utcnow)
    reconciled: bool = False
    reconciliation_detail: str = ""

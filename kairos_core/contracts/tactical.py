"""Aggregator output — a concrete tactical command (Layer 3)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..enums import ReasonCode, ReasoningEffort, Side, TacticalStatus
from .base import KairosMessage


class GridAdjustment(BaseModel):
    """Parameters to nudge the hard-coded grid strategy."""

    recenter: bool = False
    shift_pct: float = Field(0.0, description="Shift grid center by this fraction of price.")
    lower_price: Optional[float] = Field(None, gt=0)
    upper_price: Optional[float] = Field(None, gt=0)
    levels: Optional[int] = Field(None, gt=0)


class TacticalCommand(KairosMessage):
    symbol: str
    reference_price: float = Field(0.0, ge=0, description="Snapshot mid-price used for risk sizing.")
    status: TacticalStatus
    reason_code: ReasonCode
    target_side: Side = Side.FLAT
    requested_leverage: float = Field(1.0, gt=0, le=125)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    grid: Optional[GridAdjustment] = None
    effort_used: ReasoningEffort = ReasoningEffort.MEDIUM
    rationale: str = ""

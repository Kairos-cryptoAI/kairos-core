"""Router output — how much analytical effort the Aggregator should spend."""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from ..enums import ReasoningEffort, RouterMode, Side
from .base import KairosMessage


class RouterDecision(KairosMessage):
    symbol: str
    mode: RouterMode
    requested_effort: ReasoningEffort
    conflict_streak: int = Field(0, ge=0)
    calm_streak: int = Field(0, ge=0)
    quant_bias: Side = Side.FLAT
    text_bias: Side = Side.FLAT
    rationale: str = ""
    snapshot_id: Optional[str] = None
    sentiment_ids: List[str] = Field(default_factory=list)

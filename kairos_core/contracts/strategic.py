"""Macro-Strategist output — strategic capital allocation (Layer 4)."""
from __future__ import annotations

from typing import Dict

from pydantic import Field, model_validator

from ..enums import MarketRegime, StrategicTrigger
from .base import KairosMessage


class StrategicAllocation(KairosMessage):
    regime: MarketRegime
    stable_reserve_pct: float = Field(..., ge=0.0, le=1.0, description="Fraction parked in stablecoins.")
    strategy_weights: Dict[str, float] = Field(
        default_factory=dict, description="strategy_name -> weight in [0,1]"
    )
    max_gross_leverage: float = Field(2.0, gt=0, le=20)
    triggered_by: StrategicTrigger = StrategicTrigger.SCHEDULE
    rationale: str = ""

    @model_validator(mode="after")
    def _check_weights(self) -> "StrategicAllocation":
        total = self.stable_reserve_pct + sum(self.strategy_weights.values())
        if total > 1.0001:
            raise ValueError(f"stable_reserve_pct + strategy_weights must be <= 1.0 (got {total:.4f})")
        return self

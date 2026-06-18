"""Text Scouts output — structured sentiment distilled from news / social."""
from __future__ import annotations

from typing import List

from pydantic import Field

from ..enums import ImpactDirection
from .base import KairosMessage


class SentimentSignal(KairosMessage):
    topic: str = Field(..., description="Short topic label, e.g. 'SEC ETF'.")
    sentiment: float = Field(..., ge=-1.0, le=1.0, description="-1 very bearish ... +1 very bullish")
    impact: ImpactDirection
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    sources: List[str] = Field(default_factory=list, description="URLs / handles backing the signal.")
    summary: str = ""

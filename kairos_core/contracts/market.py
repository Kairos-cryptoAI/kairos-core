"""Quant Scouts output — a compact, pre-digested snapshot of the market.

This is the only numeric payload the upper layers ever see. Raw order-book
streams and tick data never leave Layer 1.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..enums import Side
from .base import KairosMessage


class OrderBookSummary(BaseModel):
    best_bid: float = Field(..., gt=0)
    best_ask: float = Field(..., gt=0)
    spread_bps: float = Field(..., ge=0, description="(ask-bid)/mid in basis points")
    imbalance: float = Field(
        ..., ge=-1.0, le=1.0, description="(bidVol-askVol)/(bidVol+askVol) over top N levels"
    )
    depth_usd: float = Field(..., ge=0, description="Notional resting within +/- band")


class DerivativesMetrics(BaseModel):
    funding_rate: float = Field(..., description="Current funding rate (fraction, e.g. 0.0001 = 1bp)")
    open_interest: float = Field(..., ge=0)
    oi_change_pct_1h: float = 0.0
    long_liquidations_usd: float = Field(0.0, ge=0)
    short_liquidations_usd: float = Field(0.0, ge=0)


class TechnicalIndicators(BaseModel):
    rsi_14: float = Field(..., ge=0, le=100)
    macd: float
    macd_signal: float
    macd_hist: float
    atr_pct: Optional[float] = Field(None, ge=0, description="ATR as fraction of price")


class MarketSnapshot(KairosMessage):
    symbol: str
    timeframe: str = "1m"
    mid_price: float = Field(..., gt=0)
    volume_usd: float = Field(..., ge=0)
    order_book: OrderBookSummary
    derivatives: DerivativesMetrics
    indicators: TechnicalIndicators
    quant_bias: Side = Field(Side.FLAT, description="Pure-math directional bias derived from indicators.")

"""Round-trip and validation tests for the message contracts."""
import pytest
from pydantic import ValidationError

from kairos_core import (
    MarketSnapshot,
    OrderBookSummary,
    DerivativesMetrics,
    TechnicalIndicators,
    SentimentSignal,
    StrategicAllocation,
)
from kairos_core.enums import ImpactDirection, MarketRegime, Side


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        source="quant-scouts",
        symbol="BTCUSD",
        mid_price=65000.0,
        volume_usd=1_250_000.0,
        order_book=OrderBookSummary(best_bid=64999.5, best_ask=65000.5, spread_bps=0.15, imbalance=0.12, depth_usd=500_000),
        derivatives=DerivativesMetrics(funding_rate=0.0001, open_interest=1.2e9, oi_change_pct_1h=0.8),
        indicators=TechnicalIndicators(rsi_14=58.4, macd=12.0, macd_signal=9.5, macd_hist=2.5),
        quant_bias=Side.LONG,
    )


def test_snapshot_round_trip():
    snap = _snapshot()
    raw = snap.to_json()
    again = MarketSnapshot.from_json(raw)
    assert again.symbol == "BTCUSD"
    assert again.quant_bias is Side.LONG
    assert again.message_id == snap.message_id


def test_sentiment_matches_spec_example():
    sig = SentimentSignal(source="text-scouts", topic="SEC ETF", sentiment=0.85, impact=ImpactDirection.BULLISH)
    payload = sig.to_payload()
    assert payload["topic"] == "SEC ETF"
    assert payload["sentiment"] == 0.85
    assert payload["impact"] == "bullish"


def test_sentiment_bounds_enforced():
    with pytest.raises(ValidationError):
        SentimentSignal(source="text-scouts", topic="x", sentiment=1.5, impact=ImpactDirection.BULLISH)


def test_allocation_weights_cannot_exceed_one():
    with pytest.raises(ValidationError):
        StrategicAllocation(
            source="macro",
            regime=MarketRegime.BULL,
            stable_reserve_pct=0.6,
            strategy_weights={"grid": 0.3, "trend": 0.3},
        )


def test_llm_health_event_round_trip_and_outage_flag():
    from kairos_core.contracts import LLMHealthEvent
    bad = LLMHealthEvent(source="text-scouts", provider="deepseek",
                         model="deepseek-v4-flash", ok=False, kind="timeout", latency_s=20.0)
    again = LLMHealthEvent.from_json(bad.to_json())
    assert again.model == "deepseek-v4-flash"
    assert again.is_outage is True
    healthy = LLMHealthEvent(source="aggregator", provider="openai", model="gpt-5.5", ok=True)
    assert healthy.is_outage is False
    bad_output = LLMHealthEvent(source="x", provider="openai", model="gpt-5.5", ok=False, kind="error")
    assert bad_output.is_outage is False  # API answered -> must not trip the breaker

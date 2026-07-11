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
    TacticalCommand,
)
from kairos_core.enums import ImpactDirection, MarketRegime, ReasonCode, Side, TacticalStatus


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        source="quant-scouts",
        symbol="BTCUSD",
        mid_price=65000.0,
        volume_usd=1_250_000.0,
        order_book=OrderBookSummary(
            best_bid=64999.5, best_ask=65000.5, spread_bps=0.15, imbalance=0.12, depth_usd=500_000
        ),
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
    sig = SentimentSignal(
        source="text-scouts", topic="SEC ETF", sentiment=0.85, impact=ImpactDirection.BULLISH
    )
    payload = sig.to_payload()
    assert payload["topic"] == "SEC ETF"
    assert payload["sentiment"] == 0.85
    assert payload["impact"] == "bullish"


def test_sentiment_bounds_enforced():
    with pytest.raises(ValidationError):
        SentimentSignal(source="text-scouts", topic="x", sentiment=1.5, impact=ImpactDirection.BULLISH)


def test_message_schema_minor_and_correlation_are_backward_compatible():
    legacy = SentimentSignal.model_validate({
        "schema_version": "1.0", "source": "text", "topic": "ETF",
        "sentiment": 0.2, "impact": "bullish",
    })
    assert legacy.correlation_id is None
    upgraded = SentimentSignal.model_validate({
        **legacy.to_payload(), "schema_version": "1.9",
        "correlation_id": "trace-1", "causation_id": "parent-1", "future_field": "ignored",
    })
    assert upgraded.correlation_id == "trace-1"
    assert upgraded.causation_id == "parent-1"


@pytest.mark.parametrize("version", ["2.0", "bad", "1", "0.1", "1.-1"])
def test_message_rejects_incompatible_or_malformed_schema(version):
    with pytest.raises(ValidationError):
        SentimentSignal(
            schema_version=version, source="text", topic="ETF",
            sentiment=0.2, impact=ImpactDirection.BULLISH,
        )


def test_tactical_command_reference_price_is_backward_compatible_and_bounded():
    legacy = TacticalCommand(
        source="aggregator", symbol="BTCUSDT", status=TacticalStatus.WAIT_CONFIRMATION,
        reason_code=ReasonCode.NO_TRADE,
    )
    assert legacy.reference_price == 0.0
    with pytest.raises(ValidationError):
        TacticalCommand(
            source="aggregator", symbol="BTCUSDT", reference_price=-1.0,
            status=TacticalStatus.WAIT_CONFIRMATION, reason_code=ReasonCode.NO_TRADE,
        )


def test_execution_contract_additions_are_backward_compatible():
    from kairos_core.contracts import ExecutionReport, OrderIntent
    from kairos_core.enums import OrderSide, OrderStatus, OrderType

    legacy_intent = OrderIntent(
        source="risk", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, quantity=0.1, price=65_000,
        reason_code=ReasonCode.ENTER_LONG_TREND,
    )
    assert legacy_intent.client_order_id is None
    report = ExecutionReport(
        source="execution", client_order_id="client-123", symbol="BTCUSDT",
        side=OrderSide.BUY, status=OrderStatus.PARTIALLY_FILLED,
        requested_qty=0.1, filled_qty=0.04, remaining_qty=0.06,
    )
    assert report.remaining_qty == pytest.approx(0.06)
    assert report.exchange_updated_at.tzinfo is not None


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

"""Pure contract checks: no bus, database, provider or frozen evaluator."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kairos_core.contracts import CandidateRouteV1, ClosedBarEventV1, SentimentSignal, StrategyIntentV1
from kairos_core.contracts.base import canonical_json_bytes, canonical_sha256, datetime_from_unix_ms
from kairos_core.contracts.decision_context import (
    DecisionContextReceiptV1,
    DecisionContextSourceV1,
    DecisionContextV1,
)
from kairos_core.enums import CandidateReviewTier, ImpactDirection, ReasoningEffort, Side
from kairos_core.topics import Topics

OPEN_MS = 1_800_000_000_000
EVENT_MS = OPEN_MS + 59_999
RECEIVED_MS = EVENT_MS + 10


def _bar() -> ClosedBarEventV1:
    return ClosedBarEventV1(
        source="quant-scouts",
        symbol="BTCUSDT",
        open_time_ms=OPEN_MS,
        close_time_ms=EVENT_MS,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        base_volume=10.0,
        quote_volume=1_000.0,
        taker_buy_base_volume=5.0,
        taker_buy_quote_volume=500.0,
    )


def _text(topic="BTCUSDT") -> SentimentSignal:
    return SentimentSignal(
        source="text-scouts",
        message_id="exact-text",
        produced_at=datetime_from_unix_ms(EVENT_MS - 1_000),
        topic=topic,
        sentiment=0.8,
        impact=ImpactDirection.BULLISH,
        confidence=0.9,
        sources=["https://example.invalid/source"],
        summary="Untrusted exact source text",
    )


def _route(*, has_text=False) -> CandidateRouteV1:
    intent = StrategyIntentV1(
        source="strategy-engine",
        strategy_id="context-contract",
        strategy_revision="test-1",
        symbol="BTCUSDT",
        side=Side.LONG,
        decision_ts_ms=EVENT_MS,
        entry_eligible_ts_ms=OPEN_MS + 60_000,
        entry_expires_ts_ms=OPEN_MS + 120_000,
        reference_price=100.0,
        signal_strength=0.8,
        gross_reward_bps=500.0,
        exit_plan={"stop_price": 95.0, "target_price": 105.0, "max_holding_ms": 180_000},
        provenance={
            "strategy_code_sha256": "a" * 64,
            "config_sha256": "b" * 64,
            "input_window_sha256": "c" * 64,
            "features_sha256": "d" * 64,
            "input_bar_sha256s": (_bar().bar_sha256,),
        },
    )
    return CandidateRouteV1(
        source="router",
        intent=intent,
        review_tier=CandidateReviewTier.NORMAL,
        requested_reasoning_effort=ReasoningEffort.MEDIUM,
        routed_at_ms=EVENT_MS,
        review_deadline_ms=EVENT_MS + 20_000,
        evidence_ids=("exact-text",) if has_text else (),
    )


def _source(kind, message, topic) -> DecisionContextSourceV1:
    produced = int(message.produced_at.timestamp() * 1_000)
    return DecisionContextSourceV1(
        kind=kind,
        availability="AVAILABLE",
        payloads_json=canonical_json_bytes({"items": [message.to_payload()]}).decode(),
        receipts=(
            DecisionContextReceiptV1(
                message_id=message.message_id,
                source=message.source,
                topic=topic,
                content_sha256=canonical_sha256(message),
                produced_at_ms=produced,
                event_at_ms=message.close_time_ms if isinstance(message, ClosedBarEventV1) else produced,
                received_at_ms=RECEIVED_MS,
                ttl_ms=120_000,
            ),
        ),
    )


def _context(*, text=None) -> DecisionContextV1:
    route = _route(has_text=text is not None)
    return DecisionContextV1(
        source="candidate-review",
        produced_at=datetime_from_unix_ms(RECEIVED_MS),
        route_id=route.route_id,
        intent_id=route.intent.intent_id,
        route_identity_json=canonical_json_bytes(route.identity_payload()).decode(),
        intent_identity_json=route.intent.canonical_intent_bytes().decode(),
        symbol=route.intent.symbol,
        event_as_of_ms=EVENT_MS,
        knowledge_cutoff_ms=RECEIVED_MS,
        captured_at_ms=RECEIVED_MS,
        review_deadline_ms=route.review_deadline_ms,
        maximum_closed_bars=60,
        required_sources=("market", "closed_bars", "text") if text is not None else ("market", "closed_bars"),
        sources=(
            DecisionContextSourceV1(kind="market", availability="UNAVAILABLE", reason_code="MISSING"),
            _source("closed_bars", _bar(), Topics.CLOSED_BAR),
            _source("text", text, Topics.SENTIMENT_SIGNAL)
            if text is not None
            else DecisionContextSourceV1(
                kind="text",
                availability="UNAVAILABLE",
                reason_code="NO_REFERENCED_TEXT",
            ),
            DecisionContextSourceV1(kind="macro", availability="UNAVAILABLE", reason_code="MISSING"),
        ),
    )


def test_exact_identity_optional_unknowns_tail_and_deep_immutability() -> None:
    context = _context(text=_text())
    context.validate_for_route(_route(has_text=True))
    assert context.context_id == canonical_sha256(context.identity_payload())
    assert context.closed_bar_scope == "DECLARED_INPUT_TAIL"
    assert context.missing_required_sources()[0].kind == "market"
    assert context.evidence_references()[0].content_sha256 == canonical_sha256(context)
    decoded = context.sources[2].payloads()[0]
    decoded["sources"].append("invented")
    assert context.sources[2].payloads()[0]["sources"] == ["https://example.invalid/source"]
    with pytest.raises(ValidationError):
        context.sources[2].receipts[0].received_at_ms = 0


def test_omitted_producer_timestamp_defaults_to_exact_capture_not_current_wall_clock() -> None:
    raw = _context().to_payload()
    del raw["produced_at"]
    assert DecisionContextV1.model_validate(raw).produced_at == datetime_from_unix_ms(RECEIVED_MS)


@pytest.mark.parametrize("change", ["hash", "late_receipt", "future_production", "wrong_topic", "stale"])
def test_source_receipt_tampering_cannot_reuse_context_identity(change: str) -> None:
    raw = _context().to_payload()
    receipt = raw["sources"][1]["receipts"][0]
    if change == "hash":
        receipt["content_sha256"] = "f" * 64
    elif change == "late_receipt":
        receipt["received_at_ms"] = RECEIVED_MS + 1
    elif change == "future_production":
        receipt["produced_at_ms"] = RECEIVED_MS + 1
    elif change == "wrong_topic":
        receipt["topic"] = Topics.SENTIMENT_SIGNAL
    else:
        receipt["ttl_ms"] = 1
    with pytest.raises(ValidationError):
        DecisionContextV1.model_validate(raw)


def test_direct_context_rejects_backdated_late_source_even_with_new_content_hash() -> None:
    raw = _context().to_payload()
    raw["context_id"] = None
    raw["sources"][1]["receipts"][0]["received_at_ms"] = RECEIVED_MS + 1
    with pytest.raises(ValidationError, match="not available"):
        DecisionContextV1.model_validate(raw)


def test_event_cut_is_not_extended_by_later_receive_clock() -> None:
    raw = _context(text=_text()).to_payload()
    text_source = raw["sources"][2]
    payload = json.loads(text_source["payloads_json"])["items"][0]
    later = EVENT_MS + 1
    payload["produced_at"] = datetime_from_unix_ms(later).isoformat().replace("+00:00", "Z")
    text_source["payloads_json"] = canonical_json_bytes({"items": [payload]}).decode()
    text_source["receipts"][0].update(
        content_sha256=canonical_sha256(payload),
        produced_at_ms=later,
        event_at_ms=later,
    )
    raw["context_id"] = None
    with pytest.raises(ValidationError, match="postdates"):
        DecisionContextV1.model_validate(raw)


@pytest.mark.parametrize("topic", ["ETHUSDT", "ABCUSDT", "ethusdt", "ETHUSDT "])
def test_direct_typed_context_cannot_supply_another_explicit_pair_text_topic(topic: str) -> None:
    with pytest.raises(ValidationError, match="text pair topic"):
        _context(text=_text(topic=topic))


def test_context_cannot_replace_unknown_with_an_invented_neutral_payload() -> None:
    raw = _context().to_payload()
    raw["sources"][3]["payloads_json"] = '{"items":[]}'
    with pytest.raises(ValidationError, match="UNAVAILABLE"):
        DecisionContextV1.model_validate(raw)


def test_wrong_route_and_incomplete_identity_are_rejected() -> None:
    context = _context()
    with pytest.raises(ValueError, match="exact route"):
        context.validate_for_route(_route(has_text=True))
    raw = context.to_payload()
    raw["intent_identity_json"] = canonical_json_bytes({"symbol": "BTCUSDT"}).decode()
    raw["intent_id"] = canonical_sha256({"symbol": "BTCUSDT"})
    with pytest.raises(ValidationError):
        DecisionContextV1.model_validate(raw)


def test_boolean_clock_or_changed_payload_under_same_context_id_is_rejected() -> None:
    raw = _context().to_payload()
    raw["captured_at_ms"] = True
    with pytest.raises(ValidationError):
        DecisionContextV1.model_validate(raw)
    raw = _context().to_payload()
    raw["maximum_closed_bars"] = 59
    with pytest.raises(ValidationError, match="content identity"):
        DecisionContextV1.model_validate(raw)

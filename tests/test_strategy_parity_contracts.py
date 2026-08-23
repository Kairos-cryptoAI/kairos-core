"""Safety and determinism guarantees for the Strategy Parity -> PAPER route."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kairos_core import (
    CandidateReviewTier,
    CandidateReviewV1,
    CandidateRouteV1,
    ClosedBarEventV1,
    EntryPolicy,
    EvedexProfile,
    EvidenceReferenceV1,
    ExitPlanV1,
    ReasoningEffort,
    ReviewDecision,
    RiskTradeDecisionV1,
    Side,
    StrategyIntentV1,
    StrategyProvenanceV1,
    TradingMode,
    VenueQualityV1,
)

T0 = 1_800_000_000_000
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _bar(**overrides: object) -> ClosedBarEventV1:
    values: dict[str, object] = {
        "source": "quant-scouts",
        "symbol": "BTCUSDT",
        "open_time_ms": T0,
        "close_time_ms": T0 + 59_999,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "base_volume": 20.0,
        "quote_volume": 2_010.0,
        "taker_buy_base_volume": 11.0,
        "taker_buy_quote_volume": 1_110.0,
    }
    values.update(overrides)
    return ClosedBarEventV1(**values)


def _intent(**overrides: object) -> StrategyIntentV1:
    values: dict[str, object] = {
        "source": "strategy-engine",
        "strategy_id": "trend-breakout",
        "strategy_revision": "2026-08-23.1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "decision_ts_ms": T0 + 59_999,
        "entry_eligible_ts_ms": T0 + 60_000,
        "entry_expires_ts_ms": T0 + 120_000,
        "reference_price": 100.0,
        "signal_strength": 0.7,
        "gross_reward_bps": 500.0,
        "exit_plan": ExitPlanV1(stop_price=95.0, target_price=105.0, max_holding_ms=180_000),
        "provenance": StrategyProvenanceV1(
            strategy_code_sha256=SHA_A,
            config_sha256=SHA_B,
            input_window_sha256=SHA_C,
            features_sha256=SHA_D,
            input_bar_sha256s=(SHA_A, SHA_B),
        ),
        "evidence": (
            EvidenceReferenceV1(kind="feature", reference="volume-zscore", content_sha256=SHA_A),
            EvidenceReferenceV1(kind="bar", reference="last-closed", content_sha256=SHA_B),
        ),
        "metadata": (("regime", "trend"), ("setup", "breakout")),
    }
    values.update(overrides)
    return StrategyIntentV1(**values)


def _route(intent: StrategyIntentV1 | None = None, **overrides: object) -> CandidateRouteV1:
    candidate = intent or _intent()
    values: dict[str, object] = {
        "source": "router",
        "intent": candidate,
        "review_tier": CandidateReviewTier.NORMAL,
        "requested_reasoning_effort": ReasoningEffort.MEDIUM,
        "routed_at_ms": T0 + 60_100,
        "review_deadline_ms": T0 + 119_000,
        "evidence_ids": ("quant:volume", "text:official"),
    }
    values.update(overrides)
    return CandidateRouteV1(**values)


def _review(
    intent: StrategyIntentV1 | None = None,
    route: CandidateRouteV1 | None = None,
    **overrides: object,
) -> CandidateReviewV1:
    candidate = intent or _intent()
    candidate_route = route or _route(candidate)
    values: dict[str, object] = {
        "source": "aggregator",
        "route": candidate_route,
        "intent": candidate,
        "decision": ReviewDecision.ALLOW,
        "priority": 60,
        "reviewed_at_ms": T0 + 60_200,
        "reviewer": "DETERMINISTIC",
        "reason_codes": ("NO_CONFLICT",),
    }
    values.update(overrides)
    return CandidateReviewV1(**values)


def _venue(**overrides: object) -> VenueQualityV1:
    reference_mid = 100.0
    best_bid, best_ask = 100.49, 100.51
    venue_mid = (best_bid + best_ask) / 2
    values: dict[str, object] = {
        "source": "venue-gate",
        "profile": EvedexProfile.DEV,
        "symbol": "BTCUSD:DEV",
        "observed_at_ms": T0 + 60_300,
        "expires_at_ms": T0 + 65_000,
        "reference_timestamp_ms": T0 + 60_000,
        "book_timestamp_ms": T0 + 60_100,
        "reference_mid_price": reference_mid,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "venue_mid_price": venue_mid,
        "basis_bps": (venue_mid - reference_mid) / reference_mid * 10_000,
        "spread_bps": (best_ask - best_bid) / venue_mid * 10_000,
        "assessed_notional_usd": 10.051,
        "depth_usd": 5_000.0,
        "buy_slippage_bps": 1.0,
        "sell_slippage_bps": 1.2,
        "taker_fee_bps": 5.0,
        "reference_age_ms": 300,
        "book_age_ms": 200,
        "latency_ms": 80,
        "timestamp_skew_ms": 100,
        "entry_allowed": True,
    }
    values.update(overrides)
    return VenueQualityV1(**values)


def _approved_decision(**overrides: object) -> RiskTradeDecisionV1:
    intent = _intent()
    route = _route(intent)
    review = _review(intent, route)
    venue = _venue()
    quantity = 0.1
    worst_entry = venue.best_ask
    notional = quantity * worst_entry
    fees = quantity * (worst_entry + intent.exit_plan.stop_price) * venue.taker_fee_bps / 10_000
    slippage = quantity * venue.venue_mid_price * venue.buy_slippage_bps / 10_000
    worst_loss = quantity * abs(worst_entry - intent.exit_plan.stop_price) + fees + slippage
    values: dict[str, object] = {
        "source": "risk-manager",
        "intent": intent,
        "review": review,
        "venue_quality": venue,
        "approved": True,
        "decided_at_ms": T0 + 60_400,
        "entry_policy": EntryPolicy.NEXT_BAR_MARKET,
        "trading_mode": TradingMode.PAPER,
        "evedex_profile": EvedexProfile.DEV,
        "account_id": "kairos-paper-dev-01",
        "venue_symbol": "BTCUSD:DEV",
        "quantity": quantity,
        "leverage": 1.0,
        "notional_usd": notional,
        "loss_budget_usd": 1.0,
        "worst_case_loss_usd": worst_loss,
        "worst_entry_price": worst_entry,
        "estimated_fees_usd": fees,
        "estimated_slippage_usd": slippage,
        "exit_plan": intent.exit_plan,
    }
    values.update(overrides)
    return RiskTradeDecisionV1(**values)


def test_closed_bar_hash_and_full_wire_bytes_are_deterministic() -> None:
    first = _bar()
    second = _bar()
    assert first.bar_sha256 == second.bar_sha256
    assert first.canonical_bar_bytes() == second.canonical_bar_bytes()
    assert first.to_json() == second.to_json()
    assert first.message_id == first.bar_sha256
    assert first.produced_at.timestamp() == pytest.approx((T0 + 59_999) / 1_000)


@pytest.mark.parametrize("field,value", [("open", math.nan), ("quote_volume", math.inf)])
def test_closed_bar_rejects_non_finite_numbers(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _bar(**{field: value})


@pytest.mark.parametrize(
    "override",
    [
        {"close_time_ms": T0 + 60_000},
        {"low": 101.5},
        {"taker_buy_base_volume": 21.0},
        {"bar_sha256": "0" * 64},
        {"unknown": True},
    ],
)
def test_closed_bar_rejects_bad_timing_geometry_hash_and_unknown_fields(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _bar(**override)


def test_intent_id_is_stable_across_input_order_and_round_trip() -> None:
    first = _intent()
    second = _intent(
        evidence=tuple(reversed(first.evidence)),
        metadata=tuple(reversed(first.metadata)),
    )
    assert first.intent_id == second.intent_id
    assert first.canonical_intent_bytes() == second.canonical_intent_bytes()
    assert first.to_json() == second.to_json()
    assert StrategyIntentV1.from_json(first.to_json()) == first
    assert first.message_id == first.intent_id


@pytest.mark.parametrize(
    "override",
    [
        {"side": Side.FLAT},
        {"entry_eligible_ts_ms": T0 + 59_999},
        {"entry_expires_ts_ms": T0 + 59_000},
        {"exit_plan": ExitPlanV1(stop_price=101, target_price=105, max_holding_ms=1)},
        {"reference_price": math.inf},
        {"intent_id": "0" * 64},
        {"metadata": (("duplicate", "one"), ("duplicate", "two"))},
    ],
)
def test_intent_rejects_invalid_geometry_expiry_hash_and_nonfinite(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _intent(**override)


def test_candidate_route_is_candidate_specific_and_bounded() -> None:
    intent = _intent()
    normal = _route(intent)
    assert normal.intent_sha256 == intent.intent_id
    assert normal.evidence_ids == ("quant:volume", "text:official")
    with pytest.raises(ValidationError):
        _route(intent, intent_sha256="0" * 64)
    with pytest.raises(ValidationError):
        _route(intent, requested_reasoning_effort=ReasoningEffort.HIGH)
    conflict = _route(
        intent,
        review_tier=CandidateReviewTier.CONFLICT,
        requested_reasoning_effort=ReasoningEffort.HIGH,
        conflict_rationale="quant and official news disagree",
    )
    assert conflict.review_tier is CandidateReviewTier.CONFLICT


def test_candidate_review_cannot_swap_or_mutate_the_routed_intent() -> None:
    intent = _intent()
    route = _route(intent)
    review = _review(intent, route)
    assert review.intent_sha256 == intent.intent_id
    assert review.route.route_id == route.route_id
    with pytest.raises(ValidationError):
        _review(_intent(strategy_revision="different"), route)
    with pytest.raises(ValidationError):
        _review(intent, route, intent_sha256="0" * 64)
    with pytest.raises(ValidationError):
        _review(intent, route, reviewed_at_ms=route.review_deadline_ms + 1)


def test_venue_quality_hashes_complete_executable_economics() -> None:
    venue = _venue()
    assert venue.measurement_id
    assert venue.depth_usd >= venue.assessed_notional_usd
    with pytest.raises(ValidationError):
        _venue(best_ask=100.7)
    with pytest.raises(ValidationError):
        _venue(entry_allowed=True, depth_usd=1.0)
    blocked = _venue(entry_allowed=False, reason_codes=("STALE_BOOK",))
    assert blocked.entry_allowed is False


def test_risk_decision_uses_loss_at_stop_and_preserves_exit_plan() -> None:
    decision = _approved_decision()
    assert decision.entry_policy is EntryPolicy.NEXT_BAR_MARKET
    assert decision.worst_case_loss_usd <= decision.loss_budget_usd
    assert decision.exit_plan == decision.intent.exit_plan
    assert decision.trade_id and decision.decision_id
    with pytest.raises(ValidationError):
        _approved_decision(exit_plan=ExitPlanV1(stop_price=96, target_price=105, max_holding_ms=180_000))
    with pytest.raises(ValidationError):
        _approved_decision(worst_case_loss_usd=0.1)
    with pytest.raises(ValidationError):
        _approved_decision(evedex_profile=EvedexProfile.DEMO)
    with pytest.raises(ValidationError, match="venue-assessed"):
        _approved_decision(venue_quality=_venue(assessed_notional_usd=10.0))


def test_strict_contracts_forbid_extras_and_are_immutable() -> None:
    intent = _intent()
    with pytest.raises(ValidationError):
        _intent(future_field="not understood")
    with pytest.raises(ValidationError):
        intent.reference_price = 101  # type: ignore[misc]

"""Additive observed-SIM clocks; old V1 bytes and restrictions stay frozen."""

import pytest
from pydantic import ValidationError

from kairos_core.contracts import CandidateRouteV1, ObservedSimStrategyIntentV2, StrategyIntentV1
from kairos_core.contracts.base import canonical_json_bytes, canonical_sha256, datetime_from_unix_ms
from kairos_core.contracts.decision_context import DecisionContextV1
from kairos_core.enums import CandidateReviewTier, ReasoningEffort
from tests.test_decision_context import EVENT_MS, _bar, _context
from tests.test_strategy_parity_contracts import T0, _approved_decision, _intent, _review, _route


def observed_values(**changes):
    values = _intent().identity_payload()
    metadata = {
        "hypothesis_id": "1" * 64,
        "source_set_sha256": "2" * 64,
        "entry_quote_sha256": "3" * 64,
        "evidence_kind": "CALLER_ATTESTED_POINT_IN_TIME",
        "confirmation_bar_close_ms": str(T0 + 59_999),
        "protection_sha256": canonical_sha256(
            {
                "stop_price": 95.0,
                "target_price": 105.0,
                "max_holding_ms": 180_000,
                "trailing_activation_price": None,
                "trailing_distance": None,
            }
        ),
    }
    values.update(
        source="observed-sim-test",
        contract_version="strategy-intent.observed-sim.v2",
        decision_ts_ms=T0 + 60_100,
        entry_eligible_ts_ms=T0 + 60_100,
        entry_expires_ts_ms=T0 + 62_000,
        metadata=tuple(sorted(metadata.items())),
    )
    values.update(changes)
    return values


def test_v1_exact_prechange_identity_and_default_are_unchanged():
    old = _intent()
    assert old.contract_version == "strategy-intent.v1"
    assert old.intent_id == "0e11921529f4a29b04b4f6a297e125c0d12b89fb8bc446c4a8299abe4de7d3bc"
    assert canonical_sha256(old.identity_payload()) == old.intent_id
    with pytest.raises(ValidationError, match="one-minute boundary"):
        _intent(entry_eligible_ts_ms=T0 + 60_100)


def test_v2_actual_clock_is_preserved_through_existing_typed_parser():
    observed = ObservedSimStrategyIntentV2(**observed_values())
    parsed = StrategyIntentV1.model_validate(observed.model_dump(mode="json"))
    assert parsed.canonical_intent_bytes() == observed.canonical_intent_bytes()
    assert parsed.decision_ts_ms == parsed.entry_eligible_ts_ms == T0 + 60_100
    assert parsed.contract_version == "strategy-intent.observed-sim.v2"
    assert parsed.intent_id != _intent().intent_id


@pytest.mark.parametrize(
    "key",
    [
        "hypothesis_id",
        "source_set_sha256",
        "entry_quote_sha256",
        "protection_sha256",
        "evidence_kind",
        "confirmation_bar_close_ms",
    ],
)
def test_v2_missing_binding_is_not_an_implicit_immediate_entry_permission(key):
    values = observed_values()
    values["metadata"] = tuple((k, v) for k, v in values["metadata"] if k != key)
    with pytest.raises(ValidationError, match="observed SIM"):
        ObservedSimStrategyIntentV2(**values)


@pytest.mark.parametrize("close", [str(T0 + 119_999), str(T0 - 1), "00123", "invalid"])
def test_v2_false_future_stale_or_noncanonical_confirmation_is_rejected(close):
    values = observed_values()
    values["metadata"] = tuple(
        (k, close if k == "confirmation_bar_close_ms" else v) for k, v in values["metadata"]
    )
    with pytest.raises(ValidationError, match="confirmation"):
        ObservedSimStrategyIntentV2(**values)


def test_v2_backdating_or_changed_protection_cannot_pass():
    with pytest.raises(ValidationError, match="before the decision"):
        ObservedSimStrategyIntentV2(**observed_values(entry_eligible_ts_ms=T0 + 60_000))
    values = observed_values()
    values["exit_plan"] = {**values["exit_plan"], "stop_price": 94.0}
    with pytest.raises(ValidationError, match="protection hash"):
        ObservedSimStrategyIntentV2(**values)


def test_v2_never_receives_non_sim_risk_approval_but_rejection_is_representable():
    observed = ObservedSimStrategyIntentV2(**observed_values())
    route = _route(observed, review_deadline_ms=observed.entry_expires_ts_ms)
    review = _review(observed, route)
    with pytest.raises(ValidationError, match="cannot receive a PAPER/LIVE"):
        _approved_decision(intent=observed, review=review, exit_plan=observed.exit_plan)
    rejected = _approved_decision(
        intent=observed,
        review=review,
        exit_plan=observed.exit_plan,
        approved=False,
        rejection_reasons=("OBSERVED_SIM_ONLY",),
        quantity=0.0,
        notional_usd=0.0,
        worst_case_loss_usd=0.0,
        estimated_fees_usd=0.0,
        estimated_slippage_usd=0.0,
    )
    assert not rejected.approved and rejected.quantity == 0.0


def test_v2_native_context_binds_original_confirmation_tail_not_issue_clock():
    values = observed_values()
    values["provenance"] = {**values["provenance"], "input_bar_sha256s": (_bar().bar_sha256,)}
    observed = ObservedSimStrategyIntentV2(**values)
    route = CandidateRouteV1(
        source="router",
        intent=observed,
        review_tier=CandidateReviewTier.NORMAL,
        requested_reasoning_effort=ReasoningEffort.MEDIUM,
        routed_at_ms=observed.decision_ts_ms,
        review_deadline_ms=observed.entry_expires_ts_ms,
    )
    original = _context().identity_payload()
    original.update(
        route_id=route.route_id,
        intent_id=observed.intent_id,
        route_identity_json=canonical_json_bytes(route.identity_payload()).decode(),
        intent_identity_json=observed.canonical_intent_bytes().decode(),
        event_as_of_ms=observed.decision_ts_ms,
        knowledge_cutoff_ms=observed.decision_ts_ms,
        captured_at_ms=observed.decision_ts_ms,
        review_deadline_ms=route.review_deadline_ms,
    )
    context = DecisionContextV1(
        source="context-test", produced_at=datetime_from_unix_ms(observed.decision_ts_ms), **original
    )
    context.validate_for_route(route)
    assert EVENT_MS < observed.decision_ts_ms
    # V1 still rejects the same post-bar decision clock with an otherwise valid
    # original minute-boundary eligibility; do not inherit observed-SIM semantics.
    old_values = values.copy()
    old_values.update(
        contract_version="strategy-intent.v1",
        entry_eligible_ts_ms=T0 + 120_000,
        entry_expires_ts_ms=T0 + 122_000,
    )
    old = StrategyIntentV1(**old_values)
    old_route = CandidateRouteV1(
        source="router",
        intent=old,
        review_tier=CandidateReviewTier.NORMAL,
        requested_reasoning_effort=ReasoningEffort.MEDIUM,
        routed_at_ms=old.decision_ts_ms,
        review_deadline_ms=old.entry_expires_ts_ms,
    )
    original.update(
        route_id=old_route.route_id,
        intent_id=old.intent_id,
        route_identity_json=canonical_json_bytes(old_route.identity_payload()).decode(),
        intent_identity_json=old.canonical_intent_bytes().decode(),
        review_deadline_ms=old_route.review_deadline_ms,
    )
    with pytest.raises(ValidationError, match="exact strategy decision bar"):
        DecisionContextV1(source="context-test", **original)

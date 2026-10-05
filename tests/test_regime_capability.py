"""Offline contracts only: fixture capabilities are not strategy promotions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kairos_core.contracts import StrategicAllocation
from kairos_core.contracts.regime_capability import (
    CapabilityRegime,
    RegimeBoundAllocationV1,
    RegimeCapabilityPolicyV1,
    RegimeCapitalBasisV1,
    RegimeObservationV1,
    StrategyRegimeCapabilityV1,
    validate_policy_binding,
)
from kairos_core.enums import MarketRegime, Side
from tests.test_strategy_parity_contracts import SHA_A, SHA_B, SHA_C, SHA_D, T0, _intent


def _policy() -> RegimeCapabilityPolicyV1:
    return RegimeCapabilityPolicyV1(
        source_set_sha256=SHA_C,
        observation_source="engineering-detector-fixture",
        detector_code_sha256=SHA_D,
        detector_config_sha256=SHA_A,
        capabilities=(
            StrategyRegimeCapabilityV1(
                strategy_id="engineering-range-fixture",
                strategy_revision="fixture-1",
                strategy_code_sha256=SHA_A,
                config_sha256=SHA_B,
                regime=CapabilityRegime.RANGE,
                sides=(Side.LONG, Side.SHORT),
            ),
        ),
    )


def _observation(**changes: object) -> RegimeObservationV1:
    values: dict[str, object] = dict(
        source="engineering-detector-fixture",
        source_set_sha256=SHA_C,
        detector_code_sha256=SHA_D,
        detector_config_sha256=SHA_A,
        intent=_intent(strategy_id="engineering-range-fixture", strategy_revision="fixture-1"),
        regime=CapabilityRegime.RANGE,
        event_as_of_ms=T0 + 59_999,
        observed_at_ms=T0 + 60_000,
        expires_at_ms=T0 + 120_000,
    )
    values.update(changes)
    return RegimeObservationV1(**values)


def _basis(**changes: object) -> RegimeCapitalBasisV1:
    values: dict[str, object] = dict(
        allocation=StrategicAllocation(
            source="kairos-macro-strategist",
            message_id="macro:engineering-fixture",
            regime=MarketRegime.CHOP,
            stable_reserve_pct=0.5,
            strategy_weights={"engineering-range-fixture": 0.5},
            max_gross_leverage=1,
            produced_at=datetime.fromtimestamp((T0 + 59_000) / 1000, UTC),
        ),
        policy_sha256=_policy().policy_sha256,
        source_set_sha256=SHA_C,
        account_id="engineering-paper-dev",
        account_snapshot_id=SHA_B,
        account_captured_at_ms=T0 + 58_000,
    )
    values.update(changes)
    return RegimeCapitalBasisV1(**values)


def _bound() -> RegimeBoundAllocationV1:
    return RegimeBoundAllocationV1(
        source="kairos-macro-strategist",
        capital_basis=_basis(),
        observation=_observation(),
        bound_at_ms=T0 + 60_100,
    )


def test_closed_policy_canonicalizes_all_sides_and_full_mapping():
    policy = _policy()
    payload = policy.model_dump(mode="json")
    payload["capabilities"][0]["sides"].reverse()
    reordered = RegimeCapabilityPolicyV1.model_validate(payload)
    assert reordered.policy_sha256 == policy.policy_sha256
    payload["capabilities"][0]["config_sha256"] = SHA_D
    assert RegimeCapabilityPolicyV1.model_validate(payload).policy_sha256 != policy.policy_sha256
    validate_policy_binding(
        policy,
        expected_sha256=policy.policy_sha256,
        source_set_sha256=SHA_C,
        allowed_strategy_revisions={("engineering-range-fixture", "fixture-1")},
    )
    with pytest.raises(ValidationError, match="frozen"):
        policy.profile = "adaptive-research-v1"


@pytest.mark.parametrize(
    "change",
    [
        {"llm_confidence": 1},
        {"profile": "adaptive-v2"},
        {"capabilities": []},
    ],
)
def test_policy_unknown_and_malformed_fields_fail_closed(change):
    with pytest.raises(ValidationError):
        RegimeCapabilityPolicyV1.model_validate(_policy().model_dump(mode="json") | change)


@pytest.mark.parametrize(
    "change",
    [
        {"regime": "CHOP"},
        {"regime": "UNCERTAIN"},
        {"sides": ["FLAT"]},
        {"sides": ["LONG", "LONG"]},
        {"strategy_revision": "fixture 1"},
    ],
)
def test_capabilities_are_explicit_closed_directional_mappings(change):
    capability = _policy().capabilities[0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        StrategyRegimeCapabilityV1.model_validate(capability | change)


def test_independently_expected_policy_source_and_qualification_cannot_be_self_asserted():
    policy = _policy()
    for expected, source, allowed in (
        (SHA_A, SHA_C, {("engineering-range-fixture", "fixture-1")}),
        (policy.policy_sha256, SHA_D, {("engineering-range-fixture", "fixture-1")}),
        (policy.policy_sha256, SHA_C, {("engineering-range-fixture", "fixture-2")}),
    ):
        with pytest.raises(ValueError):
            validate_policy_binding(
                policy,
                expected_sha256=expected,
                source_set_sha256=source,
                allowed_strategy_revisions=allowed,
            )


def test_observation_delivery_can_follow_decision_without_backdating_market_events():
    observation = _observation()
    assert observation.event_as_of_ms == observation.intent.decision_ts_ms
    assert int(observation.produced_at.timestamp() * 1000) > observation.intent.decision_ts_ms
    _policy().validate_observation(observation)
    assert RegimeBoundAllocationV1.model_validate_json(_bound().model_dump_json()) == _bound()


@pytest.mark.parametrize(
    "change",
    [
        {"event_as_of_ms": T0 + 60_000},
        {"observed_at_ms": T0 + 120_001},
        {"expires_at_ms": T0 + 120_001},
        {"produced_at": datetime.fromtimestamp((T0 + 59_999) / 1000, UTC)},
        {"produced_at": datetime.fromtimestamp((T0 + 120_001) / 1000, UTC)},
    ],
)
def test_observation_future_events_and_invalid_actual_clocks_reject(change):
    with pytest.raises(ValidationError):
        _observation(**change)


def test_exact_detector_revision_and_intent_provenance_required():
    observation = _observation(detector_code_sha256=SHA_A)
    with pytest.raises(ValueError):
        _policy().validate_observation(observation)
    intent = _observation().intent
    changed = intent.model_dump(mode="json")
    changed.pop("intent_id")
    changed["strategy_revision"] = "fixture-2"
    with pytest.raises(ValueError):
        _policy().validate_observation(_observation(intent=changed))


def test_capital_basis_mutation_is_detected_before_any_binding_can_be_issued():
    basis = _basis()
    basis.allocation.strategy_weights["engineering-range-fixture"] = 0.4
    with pytest.raises(ValidationError, match="capital basis identity"):
        RegimeCapitalBasisV1.model_validate_json(basis.model_dump_json())


def test_nested_mutation_invalidates_full_binding_instead_of_silently_changing_budget():
    bound = _bound()
    bound.capital_basis.allocation.strategy_weights["engineering-range-fixture"] = 0.4
    with pytest.raises(ValidationError, match="capital basis identity"):
        RegimeBoundAllocationV1.model_validate_json(bound.model_dump_json())


def test_foreign_or_future_capital_cannot_be_wrapped_as_current_macro_budget():
    with pytest.raises(ValidationError, match="foreign capital producer"):
        RegimeBoundAllocationV1(
            source="foreign-macro",
            capital_basis=_basis(),
            observation=_observation(),
            bound_at_ms=T0 + 60_100,
        )
    with pytest.raises(ValidationError, match="future capital"):
        RegimeBoundAllocationV1(
            source="kairos-macro-strategist",
            capital_basis=_basis(
                allocation=StrategicAllocation(
                    source="kairos-macro-strategist",
                    regime=MarketRegime.CHOP,
                    stable_reserve_pct=1,
                    strategy_weights={},
                    produced_at=datetime.fromtimestamp((T0 + 60_000) / 1000, UTC),
                )
            ),
            observation=_observation(),
            bound_at_ms=T0 + 60_100,
        )

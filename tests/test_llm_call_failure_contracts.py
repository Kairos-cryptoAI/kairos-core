from __future__ import annotations

import pytest
from pydantic import ValidationError

from kairos_core import LLMCallFailureV1, LLMTradeProposalV1, RiskTradeDecisionV1, StrategyIntentV1

T0 = 1_760_000_000_000


def _failure(**overrides: object) -> LLMCallFailureV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-v1",
        "arm_id": "paired-observation",
        "sample_id": "sample-0001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": "a" * 64,
        "sample_deadline_ts_ms": T0 + 5_000,
        "attempt_id": "attempt-0001",
        "provider": "local",
        "requested_model": "fixture-v1",
        "prompt_sha256": "b" * 64,
        "budget_reservation_id": "fixture:reservation-1",
        "attempt_started_at_ts_ms": T0 + 100,
        "failure_observed_at_ts_ms": T0 + 1_000,
        "failure_class": "TIMEOUT",
    }
    values.update(overrides)
    return LLMCallFailureV1(**values)


def test_failure_receipt_is_stable_research_only_and_round_trips() -> None:
    failure = _failure()
    same = _failure()
    decoded = LLMCallFailureV1.from_json(failure.to_json())

    assert failure.contract_version == "llm-call-failure.v1"
    assert failure.authority == "SIM_RESEARCH_ONLY"
    assert failure.failure_receipt_id == same.failure_receipt_id == failure.message_id
    assert decoded == failure
    assert failure.canonical_failure_bytes() == decoded.canonical_failure_bytes()
    assert failure.is_late is False
    for executable in (StrategyIntentV1, RiskTradeDecisionV1, LLMTradeProposalV1):
        with pytest.raises(ValidationError):
            executable.model_validate(failure.to_payload())


def test_late_failure_remains_a_receipt_with_its_actual_observed_time() -> None:
    late = _failure(failure_observed_at_ts_ms=T0 + 6_000)

    assert late.is_late is True
    assert late.failure_observed_at_ts_ms == T0 + 6_000
    assert late.produced_at.timestamp() == pytest.approx((T0 + 6_000) / 1_000)
    assert late.failure_receipt_id != _failure().failure_receipt_id


@pytest.mark.parametrize(
    "override",
    [
        {"attempt_started_at_ts_ms": T0 - 1},
        {"attempt_started_at_ts_ms": T0 + 5_000},
        {"failure_observed_at_ts_ms": T0 + 99},
        {"sample_deadline_ts_ms": T0},
        {"failure_class": "NO_PROPOSAL"},
        {"failure_receipt_id": "0" * 64},
        {"response_sha256": "c" * 64},
        {"failure_class": "INVALID_RESPONSE"},
        {"quantity": 1},
        {"symbol": "btcusdt"},
    ],
)
def test_failure_receipt_rejects_invalid_context_timing_or_authority(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _failure(**override)


def test_invalid_response_class_links_hash_without_model_decision() -> None:
    failure = _failure(failure_class="INVALID_RESPONSE", response_sha256="c" * 64)

    assert failure.response_sha256 == "c" * 64
    assert not hasattr(failure, "action")
    assert not hasattr(failure, "proposal_id")

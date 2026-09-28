"""A completion receipt attests caller timing, not trade authority."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kairos_core import LLMProposalCompletionReceiptV1, LLMProposalModelProvenanceV1

T0 = 1_800_000_000_000


def _receipt(**overrides: object) -> LLMProposalCompletionReceiptV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": "a" * 64,
        "sample_deadline_ts_ms": T0 + 30_000,
        "attempt_id": "attempt-1",
        "proposal_id": "b" * 64,
        "model_provenance": LLMProposalModelProvenanceV1(
            provider="local",
            requested_model="fixture",
            resolved_model="fixture-v1",
            request_id="request-1",
            prompt_sha256="c" * 64,
            response_sha256="d" * 64,
            budget_reservation_id="fixture:reservation-1",
            latency_ms=100,
            cost_usd=0,
        ),
        "attempt_started_at_ts_ms": T0 + 100,
        "response_observed_at_ts_ms": T0 + 1_000,
    }
    values.update(overrides)
    return LLMProposalCompletionReceiptV1(**values)


def test_completion_receipt_is_canonical_immutable_and_round_trips() -> None:
    receipt = _receipt()
    replayed = _receipt()
    decoded = LLMProposalCompletionReceiptV1.from_json(receipt.to_json())

    assert receipt.contract_version == "llm-proposal-completion-receipt.v1"
    assert receipt.authority == "SIM_RESEARCH_ONLY"
    assert receipt.completion_receipt_id == receipt.message_id
    assert receipt.completion_receipt_id == replayed.completion_receipt_id
    assert receipt.canonical_completion_bytes() == decoded.canonical_completion_bytes()
    assert decoded == receipt
    assert receipt.produced_at.timestamp() == pytest.approx((T0 + 1_000) / 1_000)
    with pytest.raises(ValidationError):
        receipt.response_observed_at_ts_ms = T0 + 2_000


def test_observation_time_changes_identity_and_late_receipt_is_retained() -> None:
    timely = _receipt()
    late = _receipt(response_observed_at_ts_ms=T0 + 31_000)

    assert not timely.is_late
    assert late.is_late
    assert timely.completion_receipt_id != late.completion_receipt_id


@pytest.mark.parametrize(
    "override",
    [
        {"authority": "PAPER"},
        {"source": "kairos-execution-engine"},
        {"contract_version": "llm-proposal-completion-receipt.v2"},
        {"symbol": "btcusdt"},
        {"sample_deadline_ts_ms": T0},
        {"attempt_started_at_ts_ms": T0 - 1},
        {"attempt_started_at_ts_ms": T0 + 30_000},
        {"response_observed_at_ts_ms": T0 + 99},
        {"response_observed_at_ts_ms": True},
        {"attempt_id": "bad id"},
        {"proposal_id": "A" * 64},
        {"completion_receipt_id": "f" * 64},
        {"quantity": 1},
        {"venue": "EVEDEX"},
    ],
)
def test_completion_receipt_rejects_invalid_scope_timing_or_authority(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _receipt(**override)

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kairos_core import (
    LLMTradeProposalV1,
    OrderIntent,
    ResearchDecisionSampleV1,
    RiskTradeDecisionV1,
    StrategyIntentV1,
)

T0 = 1_760_000_000_000
MARKET_HASH = "a" * 64


def _sample(**overrides: object) -> ResearchDecisionSampleV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-v1",
        "arm_id": "paired-observation",
        "sample_id": "sample-0001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": MARKET_HASH,
        "paired_at_ts_ms": T0 + 1_000,
        "sample_deadline_ts_ms": T0 + 5_000,
        "strategy_id": "adaptive-baseline",
        "strategy_revision": "r1",
        "strategy_outcome": "NOT_EVALUATED",
        "llm_outcome": "NOT_CALLED",
    }
    values.update(overrides)
    return ResearchDecisionSampleV1(**values)


def _evaluated_no_intent(**overrides: object) -> ResearchDecisionSampleV1:
    return _sample(
        strategy_outcome="NO_INTENT",
        strategy_evaluation_sha256="b" * 64,
        strategy_evidence_as_of_ts_ms=T0,
        strategy_market_snapshot_sha256=MARKET_HASH,
        **overrides,
    )


def _directional_disagreement(**overrides: object) -> ResearchDecisionSampleV1:
    return _sample(
        strategy_outcome="LONG",
        strategy_evaluation_sha256="b" * 64,
        strategy_evidence_as_of_ts_ms=T0,
        strategy_market_snapshot_sha256=MARKET_HASH,
        strategy_intent_id="c" * 64,
        strategy_intent_expires_at_ts_ms=T0 + 10_000,
        llm_outcome="SHORT_BIAS",
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_proposal_id="d" * 64,
        llm_proposal_expires_at_ts_ms=T0 + 10_000,
        llm_completion_receipt_id="e" * 64,
        llm_completion_started_at_ts_ms=T0 + 100,
        llm_completion_observed_at_ts_ms=T0 + 500,
        **overrides,
    )


def test_sample_is_versioned_research_only_canonical_and_round_trips() -> None:
    sample = _directional_disagreement()
    decoded = ResearchDecisionSampleV1.from_json(sample.to_json())

    assert sample.contract_version == "research-decision-sample.v1"
    assert sample.authority == "SIM_RESEARCH_ONLY"
    assert sample.sample_record_id
    assert sample.message_id == sample.sample_record_id
    assert sample.canonical_sample_bytes() == decoded.canonical_sample_bytes()
    assert decoded == sample
    assert sample.produced_at.timestamp() == pytest.approx((T0 + 1_000) / 1_000)


def test_no_intent_is_distinct_from_not_evaluated_and_independent_of_llm() -> None:
    not_evaluated = _sample()
    no_intent = _evaluated_no_intent()
    llm_only = _sample(
        llm_outcome="LONG_BIAS",
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_proposal_id="d" * 64,
        llm_proposal_expires_at_ts_ms=T0 + 10_000,
        llm_completion_receipt_id="e" * 64,
        llm_completion_started_at_ts_ms=T0 + 100,
        llm_completion_observed_at_ts_ms=T0 + 500,
    )

    assert not_evaluated.sample_record_id != no_intent.sample_record_id
    assert no_intent.strategy_intent_id is None
    assert no_intent.strategy_evaluation_sha256 == "b" * 64
    assert llm_only.strategy_outcome == "NOT_EVALUATED"
    assert llm_only.llm_outcome == "LONG_BIAS"


@pytest.mark.parametrize("outcome", ["NO_PROPOSAL", "DEFER"])
def test_non_directional_llm_result_still_requires_a_proposal_link(outcome: str) -> None:
    sample = _sample(
        llm_outcome=outcome,
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_proposal_id="d" * 64,
        llm_completion_receipt_id="e" * 64,
        llm_completion_started_at_ts_ms=T0 + 100,
        llm_completion_observed_at_ts_ms=T0 + 500,
    )

    assert sample.llm_proposal_id == "d" * 64
    assert sample.llm_proposal_expires_at_ts_ms is None


def test_volatility_alert_and_call_failure_are_distinct_non_executable_outcomes() -> None:
    alert = _sample(
        llm_outcome="VOLATILITY_ALERT",
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_proposal_id="d" * 64,
        llm_proposal_expires_at_ts_ms=T0 + 10_000,
        llm_completion_receipt_id="e" * 64,
        llm_completion_started_at_ts_ms=T0 + 100,
        llm_completion_observed_at_ts_ms=T0 + 500,
    )
    failed = _sample(
        llm_outcome="CALL_FAILED",
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_failure_receipt_id="e" * 64,
        llm_failure_class="TIMEOUT",
        llm_failure_started_at_ts_ms=T0 + 100,
        llm_failure_observed_at_ts_ms=T0 + 500,
    )

    assert alert.llm_proposal_id and alert.llm_failure_receipt_id is None
    assert failed.llm_proposal_id is None and failed.llm_failure_receipt_id
    assert failed.sample_record_id != alert.sample_record_id
    assert ResearchDecisionSampleV1.from_json(failed.to_json()) == failed


@pytest.mark.parametrize(
    "override",
    [
        {"llm_failure_receipt_id": None},
        {"llm_failure_class": None},
        {"llm_failure_started_at_ts_ms": None},
        {"llm_failure_observed_at_ts_ms": T0 + 1_001},
        {"llm_failure_started_at_ts_ms": T0 - 1},
        {"llm_proposal_id": "f" * 64},
        {"llm_completion_receipt_id": "f" * 64},
        {"llm_evidence_as_of_ts_ms": T0 - 1},
    ],
)
def test_failed_call_requires_causal_failure_and_no_proposal(override: dict[str, object]) -> None:
    payload = _sample(
        llm_outcome="CALL_FAILED",
        llm_evidence_as_of_ts_ms=T0,
        llm_market_snapshot_sha256=MARKET_HASH,
        llm_failure_receipt_id="e" * 64,
        llm_failure_class="TIMEOUT",
        llm_failure_started_at_ts_ms=T0 + 100,
        llm_failure_observed_at_ts_ms=T0 + 500,
    ).to_payload()
    payload.update(override)
    payload.pop("sample_record_id")
    with pytest.raises(ValidationError):
        ResearchDecisionSampleV1.model_validate(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"authority": "PAPER"},
        {"source": "kairos-execution-engine"},
        {"contract_version": "research-decision-sample.v2"},
        {"symbol": "btcusdt"},
        {"market_snapshot_sha256": "A" * 64},
        {"market_as_of_ts_ms": True},
        {"sample_record_id": "0" * 64},
        {"quantity": 1},
        {"venue": "EVEDEX"},
        {"trading_mode": "LIVE"},
        {"strategy_outcome": "FLAT"},
        {"llm_outcome": "ALLOW"},
    ],
)
def test_sample_fails_closed_on_invalid_identity_or_authority(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _sample(**override)


@pytest.mark.parametrize(
    "override",
    [
        {"paired_at_ts_ms": T0 - 1},
        {"paired_at_ts_ms": T0 + 5_000},
        {"sample_deadline_ts_ms": T0},
        {"strategy_evaluation_sha256": "b" * 64},
        {"strategy_intent_id": "c" * 64},
        {"llm_proposal_id": "d" * 64},
        {"llm_completion_receipt_id": "e" * 64},
        {"llm_evidence_as_of_ts_ms": T0},
    ],
)
def test_unevaluated_paths_cannot_claim_evidence_or_miss_deadline(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _sample(**override)


@pytest.mark.parametrize(
    "override",
    [
        {"strategy_evaluation_sha256": None},
        {"strategy_evidence_as_of_ts_ms": None},
        {"strategy_evidence_as_of_ts_ms": T0 + 1},
        {"strategy_market_snapshot_sha256": "e" * 64},
        {"strategy_intent_id": "c" * 64},
        {"strategy_intent_expires_at_ts_ms": T0 + 10_000},
    ],
)
def test_no_intent_requires_receipt_and_rejects_inconsistent_evidence(override: dict[str, object]) -> None:
    payload = _evaluated_no_intent().to_payload()
    payload.update(override)
    payload.pop("sample_record_id")
    with pytest.raises(ValidationError):
        ResearchDecisionSampleV1.model_validate(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"strategy_intent_id": None},
        {"strategy_intent_expires_at_ts_ms": None},
        {"strategy_intent_expires_at_ts_ms": T0 + 1_000},
        {"llm_proposal_id": None},
        {"llm_completion_receipt_id": None},
        {"llm_completion_started_at_ts_ms": None},
        {"llm_completion_observed_at_ts_ms": None},
        {"llm_completion_started_at_ts_ms": T0 - 1},
        {"llm_completion_observed_at_ts_ms": T0 + 1_001},
        {"llm_completion_observed_at_ts_ms": T0 + 99},
        {"llm_proposal_expires_at_ts_ms": None},
        {"llm_proposal_expires_at_ts_ms": T0 + 1_000},
        {"llm_evidence_as_of_ts_ms": T0 + 1},
        {"llm_market_snapshot_sha256": "e" * 64},
    ],
)
def test_directional_paths_require_fresh_matching_lineage(override: dict[str, object]) -> None:
    payload = _directional_disagreement().to_payload()
    payload.update(override)
    payload.pop("sample_record_id")
    with pytest.raises(ValidationError):
        ResearchDecisionSampleV1.model_validate(payload)


def test_record_cannot_be_parsed_as_execution_or_existing_proposal_contract() -> None:
    payload = _directional_disagreement().to_payload()

    for contract in (StrategyIntentV1, RiskTradeDecisionV1, OrderIntent, LLMTradeProposalV1):
        with pytest.raises(ValidationError):
            contract.model_validate(payload)

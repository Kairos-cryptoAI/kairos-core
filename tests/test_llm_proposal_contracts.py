from __future__ import annotations

import pytest
from pydantic import ValidationError

from kairos_core import (
    CandidateReviewV1,
    EvidenceReferenceV1,
    LLMProposalAction,
    LLMProposalModelProvenanceV1,
    LLMTradeProposalV1,
    RiskTradeDecisionV1,
    Side,
    StrategyIntentV1,
    Topics,
)

T0 = 1_760_000_000_000


def _evidence(**overrides: object) -> EvidenceReferenceV1:
    values: dict[str, object] = {
        "kind": "closed_bar",
        "reference": "BTCUSDT:1m:1760000000000",
        "content_sha256": "4" * 64,
        "observed_at_ms": T0,
    }
    values.update(overrides)
    return EvidenceReferenceV1(**values)


def _provenance(**overrides: object) -> LLMProposalModelProvenanceV1:
    values: dict[str, object] = {
        "provider": "openai",
        "requested_model": "gpt-model-alias",
        "resolved_model": "gpt-model-snapshot",
        "system_fingerprint": "fp_example",
        "reasoning_effort": "medium",
        "request_id": "request_123",
        "prompt_sha256": "1" * 64,
        "response_sha256": "2" * 64,
        "budget_reservation_id": "kairos-llm-v1:openai:reservation_123",
        "latency_ms": 42,
        "cost_usd": 0.001,
    }
    values.update(overrides)
    return LLMProposalModelProvenanceV1(**values)


def _proposal(**overrides: object) -> LLMTradeProposalV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-campaign-v1",
        "arm_id": "llm-generated-candidates",
        "sample_id": "sample-0001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "expires_at_ts_ms": T0 + 60_000,
        "market_snapshot_sha256": "3" * 64,
        "action": LLMProposalAction.LONG_BIAS,
        "rationale": "  Closed-bar momentum and the supplied trend state agree.  ",
        "evidence": (_evidence(),),
        "model_provenance": _provenance(),
    }
    values.update(overrides)
    return LLMTradeProposalV1(**values)


def test_llm_proposal_is_versioned_canonical_and_round_trips() -> None:
    proposal = _proposal()
    decoded = LLMTradeProposalV1.from_json(proposal.to_json())

    assert proposal.contract_version == "llm-trade-proposal.v1"
    assert proposal.action is LLMProposalAction.LONG_BIAS
    assert not isinstance(proposal.action, Side)
    assert proposal.rationale == "Closed-bar momentum and the supplied trend state agree."
    assert proposal.proposal_id
    assert proposal.message_id == proposal.proposal_id
    assert proposal.canonical_proposal_bytes() == decoded.canonical_proposal_bytes()
    assert decoded == proposal
    assert proposal.produced_at.timestamp() == pytest.approx(T0 / 1_000)


@pytest.mark.parametrize(
    ("action", "expires_at_ts_ms", "evidence"),
    [
        (LLMProposalAction.NO_PROPOSAL, T0, ()),
        (LLMProposalAction.DEFER, T0, ()),
    ],
)
def test_non_candidate_actions_are_valid_without_directional_evidence(
    action: LLMProposalAction,
    expires_at_ts_ms: int,
    evidence: tuple[EvidenceReferenceV1, ...],
) -> None:
    proposal = _proposal(action=action, expires_at_ts_ms=expires_at_ts_ms, evidence=evidence)

    assert proposal.action is action
    assert proposal.evidence == ()


@pytest.mark.parametrize(
    "override",
    [
        {"expires_at_ts_ms": T0 - 1},
        {"expires_at_ts_ms": T0},
        {"evidence": ()},
        {"symbol": "btcusdt"},
        {"market_snapshot_sha256": "A" * 64},
        {"market_as_of_ts_ms": True},
        {"rationale": "   "},
    ],
)
def test_candidate_fails_closed_on_invalid_or_incomplete_evidence(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _proposal(**override)


def test_model_provenance_requires_a_budget_reservation() -> None:
    with pytest.raises(ValidationError):
        _provenance(budget_reservation_id=" ")


def test_proposal_rejects_lookahead_evidence_and_duplicate_evidence() -> None:
    with pytest.raises(ValidationError, match="after the market snapshot"):
        _proposal(evidence=(_evidence(observed_at_ms=T0 + 1),))
    with pytest.raises(ValidationError, match="requires an observation timestamp"):
        _proposal(evidence=(_evidence(observed_at_ms=None),))
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        _proposal(evidence=(_evidence(), _evidence()))


@pytest.mark.parametrize(
    "execution_field",
    ["entry_price", "stop_price", "target_price", "quantity", "leverage", "order_type", "venue"],
)
def test_proposal_forbids_execution_authority_fields(execution_field: str) -> None:
    with pytest.raises(ValidationError):
        _proposal(**{execution_field: 1})


def test_proposal_cannot_be_parsed_as_strategy_review_or_risk_decision() -> None:
    payload = _proposal().to_payload()

    with pytest.raises(ValidationError):
        StrategyIntentV1.model_validate(payload)
    with pytest.raises(ValidationError):
        CandidateReviewV1.model_validate(payload)
    with pytest.raises(ValidationError):
        RiskTradeDecisionV1.model_validate(payload)


def test_proposal_topic_is_separate_from_execution_pipeline_topics() -> None:
    execution_topics = {
        Topics.STRATEGY_INTENT,
        Topics.STRATEGY_ROUTE,
        Topics.CANDIDATE_REVIEW,
        Topics.VENUE_QUALITY,
        Topics.RISK_TRADE_DECISION,
        Topics.TRADE_EXECUTION_EVENT,
    }

    assert Topics.LLM_TRADE_PROPOSAL not in execution_topics

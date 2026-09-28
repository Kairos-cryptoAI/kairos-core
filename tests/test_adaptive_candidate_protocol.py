"""The SIM adaptive roster binds exact, non-executable arm implementations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kairos_core import (
    AdaptiveCandidateProtocolV1,
    LLMProposalAdaptiveCandidateArmV1,
    ResearchDecisionSampleV1,
    StrategyOnlyAdaptiveCandidateArmV1,
    StrategyReviewAdaptiveCandidateArmV1,
    canonical_sha256,
)


def _common(*, candidate_id: str, candidate_revision: str = "frozen-001") -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "candidate_revision": candidate_revision,
        "artifact_sha256": "a" * 64,
        "input_feature_sha256": "b" * 64,
        "decision_mapping_sha256": "c" * 64,
        "hypothetical_exit_sha256": "d" * 64,
        "cost_model_sha256": "e" * 64,
    }


def _arms() -> tuple[
    StrategyOnlyAdaptiveCandidateArmV1,
    StrategyReviewAdaptiveCandidateArmV1,
    LLMProposalAdaptiveCandidateArmV1,
]:
    return (
        StrategyOnlyAdaptiveCandidateArmV1(**_common(candidate_id="baseline")),
        StrategyReviewAdaptiveCandidateArmV1(
            **_common(candidate_id="review"),
            provider="openai",
            model="gpt-5.6-sol",
            prompt_sha256="1" * 64,
            schema_sha256="2" * 64,
        ),
        LLMProposalAdaptiveCandidateArmV1(
            **_common(candidate_id="proposal"),
            provider="deepseek",
            model="deepseek-v3.2",
            prompt_sha256="3" * 64,
            schema_sha256="4" * 64,
        ),
    )


def _protocol(**overrides: object) -> AdaptiveCandidateProtocolV1:
    payload: dict[str, object] = {
        "campaign_id": "adaptive-campaign-001",
        "schedule_digest": "5" * 64,
        "arms": _arms(),
    }
    payload.update(overrides)
    return AdaptiveCandidateProtocolV1(**payload)


def test_protocol_digest_and_arm_digests_are_canonical_and_stable() -> None:
    first = _protocol()
    second = _protocol()

    assert first.protocol_digest == canonical_sha256(first.identity_payload())
    assert second.protocol_digest == first.protocol_digest
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.arm_digest("strategy-only") == canonical_sha256(first.arms[0])
    assert first.arm_digest("strategy-review") == canonical_sha256(first.arms[1])
    assert first.arm_digest("llm-proposal-research") == canonical_sha256(first.arms[2])
    assert first.arm_digest("llm-proposal-research") == second.arm_digest("llm-proposal-research")
    with pytest.raises(ValueError, match="outside the fixed adaptive candidate roster"):
        first.arm_digest("unknown-arm")  # type: ignore[arg-type]


def test_protocol_digest_changes_with_candidate_route_or_schedule_identity() -> None:
    original = _protocol()
    revised_arms = _arms()
    revised_arms = (
        revised_arms[0],
        revised_arms[1].model_copy(update={"prompt_sha256": "f" * 64}),
        revised_arms[2],
    )
    revised = AdaptiveCandidateProtocolV1(
        campaign_id=original.campaign_id,
        schedule_digest=original.schedule_digest,
        arms=revised_arms,
    )
    other_campaign = _protocol(campaign_id="adaptive-campaign-002")
    other_schedule = _protocol(schedule_digest="6" * 64)

    assert revised.arm_digest("strategy-review") != original.arm_digest("strategy-review")
    assert revised.protocol_digest != original.protocol_digest
    assert other_campaign.protocol_digest != original.protocol_digest
    assert other_schedule.protocol_digest != original.protocol_digest


def test_protocol_rejects_wrong_digest_and_noncanonical_roster_order() -> None:
    payload = _protocol().model_dump(mode="json")
    with pytest.raises(ValidationError, match="protocol_digest"):
        AdaptiveCandidateProtocolV1.model_validate({**payload, "protocol_digest": "0" * 64})

    with pytest.raises(ValidationError):
        AdaptiveCandidateProtocolV1.model_validate({**payload, "arms": payload["arms"][:2]})
    with pytest.raises(ValidationError):
        AdaptiveCandidateProtocolV1.model_validate(
            {**payload, "arms": [payload["arms"][1], payload["arms"][0], payload["arms"][2]]}
        )
    with pytest.raises(ValidationError):
        AdaptiveCandidateProtocolV1.model_validate(
            {**payload, "arms": [payload["arms"][0], payload["arms"][0], payload["arms"][2]]}
        )


def test_strategy_only_rejects_llm_fields_and_llm_arms_require_full_route() -> None:
    strategy = _common(candidate_id="baseline")
    with pytest.raises(ValidationError, match="provider"):
        StrategyOnlyAdaptiveCandidateArmV1.model_validate({**strategy, "provider": "openai"})
    with pytest.raises(ValidationError, match="prompt_sha256"):
        StrategyOnlyAdaptiveCandidateArmV1.model_validate({**strategy, "prompt_sha256": "1" * 64})

    review = {
        **_common(candidate_id="review"),
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "prompt_sha256": "1" * 64,
        "schema_sha256": "2" * 64,
    }
    for missing_field in ("provider", "model", "prompt_sha256", "schema_sha256"):
        with pytest.raises(ValidationError):
            StrategyReviewAdaptiveCandidateArmV1.model_validate(
                {key: value for key, value in review.items() if key != missing_field}
            )
    with pytest.raises(ValidationError, match="provider"):
        StrategyReviewAdaptiveCandidateArmV1.model_validate({**review, "provider": "other-provider"})
    with pytest.raises(ValidationError):
        LLMProposalAdaptiveCandidateArmV1.model_validate(
            {**review, "arm_id": "llm-proposal-research", "provider": " "}
        )


def test_protocol_and_arms_are_closed_world_and_hashes_ids_are_strict() -> None:
    payload = _protocol().model_dump(mode="json")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AdaptiveCandidateProtocolV1.model_validate({**payload, "unexpected": True})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategyOnlyAdaptiveCandidateArmV1.model_validate({**_common(candidate_id="baseline"), "pnl": 10})
    with pytest.raises(ValidationError):
        StrategyOnlyAdaptiveCandidateArmV1(**{**_common(candidate_id="bad id")})
    with pytest.raises(ValidationError):
        StrategyReviewAdaptiveCandidateArmV1(
            **_common(candidate_id="review"),
            provider="openai",
            model="gpt-5.6-sol",
            prompt_sha256="A" * 64,
            schema_sha256="2" * 64,
        )

    identity = _protocol().identity_payload()
    assert not {"outcome", "pnl", "order", "trade", "trade_authority"} & identity.keys()
    assert set(identity["arms"][0]) == {
        "arm_id",
        "candidate_id",
        "candidate_revision",
        "artifact_sha256",
        "input_feature_sha256",
        "decision_mapping_sha256",
        "hypothetical_exit_sha256",
        "cost_model_sha256",
    }


def _decision_sample(*, arm_protocol_digest: str | None = None) -> ResearchDecisionSampleV1:
    return ResearchDecisionSampleV1(
        campaign_id="adaptive-campaign-001",
        arm_id="strategy-only",
        arm_protocol_digest=arm_protocol_digest,
        sample_id="sample-001",
        symbol="BTCUSDT",
        timeframe="1m",
        market_as_of_ts_ms=1_760_000_000_000,
        market_snapshot_sha256="c" * 64,
        paired_at_ts_ms=1_760_000_001_000,
        sample_deadline_ts_ms=1_760_000_010_000,
        strategy_id="adaptive-v1",
        strategy_revision="frozen-001",
        strategy_outcome="NO_INTENT",
        strategy_evaluation_sha256="d" * 64,
        strategy_evidence_as_of_ts_ms=1_760_000_000_000,
        strategy_market_snapshot_sha256="c" * 64,
        llm_outcome="NOT_CALLED",
    )


def test_sample_arm_protocol_link_changes_canonical_identity_but_none_preserves_legacy() -> None:
    legacy = _decision_sample()
    linked = _decision_sample(arm_protocol_digest="e" * 64)

    assert "arm_protocol_digest" not in legacy.identity_payload()
    assert legacy.sample_record_id == canonical_sha256(legacy.identity_payload())
    assert linked.identity_payload()["arm_protocol_digest"] == "e" * 64
    assert linked.sample_record_id == canonical_sha256(linked.identity_payload())
    assert linked.sample_record_id != legacy.sample_record_id

    with pytest.raises(ValidationError, match="sample_record_id"):
        ResearchDecisionSampleV1.model_validate(
            {
                **linked.model_dump(mode="json"),
                "arm_protocol_digest": "f" * 64,
            }
        )

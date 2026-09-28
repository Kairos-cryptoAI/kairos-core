"""Frozen, non-executable roster for SIM matched adaptive candidate research.

The protocol binds each preregistered arm to its exact candidate, transforms,
exit assumptions, costs, and (for LLM arms) route and prompt/schema versions.
It contains no decision outcomes, PnL, orders, or permission to trade.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictStr, field_validator, model_validator

from .base import StrictKairosMessage, StrictValueModel, canonical_sha256
from .research_schedule import RESEARCH_ARMS, ResearchArm
from .strategy import _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
AdaptiveCandidateProvider = Literal["openai", "deepseek"]


class _AdaptiveCandidateArmBaseV1(StrictValueModel):
    """Fields common to the immutable identity of each research candidate."""

    candidate_id: Identifier
    candidate_revision: Identifier
    artifact_sha256: Sha256Hex
    input_feature_sha256: Sha256Hex
    decision_mapping_sha256: Sha256Hex
    hypothetical_exit_sha256: Sha256Hex
    cost_model_sha256: Sha256Hex

    @field_validator("candidate_id", "candidate_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)


class StrategyOnlyAdaptiveCandidateArmV1(_AdaptiveCandidateArmBaseV1):
    """Strategy-only control arm; its closed schema cannot carry LLM metadata."""

    arm_id: Literal["strategy-only"] = "strategy-only"


class _LLMAdaptiveCandidateArmBaseV1(_AdaptiveCandidateArmBaseV1):
    """Exact model route and prompt contract shared by the two LLM arms."""

    provider: AdaptiveCandidateProvider
    model: Identifier
    prompt_sha256: Sha256Hex
    schema_sha256: Sha256Hex

    @field_validator("model")
    @classmethod
    def validate_route_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)


class StrategyReviewAdaptiveCandidateArmV1(_LLMAdaptiveCandidateArmBaseV1):
    """Strategy plus review/veto/defer candidate arm."""

    arm_id: Literal["strategy-review"] = "strategy-review"


class LLMProposalAdaptiveCandidateArmV1(_LLMAdaptiveCandidateArmBaseV1):
    """LLM-generated research proposal candidate arm."""

    arm_id: Literal["llm-proposal-research"] = "llm-proposal-research"


AdaptiveCandidateProtocolArmV1 = Annotated[
    StrategyOnlyAdaptiveCandidateArmV1
    | StrategyReviewAdaptiveCandidateArmV1
    | LLMProposalAdaptiveCandidateArmV1,
    Field(discriminator="arm_id"),
]


class AdaptiveCandidateProtocolV1(StrictKairosMessage):
    """Canonical identity for exactly three matched SIM research candidates."""

    contract_version: Literal["adaptive-candidate-protocol.v1"] = "adaptive-candidate-protocol.v1"
    source: Literal["kairos-adaptive-candidate-protocol"] = "kairos-adaptive-candidate-protocol"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    protocol_digest: Sha256Hex | None = None
    campaign_id: Identifier
    schedule_digest: Sha256Hex
    arms: tuple[
        StrategyOnlyAdaptiveCandidateArmV1,
        StrategyReviewAdaptiveCandidateArmV1,
        LLMProposalAdaptiveCandidateArmV1,
    ]

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        return _normalized_identifier(value, name="campaign_id")

    @model_validator(mode="after")
    def validate_protocol(self) -> Self:
        if tuple(arm.arm_id for arm in self.arms) != RESEARCH_ARMS:
            raise ValueError("adaptive candidate protocol requires the three fixed arms in order")
        expected = canonical_sha256(self.identity_payload())
        if self.protocol_digest is not None and self.protocol_digest != expected:
            raise ValueError("protocol_digest does not match the canonical candidate roster")
        object.__setattr__(self, "protocol_digest", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=0)
        return self

    def identity_payload(self) -> dict[str, object]:
        """Canonical identity payload, excluding the digest and bus envelope."""

        return {
            "arms": [arm.model_dump(mode="json") for arm in self.arms],
            "authority": self.authority,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "schedule_digest": self.schedule_digest,
            "source": self.source,
        }

    def arm_digest(self, arm_id: ResearchArm) -> str:
        """Return the stable digest Persistence can bind to each observation."""

        if arm_id not in RESEARCH_ARMS:
            raise ValueError("arm_id is outside the fixed adaptive candidate roster")
        for arm in self.arms:
            if arm.arm_id == arm_id:
                return canonical_sha256(arm)
        raise ValueError("arm_id is outside the fixed adaptive candidate roster")

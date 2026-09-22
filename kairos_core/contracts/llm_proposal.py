"""Research-only contracts for LLM-generated trade hypotheses.

These messages are deliberately not strategy intents or risk decisions.  They
carry no entry/exit prices, sizing, leverage, venue, or order fields, and no
helper in this module promotes one to an executable contract.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from ..enums import LLMProposalAction
from .base import StrictKairosMessage, StrictValueModel, canonical_json_bytes, canonical_sha256
from .strategy import EvidenceReferenceV1, _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Symbol = Annotated[StrictStr, Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")]


class LLMProposalModelProvenanceV1(StrictValueModel):
    """Trusted gateway metadata for the model call that produced a proposal."""

    provider: Identifier
    requested_model: Identifier
    resolved_model: Identifier
    system_fingerprint: Identifier | None = None
    reasoning_effort: Identifier | None = None
    request_id: Identifier
    prompt_sha256: Sha256Hex
    response_sha256: Sha256Hex
    budget_reservation_id: Identifier
    latency_ms: NonNegativeInt
    cost_usd: float = Field(..., ge=0)


class LLMTradeProposalV1(StrictKairosMessage):
    """A bounded, auditable LLM hypothesis that cannot authorize execution."""

    contract_version: Literal["llm-trade-proposal.v1"] = "llm-trade-proposal.v1"
    source: Literal["kairos-llm-proposal-adapter"] = "kairos-llm-proposal-adapter"
    proposal_id: Sha256Hex | None = None
    campaign_id: Identifier
    arm_id: Identifier
    sample_id: Identifier
    symbol: Symbol
    timeframe: Identifier
    market_as_of_ts_ms: NonNegativeInt
    expires_at_ts_ms: NonNegativeInt
    market_snapshot_sha256: Sha256Hex
    action: LLMProposalAction
    rationale: StrictStr = Field(..., min_length=1, max_length=1_024)
    evidence: tuple[EvidenceReferenceV1, ...] = Field(default_factory=tuple, max_length=32)
    model_provenance: LLMProposalModelProvenanceV1

    @field_validator("campaign_id", "arm_id", "sample_id", "timeframe")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rationale must be a non-empty normalized string")
        return normalized

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        if self.expires_at_ts_ms < self.market_as_of_ts_ms:
            raise ValueError("proposal cannot expire before its market snapshot")
        if self.action in (LLMProposalAction.LONG_BIAS, LLMProposalAction.SHORT_BIAS):
            if self.expires_at_ts_ms <= self.market_as_of_ts_ms:
                raise ValueError("directional proposals must have a non-empty validity window")
            if not self.evidence:
                raise ValueError("directional proposals require cited evidence")
            if any(item.observed_at_ms is None for item in self.evidence):
                raise ValueError("directional proposal evidence requires an observation timestamp")
        if any(
            item.observed_at_ms is not None and item.observed_at_ms > self.market_as_of_ts_ms
            for item in self.evidence
        ):
            raise ValueError("proposal evidence cannot be observed after the market snapshot")
        canonical_evidence = tuple(sorted(self.evidence, key=canonical_json_bytes))
        if len({canonical_sha256(item) for item in canonical_evidence}) != len(canonical_evidence):
            raise ValueError("proposal evidence cannot contain duplicates")
        object.__setattr__(self, "evidence", canonical_evidence)

        expected_id = canonical_sha256(self.identity_payload())
        if self.proposal_id is not None and self.proposal_id != expected_id:
            raise ValueError("proposal_id does not match the canonical advisory payload")
        object.__setattr__(self, "proposal_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.market_as_of_ts_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        """Canonical hypothesis and provenance; envelope metadata is excluded."""

        return {
            "action": self.action.value,
            "arm_id": self.arm_id,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "expires_at_ts_ms": self.expires_at_ts_ms,
            "market_as_of_ts_ms": self.market_as_of_ts_ms,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "model_provenance": self.model_provenance.model_dump(mode="json"),
            "rationale": self.rationale,
            "sample_id": self.sample_id,
            "source": self.source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }

    def canonical_proposal_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

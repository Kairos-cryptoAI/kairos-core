"""Caller-attested, non-executable receipt for a completed LLM proposal.

The proposal records the model hypothesis and gateway provenance, but not when
the caller actually observed the response.  This separate receipt preserves
that observation time so a research pair cannot backdate a late completion.
It does not itself prove that the gateway was invoked: producers must derive
its facts from a durable gateway and budget-attempt log.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .base import StrictKairosMessage, canonical_json_bytes, canonical_sha256
from .llm_proposal import LLMProposalModelProvenanceV1
from .strategy import _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
TimestampMs = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Symbol = Annotated[StrictStr, Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")]


class LLMProposalCompletionReceiptV1(StrictKairosMessage):
    """Immutable observation of one completed, scheduled SIM LLM attempt.

    ``model_provenance`` must exactly match the linked proposal.  A receipt
    observed after the deadline remains valid historical evidence, but the
    research-pair builder must refuse to link it to a causal sample.
    """

    contract_version: Literal["llm-proposal-completion-receipt.v1"] = "llm-proposal-completion-receipt.v1"
    source: Literal["kairos-llm-proposal-completion-recorder"] = "kairos-llm-proposal-completion-recorder"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    completion_receipt_id: Sha256Hex | None = None

    campaign_id: Identifier
    arm_id: Identifier
    sample_id: Identifier
    symbol: Symbol
    timeframe: Identifier
    market_as_of_ts_ms: TimestampMs
    market_snapshot_sha256: Sha256Hex
    sample_deadline_ts_ms: TimestampMs

    attempt_id: Identifier
    proposal_id: Sha256Hex
    model_provenance: LLMProposalModelProvenanceV1
    attempt_started_at_ts_ms: TimestampMs
    response_observed_at_ts_ms: TimestampMs

    @field_validator("campaign_id", "arm_id", "sample_id", "timeframe", "attempt_id")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if not self.market_as_of_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("completion receipt requires a future sample deadline")
        if not self.market_as_of_ts_ms <= self.attempt_started_at_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("LLM attempt must start within the scheduled decision window")
        if self.response_observed_at_ts_ms < self.attempt_started_at_ts_ms:
            raise ValueError("response cannot be observed before the LLM attempt started")
        expected_id = canonical_sha256(self.identity_payload())
        if self.completion_receipt_id is not None and self.completion_receipt_id != expected_id:
            raise ValueError("completion_receipt_id does not match the canonical completion facts")
        object.__setattr__(self, "completion_receipt_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.response_observed_at_ts_ms)
        return self

    @property
    def is_late(self) -> bool:
        """A late observation is retained as a receipt, never as a causal pair."""

        return self.response_observed_at_ts_ms >= self.sample_deadline_ts_ms

    def identity_payload(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "attempt_id": self.attempt_id,
            "attempt_started_at_ts_ms": self.attempt_started_at_ts_ms,
            "authority": self.authority,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "market_as_of_ts_ms": self.market_as_of_ts_ms,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "model_provenance": self.model_provenance.model_dump(mode="json"),
            "proposal_id": self.proposal_id,
            "response_observed_at_ts_ms": self.response_observed_at_ts_ms,
            "sample_deadline_ts_ms": self.sample_deadline_ts_ms,
            "sample_id": self.sample_id,
            "source": self.source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }

    def canonical_completion_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

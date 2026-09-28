"""Caller-attested, non-executable receipt for an attempted LLM call failure.

The receipt never contains an exception message, model response, market order,
or inferred proposal.  A failed attempt is not a model decision.  Its observed
time is preserved even if it arrives after the sample decision deadline; a
causal pairing must reject such a late receipt.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .base import StrictKairosMessage, canonical_json_bytes, canonical_sha256
from .strategy import _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
TimestampMs = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Symbol = Annotated[StrictStr, Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")]
LLMCallFailureClass = Literal[
    "TIMEOUT",
    "PROVIDER_ERROR",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_QUOTA_EXHAUSTED",
    "TRANSPORT_ERROR",
    "INVALID_RESPONSE",
    "CANCELLED",
]


class LLMCallFailureV1(StrictKairosMessage):
    """Stable research receipt linked to one caller-observed attempted call.

    The caller must supply facts from its durable gateway/budget attempt log.
    A budget rejection before reservation is not an attempted model call and
    cannot be represented here. Rate/quota classes refer only to a provider
    response after the reserved attempt began.
    This type validates them but cannot itself prove the gateway was invoked.
    ``failure_observed_at_ts_ms`` is an observation time, not a backdated model
    response time.  No ``LLMTradeProposalV1`` is constructed from this receipt.
    """

    contract_version: Literal["llm-call-failure.v1"] = "llm-call-failure.v1"
    source: Literal["kairos-llm-call-failure-recorder"] = "kairos-llm-call-failure-recorder"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    failure_receipt_id: Sha256Hex | None = None

    campaign_id: Identifier
    arm_id: Identifier
    sample_id: Identifier
    symbol: Symbol
    timeframe: Identifier
    market_as_of_ts_ms: TimestampMs
    market_snapshot_sha256: Sha256Hex
    sample_deadline_ts_ms: TimestampMs

    attempt_id: Identifier
    provider: Identifier
    requested_model: Identifier
    prompt_sha256: Sha256Hex
    budget_reservation_id: Identifier
    attempt_started_at_ts_ms: TimestampMs
    failure_observed_at_ts_ms: TimestampMs
    failure_class: LLMCallFailureClass
    response_sha256: Sha256Hex | None = None

    @field_validator(
        "campaign_id",
        "arm_id",
        "sample_id",
        "timeframe",
        "attempt_id",
        "provider",
        "requested_model",
        "budget_reservation_id",
    )
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_failure(self) -> Self:
        if not self.market_as_of_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("failure receipt requires a future sample deadline")
        if not self.market_as_of_ts_ms <= self.attempt_started_at_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("LLM attempt must start within the scheduled decision window")
        if self.failure_observed_at_ts_ms < self.attempt_started_at_ts_ms:
            raise ValueError("failure cannot be observed before the LLM attempt started")
        if self.failure_class == "INVALID_RESPONSE":
            if self.response_sha256 is None:
                raise ValueError("invalid response failure requires a response hash")
        elif self.response_sha256 is not None:
            raise ValueError("only an invalid response failure may carry a response hash")

        expected_id = canonical_sha256(self.identity_payload())
        if self.failure_receipt_id is not None and self.failure_receipt_id != expected_id:
            raise ValueError("failure_receipt_id does not match the canonical failure facts")
        object.__setattr__(self, "failure_receipt_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.failure_observed_at_ts_ms)
        return self

    @property
    def is_late(self) -> bool:
        """A late observation is retained as a receipt, never as a causal pair."""

        return self.failure_observed_at_ts_ms >= self.sample_deadline_ts_ms

    def identity_payload(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "attempt_id": self.attempt_id,
            "attempt_started_at_ts_ms": self.attempt_started_at_ts_ms,
            "authority": self.authority,
            "budget_reservation_id": self.budget_reservation_id,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "failure_class": self.failure_class,
            "failure_observed_at_ts_ms": self.failure_observed_at_ts_ms,
            "market_as_of_ts_ms": self.market_as_of_ts_ms,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "prompt_sha256": self.prompt_sha256,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "response_sha256": self.response_sha256,
            "sample_deadline_ts_ms": self.sample_deadline_ts_ms,
            "sample_id": self.sample_id,
            "source": self.source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }

    def canonical_failure_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

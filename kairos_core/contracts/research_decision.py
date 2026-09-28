"""SIM/research-only paired strategy and LLM decisions for one scheduled sample.

This is an observation record, not a strategy intent, review, risk decision, or
order.  It intentionally has no venue, account, sizing, prices, or execution
authority.  The source decision objects remain independently versioned and
must be checked by the builder before their canonical IDs are linked here.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .base import StrictKairosMessage, canonical_json_bytes, canonical_sha256
from .llm_call_failure import LLMCallFailureClass
from .llm_proposal import MAX_VOLATILITY_ALERT_VALIDITY_MS
from .strategy import _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
TimestampMs = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Symbol = Annotated[StrictStr, Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")]
StrategyOutcome = Literal["LONG", "SHORT", "NO_INTENT", "NOT_EVALUATED"]
LLMOutcome = Literal[
    "LONG_BIAS", "SHORT_BIAS", "VOLATILITY_ALERT", "NO_PROPOSAL", "DEFER", "CALL_FAILED", "NOT_CALLED"
]


class ResearchDecisionSampleV1(StrictKairosMessage):
    """One immutable, causal SIM comparison of independent decision paths.

    ``NO_INTENT`` asserts that a strategy evaluation receipt exists but did not
    emit an intent.  ``NOT_EVALUATED`` asserts there was no such evaluation.
    A completed LLM call links its immutable proposal and caller-observed
    completion receipt, including
    ``VOLATILITY_ALERT``, ``NO_PROPOSAL`` and ``DEFER``. ``CALL_FAILED`` links
    a caller-observed failure receipt, never a proposal; ``NOT_CALLED`` has
    neither lineage.

    ``paired_at_ts_ms`` is the caller-attested logical replay clock.  It must
    precede the sample deadline and each directional candidate's expiry.
    The constructor cannot inspect hash-linked source objects; the builder
    must additionally validate their campaign, arm, sample, symbol, timeframe,
    market snapshot, and source-specific validity before constructing this
    record.
    """

    contract_version: Literal["research-decision-sample.v1"] = "research-decision-sample.v1"
    source: Literal["kairos-research-decision-sampler"] = "kairos-research-decision-sampler"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    sample_record_id: Sha256Hex | None = None

    campaign_id: Identifier
    arm_id: Identifier
    sample_id: Identifier
    symbol: Symbol
    timeframe: Identifier
    market_as_of_ts_ms: TimestampMs
    market_snapshot_sha256: Sha256Hex
    paired_at_ts_ms: TimestampMs
    sample_deadline_ts_ms: TimestampMs

    strategy_id: Identifier
    strategy_revision: Identifier
    strategy_outcome: StrategyOutcome
    strategy_evaluation_sha256: Sha256Hex | None = None
    strategy_evidence_as_of_ts_ms: TimestampMs | None = None
    strategy_market_snapshot_sha256: Sha256Hex | None = None
    strategy_intent_id: Sha256Hex | None = None
    strategy_intent_expires_at_ts_ms: TimestampMs | None = None

    llm_outcome: LLMOutcome
    llm_evidence_as_of_ts_ms: TimestampMs | None = None
    llm_market_snapshot_sha256: Sha256Hex | None = None
    llm_proposal_id: Sha256Hex | None = None
    llm_proposal_expires_at_ts_ms: TimestampMs | None = None
    llm_completion_receipt_id: Sha256Hex | None = None
    llm_completion_started_at_ts_ms: TimestampMs | None = None
    llm_completion_observed_at_ts_ms: TimestampMs | None = None
    llm_failure_receipt_id: Sha256Hex | None = None
    llm_failure_class: LLMCallFailureClass | None = None
    llm_failure_started_at_ts_ms: TimestampMs | None = None
    llm_failure_observed_at_ts_ms: TimestampMs | None = None

    @field_validator("campaign_id", "arm_id", "sample_id", "timeframe", "strategy_id", "strategy_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        if not self.market_as_of_ts_ms <= self.paired_at_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("sample pairing must follow the market snapshot and precede its deadline")

        if self.strategy_outcome == "NOT_EVALUATED":
            if any(
                value is not None
                for value in (
                    self.strategy_evaluation_sha256,
                    self.strategy_evidence_as_of_ts_ms,
                    self.strategy_market_snapshot_sha256,
                    self.strategy_intent_id,
                    self.strategy_intent_expires_at_ts_ms,
                )
            ):
                raise ValueError("NOT_EVALUATED cannot carry strategy evaluation or intent lineage")
        else:
            if (
                self.strategy_evaluation_sha256 is None
                or self.strategy_evidence_as_of_ts_ms is None
                or self.strategy_market_snapshot_sha256 is None
            ):
                raise ValueError("evaluated strategy outcome requires receipt and market evidence lineage")
            if self.strategy_evidence_as_of_ts_ms > self.market_as_of_ts_ms:
                raise ValueError("strategy evidence cannot be observed after the market snapshot")
            if self.strategy_market_snapshot_sha256 != self.market_snapshot_sha256:
                raise ValueError("strategy market snapshot does not match the scheduled sample")
            if self.strategy_outcome == "NO_INTENT":
                if self.strategy_intent_id is not None or self.strategy_intent_expires_at_ts_ms is not None:
                    raise ValueError("NO_INTENT cannot link a directional strategy intent")
            elif self.strategy_intent_id is None or self.strategy_intent_expires_at_ts_ms is None:
                raise ValueError("directional strategy outcome requires an intent ID and expiry")
            elif self.paired_at_ts_ms >= self.strategy_intent_expires_at_ts_ms:
                raise ValueError("directional strategy intent is stale at the pairing clock")

        if self.llm_outcome == "NOT_CALLED":
            if any(
                value is not None
                for value in (
                    self.llm_evidence_as_of_ts_ms,
                    self.llm_market_snapshot_sha256,
                    self.llm_proposal_id,
                    self.llm_proposal_expires_at_ts_ms,
                    self.llm_completion_receipt_id,
                    self.llm_completion_started_at_ts_ms,
                    self.llm_completion_observed_at_ts_ms,
                    self.llm_failure_receipt_id,
                    self.llm_failure_class,
                    self.llm_failure_started_at_ts_ms,
                    self.llm_failure_observed_at_ts_ms,
                )
            ):
                raise ValueError("NOT_CALLED cannot carry LLM proposal, failure, or evidence lineage")
        elif self.llm_outcome == "CALL_FAILED":
            if (
                self.llm_evidence_as_of_ts_ms != self.market_as_of_ts_ms
                or self.llm_market_snapshot_sha256 != self.market_snapshot_sha256
                or self.llm_failure_receipt_id is None
                or self.llm_failure_class is None
                or self.llm_failure_started_at_ts_ms is None
                or self.llm_failure_observed_at_ts_ms is None
            ):
                raise ValueError("CALL_FAILED requires matching market and complete failure lineage")
            if any(
                value is not None
                for value in (
                    self.llm_proposal_id,
                    self.llm_proposal_expires_at_ts_ms,
                    self.llm_completion_receipt_id,
                    self.llm_completion_started_at_ts_ms,
                    self.llm_completion_observed_at_ts_ms,
                )
            ):
                raise ValueError("CALL_FAILED cannot carry a fabricated LLM proposal")
            if not (
                self.market_as_of_ts_ms
                <= self.llm_failure_started_at_ts_ms
                <= self.llm_failure_observed_at_ts_ms
                <= self.paired_at_ts_ms
            ):
                raise ValueError("CALL_FAILED must be observed before the causal pairing clock")
        else:
            if any(
                value is not None
                for value in (
                    self.llm_failure_receipt_id,
                    self.llm_failure_class,
                    self.llm_failure_started_at_ts_ms,
                    self.llm_failure_observed_at_ts_ms,
                )
            ):
                raise ValueError("completed LLM proposal cannot carry failure lineage")
            if (
                self.llm_evidence_as_of_ts_ms is None
                or self.llm_market_snapshot_sha256 is None
                or self.llm_proposal_id is None
                or self.llm_completion_receipt_id is None
                or self.llm_completion_started_at_ts_ms is None
                or self.llm_completion_observed_at_ts_ms is None
            ):
                raise ValueError(
                    "called LLM outcome requires a proposal, completion receipt, and market lineage"
                )
            if not (
                self.market_as_of_ts_ms
                <= self.llm_completion_started_at_ts_ms
                <= self.llm_completion_observed_at_ts_ms
                <= self.paired_at_ts_ms
            ):
                raise ValueError("completed LLM response must be observed before the causal pairing clock")
            if self.llm_evidence_as_of_ts_ms > self.market_as_of_ts_ms:
                raise ValueError("LLM evidence cannot be observed after the market snapshot")
            if self.llm_market_snapshot_sha256 != self.market_snapshot_sha256:
                raise ValueError("LLM market snapshot does not match the scheduled sample")
            if self.llm_outcome in ("LONG_BIAS", "SHORT_BIAS", "VOLATILITY_ALERT"):
                if self.llm_proposal_expires_at_ts_ms is None:
                    raise ValueError("advisory LLM hypothesis requires an expiry")
                if self.paired_at_ts_ms >= self.llm_proposal_expires_at_ts_ms:
                    raise ValueError("advisory LLM hypothesis is stale at the pairing clock")
                if (
                    self.llm_outcome == "VOLATILITY_ALERT"
                    and self.llm_proposal_expires_at_ts_ms - self.market_as_of_ts_ms
                    > MAX_VOLATILITY_ALERT_VALIDITY_MS
                ):
                    raise ValueError("volatility alert validity cannot exceed 24 hours")
            elif self.llm_proposal_expires_at_ts_ms is not None:
                raise ValueError("non-candidate LLM outcome cannot carry a proposal expiry")

        expected_id = canonical_sha256(self.identity_payload())
        if self.sample_record_id is not None and self.sample_record_id != expected_id:
            raise ValueError("sample_record_id does not match the canonical research sample")
        object.__setattr__(self, "sample_record_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.paired_at_ts_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        """Canonical research facts; generic bus-envelope metadata is excluded."""

        return {
            "arm_id": self.arm_id,
            "authority": self.authority,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "llm_evidence_as_of_ts_ms": self.llm_evidence_as_of_ts_ms,
            "llm_completion_observed_at_ts_ms": self.llm_completion_observed_at_ts_ms,
            "llm_completion_receipt_id": self.llm_completion_receipt_id,
            "llm_completion_started_at_ts_ms": self.llm_completion_started_at_ts_ms,
            "llm_failure_class": self.llm_failure_class,
            "llm_failure_observed_at_ts_ms": self.llm_failure_observed_at_ts_ms,
            "llm_failure_receipt_id": self.llm_failure_receipt_id,
            "llm_failure_started_at_ts_ms": self.llm_failure_started_at_ts_ms,
            "llm_market_snapshot_sha256": self.llm_market_snapshot_sha256,
            "llm_outcome": self.llm_outcome,
            "llm_proposal_expires_at_ts_ms": self.llm_proposal_expires_at_ts_ms,
            "llm_proposal_id": self.llm_proposal_id,
            "market_as_of_ts_ms": self.market_as_of_ts_ms,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "paired_at_ts_ms": self.paired_at_ts_ms,
            "sample_deadline_ts_ms": self.sample_deadline_ts_ms,
            "sample_id": self.sample_id,
            "source": self.source,
            "strategy_evaluation_sha256": self.strategy_evaluation_sha256,
            "strategy_evidence_as_of_ts_ms": self.strategy_evidence_as_of_ts_ms,
            "strategy_id": self.strategy_id,
            "strategy_intent_expires_at_ts_ms": self.strategy_intent_expires_at_ts_ms,
            "strategy_intent_id": self.strategy_intent_id,
            "strategy_market_snapshot_sha256": self.strategy_market_snapshot_sha256,
            "strategy_outcome": self.strategy_outcome,
            "strategy_revision": self.strategy_revision,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }

    def canonical_sample_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

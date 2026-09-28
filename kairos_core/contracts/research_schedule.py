"""Immutable SIM-only roster and coverage seal for matched research arms.

The roster is fixed before results are admitted.  A complete coverage seal
means only that every preassigned window has one causal observation in every
arm; it is not an economic evaluation or permission to trade.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .base import StrictKairosMessage, StrictValueModel, canonical_sha256
from .strategy import _normalized_identifier, _set_default_envelope

Sha256Hex = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
TimestampMs = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]
Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
ResearchArm = Literal["strategy-only", "strategy-review", "llm-proposal-research"]
RESEARCH_ARMS: tuple[ResearchArm, ResearchArm, ResearchArm] = (
    "strategy-only",
    "strategy-review",
    "llm-proposal-research",
)


class ResearchObservationWindowV1(StrictValueModel):
    """One preassigned sample key, independent of later arm outcomes."""

    sample_id: Identifier
    symbol: Annotated[StrictStr, Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$")]
    timeframe: Identifier
    market_as_of_ts_ms: TimestampMs
    market_snapshot_sha256: Sha256Hex | None = None
    paired_at_ts_ms: TimestampMs
    sample_deadline_ts_ms: TimestampMs

    @field_validator("sample_id", "timeframe")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.market_as_of_ts_ms <= self.paired_at_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("research window pairing must be within its preassigned deadline")
        return self


class ResearchObservationScheduleV1(StrictKairosMessage):
    """Closed-world campaign roster: one immutable sample set for all three arms."""

    contract_version: Literal["research-observation-schedule.v1"] = "research-observation-schedule.v1"
    source: Literal["kairos-research-scheduler"] = "kairos-research-scheduler"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    schedule_digest: Sha256Hex | None = None
    campaign_id: Identifier
    strategy_id: Identifier
    strategy_revision: Identifier
    source_set_sha256: Sha256Hex
    evaluator_sha256: Sha256Hex
    arm_ids: tuple[ResearchArm, ResearchArm, ResearchArm] = RESEARCH_ARMS
    windows: Annotated[tuple[ResearchObservationWindowV1, ...], Field(min_length=1, max_length=50_000)]

    @field_validator("campaign_id", "strategy_id", "strategy_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if self.arm_ids != RESEARCH_ARMS:
            raise ValueError("matched research requires the three fixed arms in preregistered order")
        keys = [
            (window.market_as_of_ts_ms, window.symbol, window.timeframe, window.sample_id)
            for window in self.windows
        ]
        if keys != sorted(keys):
            raise ValueError("research windows must be in deterministic market-time order")
        if len({window.sample_id for window in self.windows}) != len(self.windows):
            raise ValueError("research schedule contains a duplicate sample_id")
        market_keys = {
            (window.symbol, window.timeframe, window.market_as_of_ts_ms) for window in self.windows
        }
        if len(market_keys) != len(self.windows):
            raise ValueError("research schedule contains a duplicate symbol/timeframe/decision clock")
        expected = canonical_sha256(self.identity_payload())
        if self.schedule_digest is not None and self.schedule_digest != expected:
            raise ValueError("schedule_digest does not match the immutable roster")
        object.__setattr__(self, "schedule_digest", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.windows[0].market_as_of_ts_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "arm_ids": self.arm_ids,
            "authority": self.authority,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "evaluator_sha256": self.evaluator_sha256,
            "source": self.source,
            "source_set_sha256": self.source_set_sha256,
            "strategy_id": self.strategy_id,
            "strategy_revision": self.strategy_revision,
            "windows": [window.model_dump(mode="json") for window in self.windows],
        }


class ResearchCoverageSealV1(StrictKairosMessage):
    """Digest of complete matched observation identities, with no PnL claim."""

    contract_version: Literal["research-coverage-seal.v1"] = "research-coverage-seal.v1"
    source: Literal["kairos-research-coverage-gate"] = "kairos-research-coverage-gate"
    authority: Literal["SIM_RESEARCH_ONLY"] = "SIM_RESEARCH_ONLY"
    coverage_digest: Sha256Hex | None = None
    campaign_id: Identifier
    schedule_digest: Sha256Hex
    candidate_protocol_digest: Sha256Hex | None = None
    expected_result_count: Annotated[StrictInt, Field(ge=3)]
    result_ids_sha256: Sha256Hex

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign(cls, value: str) -> str:
        return _normalized_identifier(value, name="campaign_id")

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        expected = canonical_sha256(self.identity_payload())
        if self.coverage_digest is not None and self.coverage_digest != expected:
            raise ValueError("coverage_digest does not match its canonical observations")
        object.__setattr__(self, "coverage_digest", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=0)
        return self

    def identity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "authority": self.authority,
            "campaign_id": self.campaign_id,
            "contract_version": self.contract_version,
            "expected_result_count": self.expected_result_count,
            "result_ids_sha256": self.result_ids_sha256,
            "schedule_digest": self.schedule_digest,
            "source": self.source,
        }
        # Legacy seals keep their canonical ID. Adaptive-protocol campaigns
        # include this link so the coverage seal commits to the exact roster.
        if self.candidate_protocol_digest is not None:
            payload["candidate_protocol_digest"] = self.candidate_protocol_digest
        return payload

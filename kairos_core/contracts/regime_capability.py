"""Opt-in, causal regime capabilities; legacy Macro allocations stay unchanged.

These contracts describe deterministic evidence and capital limits, never
strategy promotion, model confidence or execution authority. A frozen detector
must publish observations separately; a Macro CHOP hint is not a RANGE fact.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..enums import Side
from .base import StrictKairosMessage, StrictValueModel, canonical_sha256
from .strategic import StrategicAllocation
from .strategy import StrategyIntentV1, _set_default_envelope

REGIME_OBSERVATION_TOPIC = "kairos.market.regime_observation.v1"
REGIME_BOUND_ALLOCATION_TOPIC = "kairos.macro.regime_bound_allocation.v1"

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")]
Timestamp = Annotated[int, Field(ge=0, strict=True)]


class CapabilityRegime(StrEnum):
    BULL = "BULL"
    RANGE = "RANGE"
    BEAR = "BEAR"
    CRASH = "CRASH"
    UNCERTAIN = "UNCERTAIN"


class StrategyRegimeCapabilityV1(StrictValueModel):
    strategy_id: Identifier
    strategy_revision: Identifier
    strategy_code_sha256: Digest
    config_sha256: Digest
    regime: CapabilityRegime
    sides: tuple[Side, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def explicit_directional_capability(self) -> Self:
        if self.regime is CapabilityRegime.UNCERTAIN or Side.FLAT in self.sides:
            raise ValueError("uncertainty and FLAT cannot authorize a directional capability")
        if len(self.sides) != len(set(self.sides)):
            raise ValueError("capability sides must be unique")
        object.__setattr__(self, "sides", tuple(sorted(self.sides, key=lambda side: side.value)))
        return self


class RegimeCapabilityPolicyV1(StrictValueModel):
    contract_version: Literal["regime-capability-policy.v1"] = "regime-capability-policy.v1"
    profile: Literal["adaptive-research-v1"] = "adaptive-research-v1"
    source_set_sha256: Digest
    observation_source: Identifier
    detector_code_sha256: Digest
    detector_config_sha256: Digest
    capabilities: tuple[StrategyRegimeCapabilityV1, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def exact_capability_catalog(self) -> Self:
        keys = [(item.strategy_id, item.strategy_revision, item.regime) for item in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("strategy revision/regime capabilities must be unique")
        fingerprints: dict[tuple[str, str], tuple[str, str]] = {}
        for item in self.capabilities:
            key = (item.strategy_id, item.strategy_revision)
            fingerprint = (item.strategy_code_sha256, item.config_sha256)
            if key in fingerprints and fingerprints[key] != fingerprint:
                raise ValueError(
                    "one exact strategy revision cannot have conflicting code/config fingerprints"
                )
            fingerprints[key] = fingerprint
        object.__setattr__(
            self,
            "capabilities",
            tuple(
                sorted(
                    self.capabilities,
                    key=lambda item: (item.strategy_id, item.strategy_revision, item.regime.value),
                )
            ),
        )
        return self

    @property
    def policy_sha256(self) -> str:
        """Bind the entire closed, canonical mapping, not its display label."""
        return canonical_sha256(self)

    def permits(self, intent: StrategyIntentV1, regime: CapabilityRegime) -> bool:
        return any(
            item.strategy_id == intent.strategy_id
            and item.strategy_revision == intent.strategy_revision
            and item.strategy_code_sha256 == intent.provenance.strategy_code_sha256
            and item.config_sha256 == intent.provenance.config_sha256
            and item.regime is regime
            and intent.side in item.sides
            for item in self.capabilities
        )

    def validate_observation(self, observation: RegimeObservationV1) -> None:
        if (
            observation.source_set_sha256 != self.source_set_sha256
            or observation.source != self.observation_source
            or observation.detector_code_sha256 != self.detector_code_sha256
            or observation.detector_config_sha256 != self.detector_config_sha256
            or not self.permits(observation.intent, observation.regime)
        ):
            raise ValueError("deterministic observation does not match the frozen exact capability")


class RegimeObservationV1(StrictKairosMessage):
    contract_version: Literal["regime-observation.v1"] = "regime-observation.v1"
    observation_id: Digest | None = None
    source_set_sha256: Digest
    detector_code_sha256: Digest
    detector_config_sha256: Digest
    intent: StrategyIntentV1
    regime: CapabilityRegime
    event_as_of_ms: Timestamp
    observed_at_ms: Timestamp
    expires_at_ms: Timestamp

    @model_validator(mode="after")
    def causal_observation(self) -> Self:
        if self.event_as_of_ms > self.intent.decision_ts_ms or self.event_as_of_ms > self.observed_at_ms:
            raise ValueError(
                "regime market events cannot postdate the strategy decision or local observation"
            )
        if not self.observed_at_ms <= self.expires_at_ms or self.intent.decision_ts_ms > self.expires_at_ms:
            raise ValueError("regime observation is outside its candidate lifetime")
        if self.expires_at_ms > self.intent.entry_expires_ts_ms:
            raise ValueError("regime evidence cannot outlive its immutable intent")
        payload = self.model_dump(
            mode="json",
            exclude={"observation_id", "message_id", "correlation_id", "causation_id", "produced_at"},
        )
        expected = canonical_sha256(payload)
        if self.observation_id is not None and self.observation_id != expected:
            raise ValueError("regime observation identity differs from its canonical causal inputs")
        object.__setattr__(self, "observation_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.observed_at_ms)
        if (
            self.produced_at.utcoffset() is None
            or not self.observed_at_ms <= int(self.produced_at.timestamp() * 1000) <= self.expires_at_ms
        ):
            raise ValueError("regime production clock is outside the actual observation lifetime")
        return self


class RegimeCapitalBasisV1(StrictValueModel):
    """Scope captured when Macro actually creates an opt-in capital allocation.

    Historical unscoped legacy allocations must never be relabelled as this
    basis. Account identity, source set and policy cannot be inferred from weight.
    """

    capital_basis_id: Digest | None = None
    allocation: StrategicAllocation
    policy_sha256: Digest
    source_set_sha256: Digest
    account_id: Identifier
    account_snapshot_id: Digest
    account_captured_at_ms: Timestamp
    environment: Literal["PAPER_DEV"] = "PAPER_DEV"

    @model_validator(mode="after")
    def causal_capital_basis(self) -> Self:
        if self.allocation.produced_at.utcoffset() is None:
            raise ValueError("capital allocation needs an aware timestamp")
        if self.account_captured_at_ms > int(self.allocation.produced_at.timestamp() * 1000):
            raise ValueError("capital allocation cannot use a future account snapshot")
        values = (
            self.allocation.stable_reserve_pct,
            self.allocation.max_gross_leverage,
            *self.allocation.strategy_weights.values(),
        )
        if any(not math.isfinite(value) for value in values) or any(
            not 0 <= weight <= 1 for weight in self.allocation.strategy_weights.values()
        ):
            raise ValueError("capital weights must be finite, non-negative fractions")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"capital_basis_id"}))
        if self.capital_basis_id is not None and self.capital_basis_id != expected:
            raise ValueError("capital basis identity differs from its original immutable allocation")
        object.__setattr__(self, "capital_basis_id", expected)
        return self


class RegimeBoundAllocationV1(StrictKairosMessage):
    contract_version: Literal["regime-bound-allocation.v1"] = "regime-bound-allocation.v1"
    allocation_id: Digest | None = None
    capital_basis: RegimeCapitalBasisV1
    observation: RegimeObservationV1
    bound_at_ms: Timestamp

    @model_validator(mode="after")
    def exact_causal_binding(self) -> Self:
        basis, observation = self.capital_basis, self.observation
        if basis.source_set_sha256 != observation.source_set_sha256:
            raise ValueError("capital and regime source sets differ")
        if self.source != basis.allocation.source:
            raise ValueError("bound allocation cannot relabel a foreign capital producer")
        if int(basis.allocation.produced_at.timestamp() * 1000) > observation.intent.decision_ts_ms:
            raise ValueError("future capital allocation cannot support an older candidate")
        if (
            not max(observation.intent.decision_ts_ms, int(observation.produced_at.timestamp() * 1000))
            <= self.bound_at_ms
            <= observation.expires_at_ms
        ):
            raise ValueError("bound allocation is outside the causal evidence lifetime")
        payload = self.model_dump(
            mode="json",
            exclude={"allocation_id", "message_id", "correlation_id", "causation_id", "produced_at"},
        )
        expected = canonical_sha256(payload)
        if self.allocation_id is not None and self.allocation_id != expected:
            raise ValueError("bound allocation identity differs from its full provenance")
        object.__setattr__(self, "allocation_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.bound_at_ms)
        if (
            self.produced_at.utcoffset() is None
            or int(self.produced_at.timestamp() * 1000) != self.bound_at_ms
        ):
            raise ValueError("bound allocation envelope timestamp differs from its causal binding")
        return self


def validate_policy_binding(
    policy: RegimeCapabilityPolicyV1,
    *,
    expected_sha256: str,
    source_set_sha256: str,
    allowed_strategy_revisions: set[tuple[str, str]],
) -> None:
    """Require independent expected identities; the artifact cannot trust itself."""
    if policy.policy_sha256 != expected_sha256 or policy.source_set_sha256 != source_set_sha256:
        raise ValueError("regime policy does not match the independently frozen policy/source set")
    if any(
        (item.strategy_id, item.strategy_revision) not in allowed_strategy_revisions
        for item in policy.capabilities
    ):
        raise ValueError("regime policy contains an unknown/unapproved exact strategy revision")

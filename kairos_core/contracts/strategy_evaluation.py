"""Observational runtime strategy evaluations, never trading authority.

An empty generator result is NO_INTENT only after one scheduled, sufficiently
warmed, successful evaluation. Other states are explicit non-evaluations. The
bar clock and the caller's actual receipt-construction clock are separate; this
contract does not attest a PostgreSQL insertion time or scientific qualification.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from ..enums import Side, TradingMode
from .base import StrictKairosMessage, canonical_json_bytes, canonical_sha256, datetime_from_unix_ms
from .strategy import _normalized_identifier, _set_default_envelope

_SHA = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_MS = Annotated[StrictInt, Field(ge=0)]
StrategyEvaluationStatus = Literal[
    "INTENT", "NO_INTENT", "WARMUP", "NOT_SCHEDULED", "DISABLED", "UNAVAILABLE", "ERROR"
]


class StrategyEvaluationV1(StrictKairosMessage):
    """One immutable observation slot; the logical ID excludes its wall clock."""

    contract_version: Literal["strategy-evaluation.v1"] = "strategy-evaluation.v1"
    source: Literal["strategy-engine"] = "strategy-engine"
    authority: Literal["OBSERVATION_ONLY"] = "OBSERVATION_ONLY"
    trading_authority: Literal[False] = False
    evaluation_id: _SHA | None = None
    receipt_sha256: _SHA | None = None
    scope: Literal["ENGINE", "STRATEGY"]
    strategy_id: StrictStr | None = Field(default=None, max_length=128)
    strategy_revision: StrictStr | None = Field(default=None, max_length=128)
    registry_status: (
        Literal["rejected", "research", "forward_frozen", "inconclusive", "paper_approved"] | None
    ) = None
    trading_mode: TradingMode
    enabled_strategy_ids: tuple[StrictStr, ...] = Field(max_length=128)
    runtime_policy_sha256: _SHA
    strategy_code_sha256: _SHA | None = None
    config_sha256: _SHA | None = None
    venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    symbol: StrictStr = Field(min_length=2, max_length=32)
    timeframe: Literal["1m"] = "1m"
    bar_open_time_ms: _MS
    decision_ts_ms: _MS
    anchor_bar_sha256: _SHA
    input_first_open_time_ms: _MS
    input_bar_count: Annotated[StrictInt, Field(ge=1, le=86_400)]
    input_window_sha256: _SHA | None = None
    observed_at_ms: _MS
    status: StrategyEvaluationStatus
    evaluation_complete: StrictBool = False
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    error_type: StrictStr | None = Field(default=None, max_length=128)
    intent_ids: tuple[_SHA, ...] = Field(default=(), max_length=128)
    intent_sides: tuple[Side, ...] = Field(default=(), max_length=128)

    @field_validator("strategy_id", "strategy_revision", "reason_code", "error_type")
    @classmethod
    def identifiers(cls, value: str | None, info) -> str | None:
        return None if value is None else _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def normalized_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if self.enabled_strategy_ids != tuple(sorted(set(self.enabled_strategy_ids))):
            raise ValueError("enabled strategy roster must be distinct and sorted")
        for value in self.enabled_strategy_ids:
            _normalized_identifier(value, name="enabled_strategy_ids")
        if self.scope == "ENGINE":
            if (
                self.strategy_id is not None
                or self.strategy_revision is not None
                or self.registry_status is not None
                or self.strategy_code_sha256 is not None
                or self.config_sha256 is not None
                or self.status not in {"DISABLED", "UNAVAILABLE"}
            ):
                raise ValueError("an engine non-evaluation cannot invent a strategy identity")
        elif self.strategy_id is None or self.strategy_revision is None or self.registry_status is None:
            raise ValueError("a strategy observation requires its exact registered identity and status")
        elif self.strategy_id not in self.enabled_strategy_ids:
            raise ValueError("strategy observation is outside its explicit enabled roster")
        if (
            self.bar_open_time_ms % 60_000
            or self.decision_ts_ms != self.bar_open_time_ms + 59_999
            or self.input_first_open_time_ms % 60_000
            or self.input_first_open_time_ms > self.bar_open_time_ms
            or self.observed_at_ms < self.decision_ts_ms
        ):
            raise ValueError("evaluation requires a closed causal minute and a non-backdated observation")
        completed = self.status in {"INTENT", "NO_INTENT"}
        if self.evaluation_complete != completed:
            raise ValueError("only INTENT/NO_INTENT attest a complete successful scheduled evaluation")
        if completed and (
            self.scope != "STRATEGY"
            or self.input_window_sha256 is None
            or self.strategy_code_sha256 is None
            or self.config_sha256 is None
            or self.bar_open_time_ms - self.input_first_open_time_ms != (self.input_bar_count - 1) * 60_000
        ):
            raise ValueError("a completed evaluation requires exact gap-free input and source fingerprints")
        if self.trading_mode is TradingMode.PAPER and completed and self.registry_status != "paper_approved":
            raise ValueError("a rejected PAPER allow-list cannot become a completed strategy evaluation")
        if self.trading_mode is TradingMode.LIVE:
            raise ValueError("runtime evaluation does not authorize a LIVE strategy service")
        if (
            tuple(sorted(set(self.intent_ids))) != self.intent_ids
            or len(self.intent_ids) != len(self.intent_sides)
            or any(side is Side.FLAT for side in self.intent_sides)
            or bool(self.intent_ids) != (self.status == "INTENT")
        ):
            raise ValueError("directional intent references are distinct and exclusive to INTENT evaluations")
        if (self.error_type is not None) != (self.status == "ERROR"):
            raise ValueError("only ERROR records carry a sanitized exception class")
        expected_id = canonical_sha256(self.slot_payload())
        if self.evaluation_id is not None and self.evaluation_id != expected_id:
            raise ValueError("evaluation_id differs from its canonical runtime slot")
        object.__setattr__(self, "evaluation_id", expected_id)
        expected_receipt = canonical_sha256(self.identity_payload())
        if self.receipt_sha256 is not None and self.receipt_sha256 != expected_receipt:
            raise ValueError("receipt_sha256 differs from its immutable observation bytes")
        object.__setattr__(self, "receipt_sha256", expected_receipt)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.observed_at_ms)
        if self.message_id != expected_id or self.produced_at != datetime_from_unix_ms(self.observed_at_ms):
            raise ValueError("evaluation envelope must preserve its logical ID and actual observation clock")
        return self

    def slot_payload(self) -> dict[str, object]:
        """Stable slot identity; a changed outcome cannot mint another logical slot."""
        fields = (
            "contract_version",
            "scope",
            "strategy_id",
            "strategy_revision",
            "registry_status",
            "trading_mode",
            "enabled_strategy_ids",
            "runtime_policy_sha256",
            "venue",
            "symbol",
            "timeframe",
            "bar_open_time_ms",
            "decision_ts_ms",
            "anchor_bar_sha256",
        )
        payload = self.model_dump(mode="json")
        return {name: payload[name] for name in fields}

    def identity_payload(self) -> dict[str, object]:
        """Immutable result, including actual caller time but excluding the bus envelope."""
        return self.model_dump(
            mode="json",
            exclude={
                "receipt_sha256",
                "schema_version",
                "message_id",
                "correlation_id",
                "causation_id",
                "produced_at",
            },
        )

    def canonical_evaluation_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())


__all__ = ["StrategyEvaluationStatus", "StrategyEvaluationV1"]

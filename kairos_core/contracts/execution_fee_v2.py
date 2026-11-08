"""Versioned execution observations with explicit unknown and multi-asset fees.

Claims of fee coverage, source provenance or finality are not independent
verification, settlement evidence, execution permission or LIVE qualification.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from ..enums import (
    EvedexProfile,
    OrderRole,
    TradeExecutionEventType,
    TradeExitReason,
    TradeLifecycleState,
    TradingMode,
)
from .base import StrictKairosMessage, StrictValueModel, canonical_sha256, datetime_from_unix_ms
from .paper import TradeExecutionEventV1, _normalized, _validate_environment
from .strategy import NonNegativeFloat, NonNegativeInt, PositiveFloat, Sha256Hex


def _decimal_input(value: Any) -> Any:
    """Reject lossy JSON/SDK floats; wire amounts must be decimal strings."""
    if value is None or isinstance(value, Decimal):
        return value
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError("fee amount must be a decimal string or an exact Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("fee amount is not a decimal") from None
    if not result.is_finite():
        raise ValueError("fee amount must be finite")
    return result


class ExecutionFeeComponentV2(StrictValueModel):
    """One source-attributed currency amount, not proof of venue finality."""

    model_config = ConfigDict(revalidate_instances="always")

    component_id: str = Field(..., min_length=1, max_length=160)
    fill_id: str | None = Field(default=None, min_length=1, max_length=160)
    asset: str = Field(..., min_length=1, max_length=32)
    amount: Decimal | None = None
    amount_role: Literal["DEBIT", "REBATE", "UNKNOWN"] = "UNKNOWN"
    precision: Literal["EXACT_RAW_DECIMAL", "APPROXIMATE", "UNKNOWN"]
    source_id: str = Field(..., min_length=1, max_length=160)
    source_version: str = Field(..., min_length=1, max_length=160)
    source_received_at_ms: NonNegativeInt
    raw_sha256: Sha256Hex | None = None

    _amount_input = field_validator("amount", mode="before")(_decimal_input)

    @field_validator("component_id", "fill_id", "source_id", "source_version")
    @classmethod
    def normalized_identity(cls, value: str | None, info) -> str | None:
        return None if value is None else _normalized(value, info.field_name)

    @field_validator("asset")
    @classmethod
    def normalized_asset(cls, value: str) -> str:
        return _normalized(value, "asset", uppercase=True)

    @model_validator(mode="after")
    def consistent_amount(self) -> Self:
        if self.amount is not None and not self.amount.is_finite():
            raise ValueError("fee amount must be finite")
        if (self.precision == "UNKNOWN") != (self.amount is None):
            raise ValueError("unknown fee precision requires an absent amount")
        if self.precision == "EXACT_RAW_DECIMAL" and self.raw_sha256 is None:
            raise ValueError("exact fee precision requires original raw bytes digest")
        return self


class ExecutionFeeBundleV2(StrictValueModel):
    """Separate fee coverage, reported currency amounts and USD valuation."""

    model_config = ConfigDict(revalidate_instances="always")

    scope_kind: Literal["TRADE", "ORDER", "FILL", "POSITION"]
    scope_reference: str = Field(..., min_length=1, max_length=160)
    coverage: Literal["UNKNOWN", "INCOMPLETE", "FINAL", "NOT_APPLICABLE"]
    components: tuple[ExecutionFeeComponentV2, ...] = ()
    usd_status: Literal["UNKNOWN", "PROVISIONAL", "FINAL"] = "UNKNOWN"
    valuation_evidence_sha256: Sha256Hex | None = None
    finality_evidence_sha256: Sha256Hex | None = None
    supersedes_event_id: Sha256Hex | None = None

    @field_validator("scope_reference")
    @classmethod
    def normalized_scope(cls, value: str) -> str:
        return _normalized(value, "scope_reference")

    @model_validator(mode="after")
    def consistent_coverage(self) -> Self:
        # Until an independent venue-fill verifier exists, a caller's fill ID
        # cannot establish ownership or completeness. Order/trade bundles may
        # still retain reported fill IDs as unqualified provenance.
        if self.scope_kind == "FILL":
            raise ValueError("fill-scoped fee observations require an unavailable qualified fill source")
        identifiers = [item.component_id for item in self.components]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("fee component identities must be unique within the bundle")
        if self.coverage in {"UNKNOWN", "NOT_APPLICABLE"} and self.components:
            raise ValueError("unknown or not-applicable fee coverage cannot contain amounts")
        if self.coverage in {"UNKNOWN", "NOT_APPLICABLE"} and self.usd_status != "UNKNOWN":
            raise ValueError("unknown or not-applicable coverage cannot claim a USD valuation")
        if self.coverage in {"FINAL", "NOT_APPLICABLE"} and self.finality_evidence_sha256 is None:
            raise ValueError("final or not-applicable fee coverage requires evidence reference")
        if self.coverage not in {"FINAL", "NOT_APPLICABLE"} and self.finality_evidence_sha256 is not None:
            raise ValueError("non-final coverage cannot claim finality evidence")
        if self.coverage == "FINAL" and any(item.amount is None for item in self.components):
            raise ValueError("final fee coverage cannot contain an unknown amount")
        if self.usd_status == "FINAL" and (
            self.coverage != "FINAL"
            or any(
                item.precision != "EXACT_RAW_DECIMAL" or item.amount_role == "UNKNOWN"
                for item in self.components
            )
        ):
            raise ValueError("final USD valuation requires final exact fee coverage and known amount roles")
        if self.usd_status == "FINAL" and any(item.amount != 0 for item in self.components):
            raise ValueError("nonzero final USD requires an unavailable qualified sign, source and FX policy")
        if (self.usd_status == "UNKNOWN") != (self.valuation_evidence_sha256 is None):
            raise ValueError("USD valuation needs a matching evidence reference")
        return self


class TradeExecutionEventV2(StrictKairosMessage):
    """Execution observation with fee data that cannot default to free trading."""

    model_config = ConfigDict(revalidate_instances="always")

    contract_version: Literal["trade-execution-event.v2"] = "trade-execution-event.v2"
    event_id: Sha256Hex | None = None
    event_seq: int = Field(..., gt=0)
    occurred_at_ms: NonNegativeInt
    event_type: TradeExecutionEventType | Literal["FEE_UPDATED"]
    lifecycle_state: TradeLifecycleState
    trading_mode: TradingMode
    evedex_profile: EvedexProfile
    account_id: str = Field(..., min_length=1, max_length=128)
    venue_symbol: str = Field(..., min_length=2, max_length=64)
    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    intent_id: Sha256Hex
    risk_decision_id: Sha256Hex
    trade_id: Sha256Hex
    effect_id: str | None = Field(default=None, min_length=1, max_length=128)
    order_role: OrderRole | None = None
    client_order_id: str | None = Field(default=None, min_length=8, max_length=64)
    exchange_order_id: str | None = Field(default=None, min_length=1, max_length=128)
    requested_quantity: NonNegativeFloat | None
    filled_quantity: NonNegativeFloat | None
    position_quantity: float | None
    average_price: PositiveFloat | None = None
    fee_usd: Decimal | None = None
    fee: ExecutionFeeBundleV2
    exit_reason: TradeExitReason | None = None
    details: tuple[tuple[str, str], ...] = ()

    _fee_input = field_validator("fee_usd", mode="before")(_decimal_input)

    @field_validator("fee_usd")
    @classmethod
    def normalize_usd_negative_zero(cls, value: Decimal | None) -> Decimal | None:
        # Preserve original signed component amounts; USD valuation uses one
        # canonical sign for zero, independent of the venue's sign convention.
        return value.copy_abs() if value is not None and value.is_zero() else value

    @field_validator("account_id", "strategy_id", "strategy_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized(value, info.field_name)

    @field_validator("venue_symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized(value, "venue_symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        _validate_environment(self.trading_mode, self.evedex_profile, self.venue_symbol)
        quantities = (self.requested_quantity, self.filled_quantity, self.position_quantity)
        if self.event_type == "FEE_UPDATED":
            if any(value is not None for value in quantities):
                raise ValueError("fee update cannot invent lifecycle quantities")
            if self.average_price is not None:
                raise ValueError("fee update cannot invent an execution price")
        else:
            if any(value is None for value in quantities):
                raise ValueError("lifecycle event requires explicit position and order quantities")
            assert self.filled_quantity is not None and self.requested_quantity is not None
            if self.filled_quantity > self.requested_quantity and self.requested_quantity > 0:
                raise ValueError("filled_quantity cannot exceed requested_quantity")
        if (
            any(value is not None for value in (self.client_order_id, self.exchange_order_id))
            and self.order_role is None
        ):
            raise ValueError("order identifiers require an order_role")
        if self.order_role is not None and self.client_order_id is None:
            raise ValueError("order_role requires a deterministic client_order_id")
        if self.event_type is TradeExecutionEventType.EFFECT_PREPARED and self.effect_id is None:
            raise ValueError("EFFECT_PREPARED requires effect_id")
        if self.event_type == "FEE_UPDATED" and self.fee.supersedes_event_id is None:
            raise ValueError("fee update requires the exact preceding observation ID")
        if self.event_type != "FEE_UPDATED" and self.fee.supersedes_event_id is not None:
            raise ValueError("superseding a fee observation requires a fee update event")
        exit_events = {
            TradeExecutionEventType.EXIT_TRIGGERED,
            TradeExecutionEventType.EXIT_FILLED,
            TradeExecutionEventType.EMERGENCY_CLOSE,
        }
        if (self.exit_reason is not None) != (self.event_type in exit_events):
            raise ValueError("exit lifecycle events require an exit reason and other events forbid it")
        if (self.fee.usd_status == "UNKNOWN") != (self.fee_usd is None):
            raise ValueError("unknown USD fee must be absent and known valuation requires a value")
        if self.fee.scope_kind in {"TRADE", "POSITION"} and self.fee.scope_reference != self.trade_id:
            raise ValueError("trade or position fee scope must match the trade ID")
        if self.fee.scope_kind == "ORDER" and self.fee.scope_reference not in {
            self.client_order_id,
            self.exchange_order_id,
        }:
            raise ValueError("order fee scope must match an exact order ID")
        if self.fee.scope_kind == "FILL" and any(
            item.fill_id != self.fee.scope_reference for item in self.fee.components
        ):
            raise ValueError("fill fee component differs from its exact fill scope")
        if self.fee_usd is not None and not self.fee_usd.is_finite():
            raise ValueError("USD fee must be finite")
        if (
            self.fee.coverage == "FINAL"
            and not self.fee.components
            and self.fee_usd not in (None, Decimal(0))
        ):
            raise ValueError("a proven empty fee set cannot have a nonzero USD valuation")
        if self.fee.usd_status == "FINAL" and self.fee_usd != 0:
            raise ValueError("a zero-component final fee valuation must be zero USD")
        if any(item.source_received_at_ms > self.occurred_at_ms for item in self.fee.components):
            raise ValueError("fee observation cannot precede its source receipt")
        pairs: list[tuple[str, str]] = []
        for key, value in self.details:
            if not key or key != key.strip() or value != value.strip():
                raise ValueError("event details must contain normalized string pairs")
            pairs.append((key, value))
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("event detail keys must be unique")
        object.__setattr__(self, "details", tuple(sorted(pairs)))
        expected_id = canonical_sha256(self.identity_payload())
        if self.fee.supersedes_event_id == expected_id:
            raise ValueError("fee observation cannot supersede itself")
        if self.event_id is not None and self.event_id != expected_id:
            raise ValueError("event_id does not match the canonical execution fact")
        object.__setattr__(self, "event_id", expected_id)
        if "message_id" not in self.model_fields_set:
            object.__setattr__(self, "message_id", expected_id)
        if "correlation_id" not in self.model_fields_set:
            object.__setattr__(self, "correlation_id", self.trade_id)
        if "produced_at" not in self.model_fields_set:
            object.__setattr__(self, "produced_at", datetime_from_unix_ms(self.occurred_at_ms))
        return self

    def identity_payload(self) -> dict[str, object]:
        # Base-envelope metadata stays outside the fact identity as in V1.
        return self.model_dump(
            mode="json",
            exclude={
                "event_id",
                "schema_version",
                "message_id",
                "correlation_id",
                "causation_id",
                "produced_at",
                "source",
            },
        )


def parse_trade_execution_event(payload: object) -> TradeExecutionEventV1 | TradeExecutionEventV2:
    """Explicitly dispatch the immutable versions; never infer a missing one."""
    if not isinstance(payload, dict):
        raise ValueError("execution event payload must be an object")
    version = payload.get("contract_version")
    if version == "trade-execution-event.v1":
        return TradeExecutionEventV1.model_validate(payload)
    if version == "trade-execution-event.v2":
        return TradeExecutionEventV2.model_validate(payload)
    raise ValueError("unsupported execution event contract version")

"""Strict account and execution facts for the crash-safe PAPER lifecycle."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from ..enums import (
    EvedexProfile,
    OrderRole,
    OrderSide,
    OrderStatus,
    OrderType,
    Side,
    TradeExecutionEventType,
    TradeExitReason,
    TradeLifecycleState,
    TradingMode,
)
from .base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    canonical_sha256,
    datetime_from_unix_ms,
)
from .strategy import ExitPlanV1, NonNegativeFloat, NonNegativeInt, PositiveFloat, Sha256Hex


def _normalized(value: str, name: str, *, uppercase: bool = False) -> str:
    expected = value.strip().upper() if uppercase else value.strip()
    if not expected or value != expected:
        raise ValueError(f"{name} must be a non-empty normalized string")
    return value


def _validate_environment(mode: TradingMode, profile: EvedexProfile, venue_symbol: str) -> None:
    if mode is TradingMode.PAPER and (profile is not EvedexProfile.DEV or not venue_symbol.endswith(":DEV")):
        raise ValueError("PAPER lineage requires the exact EVEDEX DEV profile and :DEV symbol")
    if mode is TradingMode.LIVE and profile is not EvedexProfile.PROD:
        raise ValueError("LIVE lineage requires the EVEDEX PROD profile")


class TradeExecutionEventV1(StrictKairosMessage):
    """Append-only execution fact with complete strategy/trade/order lineage."""

    contract_version: Literal["trade-execution-event.v1"] = "trade-execution-event.v1"
    event_id: Sha256Hex | None = None
    event_seq: int = Field(..., gt=0)
    occurred_at_ms: NonNegativeInt
    event_type: TradeExecutionEventType
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
    requested_quantity: NonNegativeFloat = 0.0
    filled_quantity: NonNegativeFloat = 0.0
    position_quantity: float = 0.0
    average_price: PositiveFloat | None = None
    fee_usd: NonNegativeFloat = 0.0
    exit_reason: TradeExitReason | None = None
    details: tuple[tuple[str, str], ...] = ()

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
        if self.filled_quantity > self.requested_quantity and self.requested_quantity > 0:
            raise ValueError("filled_quantity cannot exceed requested_quantity")
        order_values = (self.client_order_id, self.exchange_order_id)
        if any(value is not None for value in order_values) and self.order_role is None:
            raise ValueError("order identifiers require an order_role")
        if self.order_role is not None and self.client_order_id is None:
            raise ValueError("order_role requires a deterministic client_order_id")
        if self.event_type is TradeExecutionEventType.EFFECT_PREPARED and self.effect_id is None:
            raise ValueError("EFFECT_PREPARED requires effect_id")
        exit_events = {
            TradeExecutionEventType.EXIT_TRIGGERED,
            TradeExecutionEventType.EXIT_FILLED,
            TradeExecutionEventType.EMERGENCY_CLOSE,
        }
        if self.exit_reason is not None and self.event_type not in exit_events:
            raise ValueError("exit_reason is only valid on exit lifecycle events")
        if self.event_type in exit_events and self.exit_reason is None:
            raise ValueError("exit lifecycle events require exit_reason")
        pairs: list[tuple[str, str]] = []
        for key, value in self.details:
            if not key or key != key.strip() or value != value.strip():
                raise ValueError("event details must contain normalized string pairs")
            pairs.append((key, value))
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("event detail keys must be unique")
        object.__setattr__(self, "details", tuple(sorted(pairs)))
        expected_id = canonical_sha256(self.identity_payload())
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
        return {
            "account_id": self.account_id,
            "average_price": self.average_price,
            "client_order_id": self.client_order_id,
            "contract_version": self.contract_version,
            "details": self.details,
            "effect_id": self.effect_id,
            "event_seq": self.event_seq,
            "event_type": self.event_type.value,
            "evedex_profile": self.evedex_profile.value,
            "exchange_order_id": self.exchange_order_id,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "fee_usd": self.fee_usd,
            "filled_quantity": self.filled_quantity,
            "intent_id": self.intent_id,
            "lifecycle_state": self.lifecycle_state.value,
            "occurred_at_ms": self.occurred_at_ms,
            "order_role": self.order_role.value if self.order_role else None,
            "position_quantity": self.position_quantity,
            "requested_quantity": self.requested_quantity,
            "risk_decision_id": self.risk_decision_id,
            "strategy_id": self.strategy_id,
            "strategy_revision": self.strategy_revision,
            "trade_id": self.trade_id,
            "trading_mode": self.trading_mode.value,
            "venue_symbol": self.venue_symbol,
        }


class PositionSnapshotV2(StrictValueModel):
    """Authoritative EVEDEX position enriched with Kairos trade lineage."""

    venue_symbol: str = Field(..., min_length=2, max_length=64)
    side: Side
    signed_quantity: float
    entry_price: PositiveFloat
    mark_price: PositiveFloat
    leverage: float = Field(..., ge=1, le=125)
    liquidation_price: PositiveFloat | None = None
    unrealized_pnl_usd: float = 0.0
    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    intent_id: Sha256Hex
    risk_decision_id: Sha256Hex
    trade_id: Sha256Hex
    lifecycle_state: TradeLifecycleState
    entry_client_order_id: str = Field(..., min_length=8, max_length=64)
    stop_client_order_id: str | None = Field(default=None, min_length=8, max_length=64)
    target_client_order_id: str | None = Field(default=None, min_length=8, max_length=64)
    first_fill_at_ms: NonNegativeInt
    timeout_at_ms: NonNegativeInt
    exit_plan: ExitPlanV1

    @field_validator("venue_symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized(value, "venue_symbol", uppercase=True)

    @field_validator("strategy_id", "strategy_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized(value, info.field_name)

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        if self.side is Side.FLAT or self.signed_quantity == 0:
            raise ValueError("active positions must have LONG/SHORT side and non-zero quantity")
        if self.side is Side.LONG and self.signed_quantity < 0:
            raise ValueError("LONG positions require positive signed_quantity")
        if self.side is Side.SHORT and self.signed_quantity > 0:
            raise ValueError("SHORT positions require negative signed_quantity")
        if self.timeout_at_ms != self.first_fill_at_ms + self.exit_plan.max_holding_ms:
            raise ValueError("timeout_at_ms must begin at the first non-zero fill")
        if self.lifecycle_state not in {
            TradeLifecycleState.PROTECTING,
            TradeLifecycleState.ACTIVE,
            TradeLifecycleState.EXITING_STOP,
            TradeLifecycleState.EXITING_TARGET,
            TradeLifecycleState.EXITING_TIMEOUT,
            TradeLifecycleState.FAILED_BLOCKED,
        }:
            raise ValueError("active position has an incompatible lifecycle_state")
        if (
            self.lifecycle_state
            in {
                TradeLifecycleState.ACTIVE,
                TradeLifecycleState.EXITING_STOP,
                TradeLifecycleState.EXITING_TARGET,
                TradeLifecycleState.EXITING_TIMEOUT,
            }
            and self.stop_client_order_id is None
        ):
            raise ValueError("ACTIVE and EXITING positions require a reconciled protective stop")
        return self


class OpenOrderSnapshotV2(StrictValueModel):
    """Open EVEDEX order with deterministic role and owning trade."""

    venue_symbol: str = Field(..., min_length=2, max_length=64)
    client_order_id: str = Field(..., min_length=8, max_length=64)
    exchange_order_id: str = Field(..., min_length=1, max_length=128)
    order_role: OrderRole
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    quantity: PositiveFloat
    filled_quantity: NonNegativeFloat = 0.0
    price: PositiveFloat | None = None
    stop_price: PositiveFloat | None = None
    reduce_only: bool
    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    intent_id: Sha256Hex
    risk_decision_id: Sha256Hex
    trade_id: Sha256Hex
    created_at_ms: NonNegativeInt
    updated_at_ms: NonNegativeInt

    @field_validator("venue_symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized(value, "venue_symbol", uppercase=True)

    @field_validator("strategy_id", "strategy_revision")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized(value, info.field_name)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.filled_quantity > self.quantity:
            raise ValueError("filled_quantity cannot exceed order quantity")
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("order update cannot predate order creation")
        if self.status not in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("open order snapshots may only contain NEW or PARTIALLY_FILLED orders")
        if self.order_role is not OrderRole.ENTRY and not self.reduce_only:
            raise ValueError("protective and exit orders must be reduce-only")
        return self


class AccountSnapshotV2(StrictKairosMessage):
    """Reconciled account state with durable equity and complete order lineage."""

    contract_version: Literal["account-snapshot.v2"] = "account-snapshot.v2"
    snapshot_id: Sha256Hex | None = None
    exchange: Literal["EVEDEX"] = "EVEDEX"
    trading_mode: TradingMode
    evedex_profile: EvedexProfile
    account_id: str = Field(..., min_length=1, max_length=128)
    equity_usd: PositiveFloat
    available_balance_usd: NonNegativeFloat
    margin_used_usd: NonNegativeFloat
    durable_day_start_equity_usd: PositiveFloat
    durable_peak_equity_usd: PositiveFloat
    daily_realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    total_open_risk_usd: NonNegativeFloat = 0.0
    positions: tuple[PositionSnapshotV2, ...] = ()
    open_orders: tuple[OpenOrderSnapshotV2, ...] = ()
    captured_at_ms: NonNegativeInt
    reconciliation_seq: NonNegativeInt
    reconciled: bool
    reconciliation_detail: str = Field(default="", max_length=2_048)

    @field_validator("account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        return _normalized(value, "account_id")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.trading_mode is TradingMode.PAPER and self.evedex_profile is not EvedexProfile.DEV:
            raise ValueError("PAPER account snapshots require the EVEDEX DEV profile")
        if self.trading_mode is TradingMode.LIVE and self.evedex_profile is not EvedexProfile.PROD:
            raise ValueError("LIVE account snapshots require the EVEDEX PROD profile")
        if self.durable_peak_equity_usd < self.equity_usd:
            raise ValueError("durable_peak_equity_usd cannot be below current equity")
        position_symbols = [position.venue_symbol for position in self.positions]
        if len(position_symbols) != len(set(position_symbols)):
            raise ValueError("at most one active position is allowed per symbol")
        trade_ids = [position.trade_id for position in self.positions]
        if len(trade_ids) != len(set(trade_ids)):
            raise ValueError("active position trade_id values must be unique")
        client_order_ids = [order.client_order_id for order in self.open_orders]
        exchange_order_ids = [order.exchange_order_id for order in self.open_orders]
        if len(client_order_ids) != len(set(client_order_ids)):
            raise ValueError("open client_order_id values must be unique")
        if len(exchange_order_ids) != len(set(exchange_order_ids)):
            raise ValueError("open exchange_order_id values must be unique")
        object.__setattr__(
            self,
            "positions",
            tuple(sorted(self.positions, key=lambda item: (item.venue_symbol, item.trade_id))),
        )
        object.__setattr__(
            self,
            "open_orders",
            tuple(sorted(self.open_orders, key=lambda item: item.client_order_id)),
        )
        expected_id = canonical_sha256(self.identity_payload())
        if self.snapshot_id is not None and self.snapshot_id != expected_id:
            raise ValueError("snapshot_id does not match canonical account state")
        object.__setattr__(self, "snapshot_id", expected_id)
        if "message_id" not in self.model_fields_set:
            object.__setattr__(self, "message_id", expected_id)
        if "correlation_id" not in self.model_fields_set:
            object.__setattr__(self, "correlation_id", expected_id)
        if "produced_at" not in self.model_fields_set:
            object.__setattr__(self, "produced_at", datetime_from_unix_ms(self.captured_at_ms))
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "available_balance_usd": self.available_balance_usd,
            "captured_at_ms": self.captured_at_ms,
            "contract_version": self.contract_version,
            "daily_realized_pnl_usd": self.daily_realized_pnl_usd,
            "durable_day_start_equity_usd": self.durable_day_start_equity_usd,
            "durable_peak_equity_usd": self.durable_peak_equity_usd,
            "equity_usd": self.equity_usd,
            "evedex_profile": self.evedex_profile.value,
            "exchange": self.exchange,
            "margin_used_usd": self.margin_used_usd,
            "open_orders": [item.model_dump(mode="json") for item in self.open_orders],
            "positions": [item.model_dump(mode="json") for item in self.positions],
            "reconciled": self.reconciled,
            "reconciliation_detail": self.reconciliation_detail,
            "reconciliation_seq": self.reconciliation_seq,
            "total_open_risk_usd": self.total_open_risk_usd,
            "trading_mode": self.trading_mode.value,
            "unrealized_pnl_usd": self.unrealized_pnl_usd,
        }

    def canonical_snapshot_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

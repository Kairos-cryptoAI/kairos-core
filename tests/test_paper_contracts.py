"""Execution lifecycle and reconciled account contract tests."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kairos_core import (
    AccountSnapshotV2,
    EvedexProfile,
    ExitPlanV1,
    OpenOrderSnapshotV2,
    OrderRole,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshotV2,
    Side,
    TradeExecutionEventType,
    TradeExecutionEventV1,
    TradeExitReason,
    TradeLifecycleState,
    TradingMode,
)

T0 = 1_800_000_000_000
INTENT_ID = "1" * 64
DECISION_ID = "2" * 64
TRADE_ID = "3" * 64
PLAN = ExitPlanV1(stop_price=95, target_price=105, max_holding_ms=180_000)


def _event(**overrides: object) -> TradeExecutionEventV1:
    values: dict[str, object] = {
        "source": "execution-engine",
        "event_seq": 1,
        "occurred_at_ms": T0,
        "event_type": TradeExecutionEventType.DECISION_RECEIVED,
        "lifecycle_state": TradeLifecycleState.RECEIVED,
        "trading_mode": TradingMode.PAPER,
        "evedex_profile": EvedexProfile.DEV,
        "account_id": "kairos-paper-dev-01",
        "venue_symbol": "BTCUSD:DEV",
        "strategy_id": "trend-breakout",
        "strategy_revision": "2026-08-23.1",
        "intent_id": INTENT_ID,
        "risk_decision_id": DECISION_ID,
        "trade_id": TRADE_ID,
    }
    values.update(overrides)
    return TradeExecutionEventV1(**values)


def _position(**overrides: object) -> PositionSnapshotV2:
    values: dict[str, object] = {
        "venue_symbol": "BTCUSD:DEV",
        "side": Side.LONG,
        "signed_quantity": 0.1,
        "entry_price": 100.5,
        "mark_price": 101.0,
        "leverage": 1.0,
        "unrealized_pnl_usd": 0.05,
        "strategy_id": "trend-breakout",
        "strategy_revision": "2026-08-23.1",
        "intent_id": INTENT_ID,
        "risk_decision_id": DECISION_ID,
        "trade_id": TRADE_ID,
        "lifecycle_state": TradeLifecycleState.ACTIVE,
        "entry_client_order_id": "entry-order-0001",
        "stop_client_order_id": "stop-order-00001",
        "target_client_order_id": "target-order-001",
        "first_fill_at_ms": T0,
        "timeout_at_ms": T0 + PLAN.max_holding_ms,
        "exit_plan": PLAN,
    }
    values.update(overrides)
    return PositionSnapshotV2(**values)


def _stop_order(**overrides: object) -> OpenOrderSnapshotV2:
    values: dict[str, object] = {
        "venue_symbol": "BTCUSD:DEV",
        "client_order_id": "stop-order-00001",
        "exchange_order_id": "venue-stop-1",
        "order_role": OrderRole.STOP_LOSS,
        "side": OrderSide.SELL,
        "order_type": OrderType.STOP_LIMIT,
        "status": OrderStatus.NEW,
        "quantity": 0.1,
        "stop_price": 95.0,
        "reduce_only": True,
        "strategy_id": "trend-breakout",
        "strategy_revision": "2026-08-23.1",
        "intent_id": INTENT_ID,
        "risk_decision_id": DECISION_ID,
        "trade_id": TRADE_ID,
        "created_at_ms": T0,
        "updated_at_ms": T0 + 1_000,
    }
    values.update(overrides)
    return OpenOrderSnapshotV2(**values)


def _snapshot(**overrides: object) -> AccountSnapshotV2:
    values: dict[str, object] = {
        "source": "execution-engine",
        "trading_mode": TradingMode.PAPER,
        "evedex_profile": EvedexProfile.DEV,
        "account_id": "kairos-paper-dev-01",
        "equity_usd": 1_005.0,
        "available_balance_usd": 990.0,
        "margin_used_usd": 10.0,
        "durable_day_start_equity_usd": 1_000.0,
        "durable_peak_equity_usd": 1_010.0,
        "daily_realized_pnl_usd": 4.95,
        "unrealized_pnl_usd": 0.05,
        "total_open_risk_usd": 0.55,
        "positions": (_position(),),
        "open_orders": (_stop_order(),),
        "captured_at_ms": T0 + 2_000,
        "reconciliation_seq": 7,
        "reconciled": True,
    }
    values.update(overrides)
    return AccountSnapshotV2(**values)


def test_execution_event_has_stable_full_lineage_and_id() -> None:
    first = _event()
    second = _event()
    assert first.event_id == second.event_id
    assert first.to_json() == second.to_json()
    assert first.correlation_id == TRADE_ID
    prepared = _event(
        event_seq=2,
        event_type=TradeExecutionEventType.EFFECT_PREPARED,
        lifecycle_state=TradeLifecycleState.ENTRY_PENDING,
        effect_id="effect-entry-1",
        order_role=OrderRole.ENTRY,
        client_order_id="entry-order-0001",
        requested_quantity=0.1,
    )
    assert prepared.event_id != first.event_id


def test_execution_event_rejects_missing_effect_order_role_and_exit_reason() -> None:
    with pytest.raises(ValidationError):
        _event(event_type=TradeExecutionEventType.EFFECT_PREPARED)
    with pytest.raises(ValidationError):
        _event(client_order_id="entry-order-0001")
    with pytest.raises(ValidationError):
        _event(
            event_type=TradeExecutionEventType.EXIT_TRIGGERED,
            lifecycle_state=TradeLifecycleState.EXITING_STOP,
        )
    exited = _event(
        event_type=TradeExecutionEventType.EXIT_TRIGGERED,
        lifecycle_state=TradeLifecycleState.EXITING_STOP,
        exit_reason=TradeExitReason.STOP,
    )
    assert exited.exit_reason is TradeExitReason.STOP


def test_account_snapshot_carries_complete_durable_lineage() -> None:
    snapshot = _snapshot()
    assert snapshot.snapshot_id
    assert snapshot.positions[0].intent_id == INTENT_ID
    assert snapshot.open_orders[0].order_role is OrderRole.STOP_LOSS
    assert snapshot.positions[0].timeout_at_ms == T0 + PLAN.max_holding_ms
    assert AccountSnapshotV2.from_json(snapshot.to_json()) == snapshot


@pytest.mark.parametrize(
    "override",
    [
        {"durable_peak_equity_usd": 999.0},
        {"evedex_profile": EvedexProfile.DEMO},
        {"equity_usd": math.inf},
        {"unexpected": "field"},
    ],
)
def test_account_snapshot_rejects_bad_environment_equity_and_unknown_fields(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**override)


def test_position_timeout_starts_at_first_fill_and_exit_orders_are_reduce_only() -> None:
    with pytest.raises(ValidationError):
        _position(timeout_at_ms=T0 + PLAN.max_holding_ms + 1)
    with pytest.raises(ValidationError):
        _stop_order(reduce_only=False)


def test_account_snapshot_blocks_two_positions_for_one_symbol() -> None:
    second = _position(
        trade_id="4" * 64,
        intent_id="5" * 64,
        risk_decision_id="6" * 64,
        entry_client_order_id="entry-order-0002",
        stop_client_order_id="stop-order-00002",
        target_client_order_id="target-order-002",
    )
    with pytest.raises(ValidationError):
        _snapshot(positions=(_position(), second))

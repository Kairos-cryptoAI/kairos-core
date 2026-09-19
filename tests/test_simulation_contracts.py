"""Strict boundary tests for the isolated market-data simulator contracts."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kairos_core import (
    ClosedBarEventV1,
    ExitPlanV1,
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    Side,
    SimulationAdmissionV1,
    SimulationAssumptionsV1,
    SimulationResultV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
    SimulationTradeEventV1,
    StrategyIntentV1,
    StrategyProvenanceV1,
    TradingMode,
)

T0 = 1_800_000_000_000
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _intent(**overrides: object) -> StrategyIntentV1:
    bar = ClosedBarEventV1(
        source="quant-scouts",
        symbol="BTCUSDT",
        open_time_ms=T0,
        close_time_ms=T0 + 59_999,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        base_volume=20.0,
        quote_volume=2_010.0,
        taker_buy_base_volume=11.0,
        taker_buy_quote_volume=1_110.0,
    )
    values: dict[str, object] = {
        "source": "strategy-engine",
        "strategy_id": "regime-aligned-right-tail",
        "strategy_revision": "v1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "decision_ts_ms": T0 + 59_999,
        "entry_eligible_ts_ms": T0 + 60_000,
        "entry_expires_ts_ms": T0 + 120_000,
        "reference_price": 100.0,
        "signal_strength": 0.5,
        "gross_reward_bps": 500.0,
        "exit_plan": ExitPlanV1(stop_price=95.0, target_price=105.0, max_holding_ms=180_000),
        "provenance": StrategyProvenanceV1(
            strategy_code_sha256=SHA_A,
            config_sha256=SHA_B,
            input_window_sha256=SHA_C,
            features_sha256=SHA_D,
            input_bar_sha256s=(bar.bar_sha256,),
        ),
    }
    values.update(overrides)
    return StrategyIntentV1(**values)


def _frame(**overrides: object) -> RecordedTopNBookFrameV1:
    values: dict[str, object] = {
        "source": "sim-recorder",
        "tape_id": "binance-20260919",
        "stream_epoch": "epoch-1",
        "symbol": "BTCUSDT",
        "tape_sequence": 1,
        "exchange_update_id": 100,
        "exchange_at_ms": T0 + 60_000,
        "received_at_ms": T0 + 60_010,
        "persisted_at_ms": T0 + 60_020,
        "raw_payload_sha256": SHA_A,
        "continuity": "ADMITTED",
        "bids": (RecordedBookLevelV1(price=99.9, quantity=2.0),),
        "asks": (RecordedBookLevelV1(price=100.1, quantity=2.0),),
    }
    values.update(overrides)
    return RecordedTopNBookFrameV1(**values)


def _assumptions(**overrides: object) -> SimulationAssumptionsV1:
    values: dict[str, object] = {
        "latency_ms": 25,
        "maximum_book_age_ms": 5_000,
        "maximum_frame_latency_ms": 1_000,
        "depth_participation_fraction": 0.1,
        "adverse_slippage_bps": 2.0,
        "taker_fee_bps": 5.0,
        "price_tick": 0.1,
        "quantity_step": 0.001,
    }
    values.update(overrides)
    return SimulationAssumptionsV1(**values)


def _session(**overrides: object) -> SimulationSessionV1:
    values: dict[str, object] = {
        "source": "market-simulator",
        "tape_id": "binance-20260919",
        "tape_sha256": SHA_B,
        "assumptions": _assumptions(),
        "strategy_allowlist": (
            SimulationStrategyRefV1(strategy_id="regime-aligned-right-tail", strategy_revision="v1"),
        ),
        "started_at_ms": T0,
        "ends_at_ms": T0 + 600_000,
    }
    values.update(overrides)
    return SimulationSessionV1(**values)


def _admission(**overrides: object) -> SimulationAdmissionV1:
    values: dict[str, object] = {
        "source": "market-simulator",
        "session": _session(),
        "intent": _intent(),
        "quantity": 0.01,
        "price_cap": 100.2,
        "admitted_at_ms": T0 + 60_000,
    }
    values.update(overrides)
    return SimulationAdmissionV1(**values)


def test_recorded_frame_is_hash_chained_deterministic_and_strict() -> None:
    first = _frame()
    second = _frame()
    assert first.frame_sha256 == second.frame_sha256
    assert first.canonical_frame_bytes() == second.canonical_frame_bytes()
    assert first.message_id == first.frame_sha256
    assert RecordedTopNBookFrameV1.from_json(first.to_json()) == first

    chained = _frame(
        tape_sequence=2,
        exchange_update_id=101,
        exchange_at_ms=T0 + 60_100,
        received_at_ms=T0 + 60_110,
        persisted_at_ms=T0 + 60_120,
        raw_payload_sha256=SHA_B,
        previous_frame_sha256=first.frame_sha256,
    )
    assert chained.previous_frame_sha256 == first.frame_sha256
    with pytest.raises(ValidationError):
        _frame(tape_sequence=2)
    with pytest.raises(ValidationError):
        _frame(unknown="not understood")


@pytest.mark.parametrize(
    "override",
    [
        {"asks": ()},
        {"bids": (RecordedBookLevelV1(price=100.1, quantity=1.0),)},
        {"received_at_ms": T0 + 59_999},
        {"raw_payload_sha256": "0" * 64, "frame_sha256": "1" * 64},
        {
            "bids": (
                RecordedBookLevelV1(price=99.8, quantity=1.0),
                RecordedBookLevelV1(price=99.9, quantity=1.0),
            )
        },
    ],
)
def test_recorded_frame_rejects_unusable_chain_clock_and_book(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _frame(**override)


def test_session_has_a_frozen_research_only_boundary() -> None:
    first = _session()
    second = _session()
    assert first.session_id == second.session_id
    assert first.paper_qualification_eligible is False
    assert first.trial15_eligible is False
    assert first.alpha_claim is False
    assert TradingMode.__members__.keys() == {"DRY_RUN", "PAPER", "LIVE"}
    with pytest.raises(ValidationError):
        _session(trading_mode="PAPER")
    with pytest.raises(ValidationError):
        _assumptions(adverse_slippage_bps=math.inf)
    with pytest.raises(ValidationError):
        _assumptions(max_terminal_commands=1_025)


def test_admission_binds_the_same_intent_without_risk_or_paper_lineage() -> None:
    admission = _admission()
    assert admission.intent_sha256 == admission.intent.intent_id
    assert admission.session_id == admission.session.session_id
    assert admission.admission_id
    with pytest.raises(ValidationError, match="allowlist"):
        _admission(intent=_intent(strategy_revision="v2"))
    with pytest.raises(ValidationError, match="price cap"):
        _admission(price_cap=99.9)
    with pytest.raises(ValidationError):
        _admission(account_id="never accepted")


def test_simulated_events_and_results_cannot_claim_venue_or_alpha() -> None:
    admission = _admission()
    event = SimulationTradeEventV1(
        source="market-simulator",
        session_id=admission.session_id,
        admission_id=admission.admission_id,
        intent_id=admission.intent_sha256,
        trade_id=SHA_C,
        event_seq=1,
        event_type="ENTRY_FILLED",
        occurred_at_ms=T0 + 60_100,
        symbol="BTCUSDT",
        side="LONG",
        filled_quantity=0.01,
        average_price=100.1,
        model_frame_sha256=_frame().frame_sha256,
        reason_codes=("MODEL_IOC",),
    )
    assert event.event_id
    result = SimulationResultV1(
        source="market-simulator",
        session_id=admission.session_id,
        admission_id=admission.admission_id,
        intent_id=admission.intent_sha256,
        trade_id=SHA_C,
        terminal_event_id=event.event_id,
        completed_at_ms=T0 + 120_000,
        final_state="UNRESOLVED",
        entry_filled_quantity=0.01,
        exit_filled_quantity=0,
        entry_average_price=100.1,
        reason_codes=("NO_ADMITTED_BOOK",),
    )
    assert result.execution_environment == "SIMULATED"
    assert result.venue_execution_observed is False
    with pytest.raises(ValidationError):
        SimulationResultV1.model_validate(result.model_dump() | {"paper_qualification_eligible": True})
    with pytest.raises(ValidationError):
        SimulationTradeEventV1.model_validate(event.model_dump() | {"alpha_claim": True})
    with pytest.raises(ValidationError):
        SimulationResultV1.model_validate(result.model_dump() | {"execution_environment": "PAPER"})

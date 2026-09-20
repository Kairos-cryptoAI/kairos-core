"""Strict boundary tests for the isolated market-data simulator contracts."""

from __future__ import annotations

import hashlib
import math

import pytest
from pydantic import ValidationError

from kairos_core import (
    CandidateReviewTier,
    CandidateReviewV1,
    CandidateRouteV1,
    ClosedBarEventV1,
    ExitPlanV1,
    ReasoningEffort,
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    RecordedTopNBookFrameV2,
    ReviewDecision,
    Side,
    SimulationAdmissionV1,
    SimulationAdmissionV2,
    SimulationAssumptionsV1,
    SimulationBookChainHeadV1,
    SimulationChainHeadV1,
    SimulationCommandReceiptV1,
    SimulationCommandV1,
    SimulationFillLevelV1,
    SimulationResultV1,
    SimulationRiskDecisionV1,
    SimulationSessionReceiptV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
    SimulationTapeSealV1,
    SimulationTradeEventV1,
    SimulationTradeEventV2,
    SimulationTradeJournalHeadV1,
    SimulationTradeV1,
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
RAW_PAYLOAD = '{"lastUpdateId":100,"bids":[["99.9","2.0"]],"asks":[["100.1","2.0"]]}'


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


def _frame_v2(**overrides: object) -> RecordedTopNBookFrameV2:
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
        "raw_payload": RAW_PAYLOAD,
        "raw_payload_sha256": hashlib.sha256(RAW_PAYLOAD.encode("utf-8")).hexdigest(),
        "continuity": "ADMITTED",
        "source_reason": "SNAPSHOT_RECEIVED",
        "bids": (RecordedBookLevelV1(price=99.9, quantity=2.0),),
        "asks": (RecordedBookLevelV1(price=100.1, quantity=2.0),),
    }
    values.update(overrides)
    return RecordedTopNBookFrameV2(**values)


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


def _route(**overrides: object) -> CandidateRouteV1:
    values: dict[str, object] = {
        "source": "router",
        "intent": _intent(),
        "review_tier": CandidateReviewTier.NORMAL,
        "requested_reasoning_effort": ReasoningEffort.MEDIUM,
        "routed_at_ms": T0 + 60_000,
        "review_deadline_ms": T0 + 80_000,
    }
    values.update(overrides)
    return CandidateRouteV1(**values)


def _review(**overrides: object) -> CandidateReviewV1:
    route = _route()
    values: dict[str, object] = {
        "source": "aggregator",
        "route": route,
        "intent": route.intent,
        "decision": ReviewDecision.ALLOW,
        "priority": 0,
        "reviewed_at_ms": T0 + 60_050,
        "reviewer": "DETERMINISTIC",
        "reason_codes": ("SIM_TEST_ALLOW",),
    }
    values.update(overrides)
    return CandidateReviewV1(**values)


def _simulation_decision(**overrides: object) -> SimulationRiskDecisionV1:
    session = _session()
    review = _review()
    values: dict[str, object] = {
        "source": "simulation-risk",
        "session": session,
        "intent": review.intent,
        "review": review,
        "selected_book_frame": _frame(),
        "approved": True,
        "quantity": 0.01,
        "price_cap": 100.2,
        "decided_at_ms": T0 + 60_100,
    }
    values.update(overrides)
    return SimulationRiskDecisionV1(**values)


def _admission_v2(**overrides: object) -> SimulationAdmissionV2:
    values: dict[str, object] = {
        "source": "market-simulator",
        "decision": _simulation_decision(),
        "admitted_at_ms": T0 + 60_110,
    }
    values.update(overrides)
    return SimulationAdmissionV2(**values)


def _tape_seal(**overrides: object) -> SimulationTapeSealV1:
    values: dict[str, object] = {
        "source": "sim-recorder",
        "tape_id": "binance-20260919",
        "sealed_at_ms": T0 + 600_000,
        "bar_chains": (
            SimulationChainHeadV1(symbol="BTCUSDT", entry_count=1, head_sha256=SHA_A),
            SimulationChainHeadV1(symbol="ETHUSDT", entry_count=1, head_sha256=SHA_B),
            SimulationChainHeadV1(symbol="SOLUSDT", entry_count=1, head_sha256=SHA_C),
            SimulationChainHeadV1(symbol="BNBUSDT", entry_count=1, head_sha256=SHA_D),
            SimulationChainHeadV1(symbol="XRPUSDT", entry_count=1, head_sha256=SHA_E),
        ),
        "book_chain": SimulationBookChainHeadV1(entry_count=1, head_sha256=_frame().frame_sha256),
    }
    values.update(overrides)
    return SimulationTapeSealV1(**values)


def _trade(**overrides: object) -> SimulationTradeV1:
    values: dict[str, object] = {
        "source": "market-simulator",
        "admission": _admission(),
        "created_at_ms": T0 + 60_000,
    }
    values.update(overrides)
    return SimulationTradeV1(**values)


def _command(**overrides: object) -> SimulationCommandV1:
    values: dict[str, object] = {
        "source": "market-simulator",
        "trade": _trade(),
        "command_kind": "ENTRY_IOC",
        "quantity": 0.01,
        "price_cap": 100.2,
        "submitted_at_ms": T0 + 60_000,
        "persisted_at_ms": T0 + 60_001,
        "eligible_at_ms": T0 + 60_000,
        "expires_at_ms": T0 + 120_000,
    }
    values.update(overrides)
    return SimulationCommandV1(**values)


def _receipt(**overrides: object) -> SimulationCommandReceiptV1:
    values: dict[str, object] = {
        "source": "market-simulator",
        "command": _command(),
        "model_frame_sha256": _frame().frame_sha256,
        "status": "FILLED",
        "reason_codes": ("MODEL_IOC",),
        "arrival_at_ms": T0 + 60_100,
        "filled_quantity": 0.01,
        "cancelled_quantity": 0.0,
        "average_price": 100.2,
        "notional_quote": 1.002,
        "fee_quote": 0.00501,
        "arrival_mid_price": 100.0,
        "implementation_shortfall_quote": 0.002,
        "level_fills": (
            SimulationFillLevelV1(book_price=100.1, execution_price=100.2, quantity=0.01, fee_quote=0.00501),
        ),
    }
    values.update(overrides)
    return SimulationCommandReceiptV1(**values)


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


def test_recorded_frame_v1_wire_and_hash_identity_are_unchanged() -> None:
    frame = _frame()
    assert frame.contract_version == "sim-book-frame.v1"
    assert "raw_payload" not in frame.identity_payload()
    assert "source_reason" not in frame.identity_payload()
    assert "raw_payload" not in frame.to_payload()
    assert frame.frame_sha256 == hashlib.sha256(frame.canonical_frame_bytes()).hexdigest()
    with pytest.raises(ValidationError):
        _frame(raw_payload=RAW_PAYLOAD)


def test_recorded_frame_v2_retains_and_hashes_the_original_utf8_payload() -> None:
    frame = _frame_v2()
    assert frame.contract_version == "sim-book-frame.v2"
    assert frame.raw_payload == RAW_PAYLOAD
    assert frame.raw_payload_sha256 == hashlib.sha256(RAW_PAYLOAD.encode("utf-8")).hexdigest()
    assert frame.frame_sha256 == hashlib.sha256(frame.canonical_frame_bytes()).hexdigest()
    assert frame.message_id == frame.frame_sha256
    assert RecordedTopNBookFrameV2.from_json(frame.to_json()) == frame


def test_recorded_frame_v2_requires_raw_payload_and_source_reason() -> None:
    payload = _frame_v2().model_dump()
    payload.pop("raw_payload")
    with pytest.raises(ValidationError):
        RecordedTopNBookFrameV2.model_validate(payload)

    payload = _frame_v2().model_dump()
    payload.pop("source_reason")
    with pytest.raises(ValidationError):
        RecordedTopNBookFrameV2.model_validate(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"raw_payload_sha256": SHA_A},
        {"raw_payload": None},
        {"source_reason": "snapshot_received"},
        {"source_reason": "SNAPSHOT-RECEIVED"},
        {"continuity": "GAP", "bids": (RecordedBookLevelV1(price=99.9, quantity=2.0),), "asks": ()},
        {"continuity": "ADMITTED", "bids": (), "asks": ()},
    ],
)
def test_recorded_frame_v2_rejects_invalid_recorder_evidence(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _frame_v2(**override)


def test_recorded_frame_v2_records_clock_skew_as_an_empty_terminal_frame() -> None:
    frame = _frame_v2(
        continuity="CLOCK_SKEW",
        source_reason="EXCHANGE_CLOCK_SKEW",
        bids=(),
        asks=(),
    )
    assert frame.continuity == "CLOCK_SKEW"
    assert frame.bids == ()
    assert frame.asks == ()


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


def test_simulation_risk_admission_has_review_and_recorded_book_lineage() -> None:
    decision = _simulation_decision()
    admission = _admission_v2(decision=decision)
    assert decision.decision_id
    assert admission.decision_id == decision.decision_id
    assert admission.review_id == decision.review_id
    assert admission.selected_book_frame_sha256 == decision.selected_book_frame_sha256
    assert (
        SimulationTradeV1(
            source="market-simulator", admission=admission, created_at_ms=admission.admitted_at_ms
        ).admission_id
        == admission.admission_id
    )
    veto = _review(decision=ReviewDecision.VETO, reason_codes=("SIM_TEST_VETO",))
    with pytest.raises(ValidationError, match="only an ALLOW"):
        _simulation_decision(review=veto, intent=veto.intent)
    stale_review = _review(reviewed_at_ms=T0 + 69_900)
    with pytest.raises(ValidationError, match="stale"):
        _simulation_decision(
            review=stale_review,
            intent=stale_review.intent,
            decided_at_ms=T0 + 70_000,
        )
    with pytest.raises(ValidationError):
        _admission_v2(evedex_profile="DEV")


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


def test_tape_seal_records_all_input_chain_heads_and_is_deterministic() -> None:
    first = _tape_seal()
    second = _tape_seal()
    assert first.tape_sha256 == second.tape_sha256
    assert first.message_id == first.tape_sha256
    assert tuple(chain.symbol for chain in first.bar_chains) == (
        "BNBUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    )
    with pytest.raises(ValidationError, match="at least 5"):
        _tape_seal(bar_chains=_tape_seal().bar_chains[:-1])
    with pytest.raises(ValidationError, match="empty simulation book chain"):
        SimulationBookChainHeadV1(entry_count=0, head_sha256=SHA_A)
    with pytest.raises(ValidationError):
        _tape_seal(evedex_profile="DEV")


def test_command_and_receipt_have_immutable_sim_only_lineage() -> None:
    command = _command()
    receipt = _receipt(command=command)
    assert command.command_id
    assert command.order_side == "BUY"
    assert receipt.command_id == command.command_id
    command_session = command.trade.admission.session
    assert command_session is not None
    assert receipt.assumptions_sha256 == command_session.assumptions.assumptions_sha256
    assert receipt.receipt_id
    with pytest.raises(ValidationError, match="does not match the immutable simulation trade"):
        _command(symbol="ETHUSDT")
    assert _command(command_kind="TIMEOUT_EXIT_IOC").order_side == "SELL"
    with pytest.raises(ValidationError, match="order_side"):
        _command(order_side="SELL")
    with pytest.raises(ValidationError, match="submission cannot predate eligibility"):
        _command(submitted_at_ms=T0 + 59_999)
    with pytest.raises(ValidationError, match="must be filled or cancelled"):
        _receipt(command=command, cancelled_quantity=0.1)
    with pytest.raises(ValidationError, match="Input should be False"):
        _receipt(
            command=command,
            status="NO_FILL",
            model_frame_sha256=None,
            filled_quantity=0.0,
            cancelled_quantity=0.01,
            average_price=None,
            notional_quote=0.0,
            fee_quote=0.0,
            arrival_mid_price=None,
            implementation_shortfall_quote=0.0,
            level_fills=(),
            paper_qualification_eligible=True,
        )


def test_v2_event_chain_and_session_receipt_require_terminal_evidence() -> None:
    trade = _trade()
    admitted = SimulationTradeEventV2(
        source="market-simulator",
        session_id=trade.session_id,
        admission_id=trade.admission_id,
        intent_id=trade.intent_id,
        trade_id=trade.trade_id,
        event_seq=1,
        event_type="ADMITTED",
        to_state="PENDING",
        occurred_at_ms=T0 + 60_000,
        symbol="BTCUSDT",
        side="LONG",
        reason_codes=("SIM_ADMISSION",),
    )
    receipt = _receipt()
    filled = SimulationTradeEventV2(
        source="market-simulator",
        session_id=trade.session_id,
        admission_id=trade.admission_id,
        intent_id=trade.intent_id,
        trade_id=trade.trade_id,
        event_seq=2,
        previous_event_sha256=admitted.event_id,
        event_type="ENTRY_FILLED",
        from_state="PENDING",
        to_state="ACTIVE",
        occurred_at_ms=T0 + 60_100,
        symbol="BTCUSDT",
        side="LONG",
        command_id=receipt.command_id,
        receipt_id=receipt.receipt_id,
        filled_quantity=receipt.filled_quantity,
        average_price=receipt.average_price,
        model_frame_sha256=receipt.model_frame_sha256,
        reason_codes=("MODEL_IOC",),
    )
    assert filled.previous_event_sha256 == admitted.event_id
    with pytest.raises(ValidationError, match="first simulation event"):
        SimulationTradeEventV2.model_validate(
            admitted.model_dump() | {"event_seq": 2, "previous_event_sha256": None}
        )
    sealed_session = _session(tape_sha256=_tape_seal().tape_sha256)
    session_receipt = SimulationSessionReceiptV1(
        source="market-simulator",
        session=sealed_session,
        receipt_state="COMPLETED",
        completed_at_ms=T0 + 180_000,
        command_count=1,
        trade_journals=(
            SimulationTradeJournalHeadV1(
                trade_id=trade.trade_id,
                state="FLAT",
                event_count=3,
                journal_head_sha256=SHA_E,
            ),
        ),
    )
    assert session_receipt.receipt_id
    with pytest.raises(ValidationError, match="terminal"):
        SimulationSessionReceiptV1.model_validate(
            session_receipt.model_dump()
            | {
                "trade_journals": (
                    SimulationTradeJournalHeadV1(
                        trade_id=trade.trade_id,
                        state="ACTIVE",
                        event_count=2,
                        journal_head_sha256=SHA_E,
                    ),
                )
            }
        )


def test_simulator_respects_next_bar_eligibility_and_reports_partial_exit_as_unresolved() -> None:
    late_intent = _intent(entry_eligible_ts_ms=T0 + 120_000, entry_expires_ts_ms=T0 + 180_000)
    late_route = _route(intent=late_intent)
    late_review = _review(route=late_route, intent=late_intent)
    with pytest.raises(ValidationError, match="next-bar entry eligibility"):
        _simulation_decision(intent=late_intent, review=late_review, decided_at_ms=T0 + 60_100)
    with pytest.raises(ValidationError, match="next-bar entry eligibility"):
        _admission(admitted_at_ms=T0 + 59_999)

    trade = _trade()
    command = _command(command_kind="STOP_EXIT_IOC")
    receipt = _receipt(command=command)
    partial_exit = SimulationTradeEventV2(
        source="market-simulator",
        session_id=trade.session_id,
        admission_id=trade.admission_id,
        intent_id=trade.intent_id,
        trade_id=trade.trade_id,
        event_seq=2,
        previous_event_sha256=SHA_A,
        event_type="STOP_TRIGGERED",
        from_state="ACTIVE",
        to_state="UNRESOLVED",
        occurred_at_ms=T0 + 120_000,
        symbol="BTCUSDT",
        side="LONG",
        command_id=receipt.command_id,
        receipt_id=receipt.receipt_id,
        filled_quantity=0.005,
        average_price=99.9,
        model_frame_sha256=_frame().frame_sha256,
        reason_codes=("PARTIAL_EXIT",),
    )
    assert partial_exit.to_state == "UNRESOLVED"
    result = SimulationResultV1(
        source="market-simulator",
        session_id=trade.session_id,
        admission_id=trade.admission_id,
        intent_id=trade.intent_id,
        trade_id=trade.trade_id,
        terminal_event_id=partial_exit.event_id,
        completed_at_ms=T0 + 120_001,
        final_state="UNRESOLVED",
        entry_filled_quantity=0.01,
        exit_filled_quantity=0.005,
        entry_average_price=100.2,
        exit_average_price=99.9,
        model_realized_pnl_quote=-0.0015,
        model_fee_quote=0.0075,
        reason_codes=("PARTIAL_EXIT",),
    )
    assert result.exit_filled_quantity < result.entry_filled_quantity


def test_simulation_risk_can_audit_an_unallowlisted_rejection_but_never_approve_it() -> None:
    outside_intent = _intent(strategy_id="outside-strategy")
    outside_route = _route(intent=outside_intent)
    outside_review = _review(route=outside_route, intent=outside_intent)
    rejected = SimulationRiskDecisionV1(
        source="simulation-risk",
        session=_session(),
        intent=outside_intent,
        review=outside_review,
        approved=False,
        rejection_reasons=("STRATEGY_NOT_ALLOWLISTED",),
        quantity=0.0,
        decided_at_ms=T0 + 60_100,
    )
    assert rejected.approved is False
    with pytest.raises(ValidationError, match="approved simulation decision intent"):
        SimulationRiskDecisionV1.model_validate(
            rejected.model_dump()
            | {
                "approved": True,
                "rejection_reasons": (),
                "quantity": 0.01,
                "price_cap": 100.2,
                "selected_book_frame": _frame().model_dump(mode="json"),
            }
        )

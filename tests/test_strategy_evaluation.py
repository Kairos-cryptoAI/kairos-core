"""Strict observational evaluation states cannot grant trading or invent analysis."""

import pytest

from kairos_core.contracts.strategy_evaluation import StrategyEvaluationV1
from kairos_core.enums import Side, TradingMode


def _payload(**changes):
    values = dict(
        scope="STRATEGY",
        strategy_id="range_mean_reversion_v1",
        strategy_revision="1",
        registry_status="rejected",
        trading_mode=TradingMode.DRY_RUN,
        enabled_strategy_ids=("range_mean_reversion_v1",),
        runtime_policy_sha256="a" * 64,
        strategy_code_sha256="b" * 64,
        config_sha256="c" * 64,
        symbol="BTCUSDT",
        bar_open_time_ms=60_000,
        decision_ts_ms=119_999,
        anchor_bar_sha256="d" * 64,
        input_first_open_time_ms=0,
        input_bar_count=2,
        input_window_sha256="e" * 64,
        observed_at_ms=120_123,
        status="NO_INTENT",
        evaluation_complete=True,
        reason_code="COMPLETE_EVALUATION_NO_INTENT",
    )
    values.update(changes)
    return values


def test_completed_research_evaluation_has_exact_slot_and_separate_actual_clock():
    value = StrategyEvaluationV1(**_payload())
    later = StrategyEvaluationV1(**_payload(observed_at_ms=120_456))
    assert value.evaluation_id == later.evaluation_id == value.message_id
    assert value.receipt_sha256 != later.receipt_sha256
    assert value.produced_at.timestamp() == pytest.approx(120.123)
    assert value.registry_status == "rejected" and not value.trading_authority
    assert value.authority == "OBSERVATION_ONLY"
    assert StrategyEvaluationV1.model_validate(value.model_dump(mode="json")) == value
    assert value.canonical_evaluation_bytes() == value.canonical_evaluation_bytes()


def test_changed_outcome_cannot_mint_another_logical_slot():
    quiet = StrategyEvaluationV1(**_payload())
    directional = StrategyEvaluationV1(
        **_payload(
            status="INTENT", intent_ids=("f" * 64,), intent_sides=(Side.SHORT,), reason_code="GENERATED"
        )
    )
    assert quiet.evaluation_id == directional.evaluation_id
    assert quiet.receipt_sha256 != directional.receipt_sha256


@pytest.mark.parametrize("status", ["WARMUP", "NOT_SCHEDULED", "DISABLED", "UNAVAILABLE", "ERROR"])
def test_incomplete_states_cannot_claim_completed_analysis(status):
    fields = dict(status=status, error_type="ValueError" if status == "ERROR" else None)
    with pytest.raises(ValueError, match="only INTENT/NO_INTENT"):
        StrategyEvaluationV1(**_payload(**fields))
    value = StrategyEvaluationV1(**_payload(evaluation_complete=False, **fields))
    assert not value.evaluation_complete and not value.intent_ids


@pytest.mark.parametrize(
    "changes",
    [
        {"input_window_sha256": None},
        {"strategy_code_sha256": None},
        {"config_sha256": None},
        {"input_bar_count": 3},
        {"evaluation_complete": False},
        {"intent_ids": ("f" * 64,), "intent_sides": (Side.LONG,)},
        {"trading_authority": True},
        {"observed_at_ms": 119_998},
        {"scope": "ENGINE"},
        {"enabled_strategy_ids": ()},
        {"enabled_strategy_ids": ("range_mean_reversion_v1", "range_mean_reversion_v1")},
        {"trading_mode": TradingMode.PAPER},
        {"trading_mode": TradingMode.LIVE},
        {"evaluation_id": "1" * 64},
        {"receipt_sha256": "1" * 64},
        {"message_id": "another-logical-evaluation"},
        {"produced_at": "1970-01-01T00:02:00Z"},
        {"unknown_field": "not understood"},
    ],
)
def test_invalid_or_overclaiming_evaluations_fail_closed(changes):
    with pytest.raises(ValueError):
        StrategyEvaluationV1(**_payload(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"intent_sides": (Side.FLAT,)},
        {"intent_ids": ()},
        {"intent_ids": ("f" * 64, "f" * 64), "intent_sides": (Side.LONG, Side.SHORT)},
        {"error_type": "RuntimeError"},
    ],
)
def test_intent_references_must_be_directional_unique_and_exact(changes):
    values = _payload(status="INTENT", intent_ids=("f" * 64,), intent_sides=(Side.LONG,))
    values.update(changes)
    with pytest.raises(ValueError):
        StrategyEvaluationV1(**values)


def test_empty_allow_list_is_an_engine_disabled_observation_not_a_fake_strategy():
    value = StrategyEvaluationV1(
        **_payload(
            scope="ENGINE",
            strategy_id=None,
            strategy_revision=None,
            registry_status=None,
            strategy_code_sha256=None,
            config_sha256=None,
            enabled_strategy_ids=(),
            status="DISABLED",
            evaluation_complete=False,
            reason_code="EMPTY_STRATEGY_ALLOW_LIST",
        )
    )
    assert value.strategy_id is None and not value.evaluation_complete

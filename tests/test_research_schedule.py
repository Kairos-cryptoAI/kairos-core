"""Preregistered SIM coverage is exhaustive, immutable and non-executable."""

from __future__ import annotations

import pytest

from kairos_core import (
    RESEARCH_ARMS,
    ResearchDecisionSampleV1,
    ResearchObservationScheduleV1,
    ResearchObservationWindowV1,
    canonical_sha256,
)
from kairos_core.research_schedule import evaluate_research_coverage


def _schedule() -> ResearchObservationScheduleV1:
    return ResearchObservationScheduleV1(
        campaign_id="adaptive-matched-v1",
        strategy_id="adaptive-strategy-v1",
        strategy_revision="frozen-001",
        source_set_sha256="a" * 64,
        evaluator_sha256="b" * 64,
        windows=(
            ResearchObservationWindowV1(
                sample_id="sample-001",
                symbol="BTCUSDT",
                timeframe="1m",
                market_as_of_ts_ms=1_760_000_000_000,
                paired_at_ts_ms=1_760_000_001_000,
                sample_deadline_ts_ms=1_760_000_010_000,
            ),
            ResearchObservationWindowV1(
                sample_id="sample-002",
                symbol="ETHUSDT",
                timeframe="1m",
                market_as_of_ts_ms=1_760_000_060_000,
                paired_at_ts_ms=1_760_000_061_000,
                sample_deadline_ts_ms=1_760_000_070_000,
            ),
        ),
    )


def _sample(
    schedule: ResearchObservationScheduleV1,
    *,
    arm: str,
    sample_id: str,
    failed: bool = False,
) -> ResearchDecisionSampleV1:
    window = next(window for window in schedule.windows if window.sample_id == sample_id)
    data: dict[str, object] = {
        "campaign_id": schedule.campaign_id,
        "arm_id": arm,
        "sample_id": sample_id,
        "symbol": window.symbol,
        "timeframe": window.timeframe,
        "market_as_of_ts_ms": window.market_as_of_ts_ms,
        "market_snapshot_sha256": "c" * 64,
        "paired_at_ts_ms": window.paired_at_ts_ms,
        "sample_deadline_ts_ms": window.sample_deadline_ts_ms,
        "strategy_id": schedule.strategy_id,
        "strategy_revision": schedule.strategy_revision,
        "strategy_outcome": "NO_INTENT",
        "strategy_evaluation_sha256": "d" * 64,
        "strategy_evidence_as_of_ts_ms": window.market_as_of_ts_ms,
        "strategy_market_snapshot_sha256": "c" * 64,
        "llm_outcome": "NOT_CALLED",
    }
    if failed:
        data.update(
            llm_outcome="CALL_FAILED",
            llm_evidence_as_of_ts_ms=window.market_as_of_ts_ms,
            llm_market_snapshot_sha256="c" * 64,
            llm_failure_receipt_id="e" * 64,
            llm_failure_class="TIMEOUT",
            llm_failure_started_at_ts_ms=window.market_as_of_ts_ms + 100,
            llm_failure_observed_at_ts_ms=window.paired_at_ts_ms - 100,
        )
    return ResearchDecisionSampleV1(**data)


def _complete(schedule: ResearchObservationScheduleV1) -> list[ResearchDecisionSampleV1]:
    return [
        _sample(schedule, arm=arm, sample_id=window.sample_id, failed=arm == "strategy-review")
        for window in schedule.windows
        for arm in RESEARCH_ARMS
    ]


def test_canonical_schedule_and_all_outcome_windows_are_covered() -> None:
    schedule = _schedule()
    samples = _complete(schedule)
    seal = evaluate_research_coverage(schedule, reversed(samples))

    assert schedule.schedule_digest == canonical_sha256(schedule.identity_payload())
    assert seal.schedule_digest == schedule.schedule_digest
    assert seal.expected_result_count == 6
    assert seal.coverage_digest == canonical_sha256(seal.identity_payload())
    assert all(sample.strategy_outcome == "NO_INTENT" for sample in samples)
    assert any(sample.llm_outcome == "CALL_FAILED" for sample in samples)
    assert any(sample.llm_outcome == "NOT_CALLED" for sample in samples)
    assert seal.authority == "SIM_RESEARCH_ONLY"
    assert "order" not in seal.to_payload()
    assert "risk_decision" not in seal.to_payload()


def test_missing_duplicate_and_post_hoc_observations_fail_closed() -> None:
    schedule = _schedule()
    samples = _complete(schedule)
    with pytest.raises(ValueError, match="missing 1 scheduled"):
        evaluate_research_coverage(schedule, samples[:-1])
    with pytest.raises(ValueError, match="duplicate research arm"):
        evaluate_research_coverage(schedule, [*samples, samples[0]])
    extra = ResearchDecisionSampleV1.model_validate(
        {**samples[0].to_payload(), "sample_record_id": None, "sample_id": "sample-999"}
    )
    with pytest.raises(ValueError, match="post-hoc"):
        evaluate_research_coverage(schedule, [*samples, extra])
    outside_arm = ResearchDecisionSampleV1.model_validate(
        {**samples[0].to_payload(), "sample_record_id": None, "arm_id": "fourth-arm"}
    )
    with pytest.raises(ValueError, match="outside"):
        evaluate_research_coverage(schedule, [*samples[1:], outside_arm])


def test_altered_schedule_or_sample_key_and_late_window_fail_closed() -> None:
    schedule = _schedule()
    samples = _complete(schedule)
    with pytest.raises(ValueError, match="digest changed"):
        evaluate_research_coverage(schedule.model_copy(update={"source_set_sha256": "f" * 64}), samples)
    altered = samples[0].model_copy(update={"market_snapshot_sha256": "f" * 64})
    with pytest.raises(ValueError, match="ID changed"):
        evaluate_research_coverage(schedule, [altered, *samples[1:]])
    with pytest.raises(ValueError, match="deadline"):
        ResearchObservationWindowV1(
            sample_id="late",
            symbol="BTCUSDT",
            timeframe="1m",
            market_as_of_ts_ms=100,
            paired_at_ts_ms=200,
            sample_deadline_ts_ms=200,
        )
    with pytest.raises(ValueError, match="duplicate sample_id"):
        ResearchObservationScheduleV1(
            campaign_id="c",
            strategy_id="s",
            strategy_revision="r",
            source_set_sha256="a" * 64,
            evaluator_sha256="b" * 64,
            windows=(schedule.windows[0], schedule.windows[0]),
        )


def test_strategy_only_arm_never_uses_llm_and_arm_set_cannot_drift() -> None:
    schedule = _schedule()
    samples = _complete(schedule)
    control_failed = _sample(schedule, arm="strategy-only", sample_id="sample-001", failed=True)
    with pytest.raises(ValueError, match="strategy-only control"):
        evaluate_research_coverage(schedule, [control_failed, *samples[1:]])
    with pytest.raises(ValueError, match="three fixed arms"):
        ResearchObservationScheduleV1(
            campaign_id="c",
            strategy_id="s",
            strategy_revision="r",
            source_set_sha256="a" * 64,
            evaluator_sha256="b" * 64,
            arm_ids=("strategy-review", "strategy-only", "llm-proposal-research"),
            windows=(schedule.windows[0],),
        )

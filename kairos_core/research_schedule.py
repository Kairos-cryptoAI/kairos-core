"""Deterministic, outcome-inclusive coverage gate for preregistered SIM research."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts.base import canonical_sha256
from .contracts.research_decision import ResearchDecisionSampleV1
from .contracts.research_schedule import (
    RESEARCH_ARMS,
    ResearchCoverageSealV1,
    ResearchObservationScheduleV1,
)


def evaluate_research_coverage(
    schedule: ResearchObservationScheduleV1,
    samples: Iterable[ResearchDecisionSampleV1],
) -> ResearchCoverageSealV1:
    """Reject missing, duplicate, extra, drifted or late arm observations.

    ``NO_INTENT``, ``NOT_CALLED`` and ``CALL_FAILED`` count as observations,
    never as trades.  This checks geometry and contract integrity only; source
    receipts, provider timing and economic outcomes need independent gates.
    """

    if type(schedule) is not ResearchObservationScheduleV1:
        raise TypeError("coverage requires ResearchObservationScheduleV1")
    if schedule.schedule_digest != canonical_sha256(schedule.identity_payload()):
        raise ValueError("research schedule digest changed after preregistration")

    windows = {window.sample_id: window for window in schedule.windows}
    observed: dict[tuple[str, str], ResearchDecisionSampleV1] = {}
    snapshot_by_sample: dict[str, str] = {}
    strategy_outcome_by_sample: dict[str, str] = {}
    for sample in samples:
        if type(sample) is not ResearchDecisionSampleV1:
            raise TypeError("coverage accepts only ResearchDecisionSampleV1 observations")
        if sample.sample_record_id != canonical_sha256(sample.identity_payload()):
            raise ValueError("research observation ID changed after construction")
        if sample.campaign_id != schedule.campaign_id or sample.arm_id not in RESEARCH_ARMS:
            raise ValueError("research observation is outside the frozen campaign or arm set")
        window = windows.get(sample.sample_id)
        if window is None:
            raise ValueError("post-hoc research observation is absent from the frozen schedule")
        for field in (
            "symbol",
            "timeframe",
            "market_as_of_ts_ms",
            "paired_at_ts_ms",
            "sample_deadline_ts_ms",
        ):
            if getattr(sample, field) != getattr(window, field):
                raise ValueError(f"research observation {field} differs from the frozen window")
        if (
            window.market_snapshot_sha256 is not None
            and sample.market_snapshot_sha256 != window.market_snapshot_sha256
        ):
            raise ValueError("research observation market snapshot differs from the frozen window")
        if (
            sample.strategy_id != schedule.strategy_id
            or sample.strategy_revision != schedule.strategy_revision
        ):
            raise ValueError("research observation uses a different strategy identity")
        if sample.arm_id == "strategy-only" and sample.llm_outcome != "NOT_CALLED":
            raise ValueError("strategy-only control arm cannot contain an LLM result")
        key = (sample.arm_id, sample.sample_id)
        if key in observed:
            raise ValueError("duplicate research arm observation for a frozen sample")
        observed[key] = sample
        prior_snapshot = snapshot_by_sample.setdefault(sample.sample_id, sample.market_snapshot_sha256)
        if sample.market_snapshot_sha256 != prior_snapshot:
            raise ValueError("matched arms disagree on their market snapshot")
        prior_outcome = strategy_outcome_by_sample.setdefault(sample.sample_id, sample.strategy_outcome)
        if sample.strategy_outcome != prior_outcome:
            raise ValueError("matched arms disagree on the baseline strategy outcome")

    expected = [(arm, window.sample_id) for window in schedule.windows for arm in RESEARCH_ARMS]
    missing = [key for key in expected if key not in observed]
    if missing:
        raise ValueError(f"research coverage is missing {len(missing)} scheduled arm observations")
    if len(observed) != len(expected):
        raise ValueError("research coverage contains post-hoc or duplicate observations")
    if schedule.schedule_digest is None:
        raise ValueError("research schedule lacks its canonical digest")
    return ResearchCoverageSealV1(
        campaign_id=schedule.campaign_id,
        schedule_digest=schedule.schedule_digest,
        expected_result_count=len(expected),
        result_ids_sha256=canonical_sha256(
            {"sample_record_ids": [observed[key].sample_record_id for key in expected]}
        ),
    )

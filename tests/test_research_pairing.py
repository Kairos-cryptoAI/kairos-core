"""The research pair is a comparison record, never a trade authorization."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kairos_core import (
    EvidenceReferenceV1,
    ExitPlanV1,
    LLMCallFailureV1,
    LLMProposalAction,
    LLMProposalCompletionReceiptV1,
    LLMProposalModelProvenanceV1,
    LLMTradeProposalV1,
    ResearchDecisionSampleV1,
    RiskTradeDecisionV1,
    Side,
    StrategyIntentV1,
    StrategyProvenanceV1,
)
from kairos_core.research_pairing import (
    ScheduledResearchSampleV1,
    StrategyEvaluationEvidenceV1,
    build_research_decision_sample,
)

T0 = 1_800_000_000_000
SNAPSHOT = "a" * 64
EVALUATION = "b" * 64


def _sample(**changes: object) -> ScheduledResearchSampleV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": SNAPSHOT,
        "strategy_id": "adaptive-strategy",
        "strategy_revision": "revision-1",
        "paired_at_ts_ms": T0 + 5_000,
        "sample_deadline_ts_ms": T0 + 30_000,
    }
    values.update(changes)
    return ScheduledResearchSampleV1(**values)  # type: ignore[arg-type]


def _intent(**changes: object) -> StrategyIntentV1:
    values: dict[str, object] = {
        "source": "strategy-engine",
        "strategy_id": "adaptive-strategy",
        "strategy_revision": "revision-1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "decision_ts_ms": T0,
        "entry_eligible_ts_ms": T0 + 60_000,
        "entry_expires_ts_ms": T0 + 120_000,
        "reference_price": 100.0,
        "signal_strength": 0.7,
        "gross_reward_bps": 500.0,
        "exit_plan": ExitPlanV1(stop_price=95.0, target_price=105.0, max_holding_ms=180_000),
        "provenance": StrategyProvenanceV1(
            strategy_code_sha256="c" * 64,
            config_sha256="d" * 64,
            input_window_sha256="e" * 64,
            features_sha256="f" * 64,
            input_bar_sha256s=(SNAPSHOT,),
        ),
    }
    values.update(changes)
    return StrategyIntentV1(**values)


def _evaluation(*, intent: StrategyIntentV1 | None = None, **changes: object) -> StrategyEvaluationEvidenceV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "strategy_id": "adaptive-strategy",
        "strategy_revision": "revision-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "evidence_as_of_ts_ms": T0,
        "market_snapshot_sha256": SNAPSHOT,
        "evaluation_sha256": EVALUATION,
        "intent_id": intent.intent_id if intent is not None else None,
    }
    values.update(changes)
    return StrategyEvaluationEvidenceV1(**values)  # type: ignore[arg-type]


def _proposal(**changes: object) -> LLMTradeProposalV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "expires_at_ts_ms": T0 + 20_000,
        "market_snapshot_sha256": SNAPSHOT,
        "action": LLMProposalAction.SHORT_BIAS,
        "rationale": "Risk of a sharp downside move in the supplied snapshot.",
        "evidence": (
            EvidenceReferenceV1(
                kind="closed_bar",
                reference="BTCUSDT:1m:1800000000000",
                content_sha256="1" * 64,
                observed_at_ms=T0,
            ),
        ),
        "model_provenance": LLMProposalModelProvenanceV1(
            provider="local",
            requested_model="fixture",
            resolved_model="fixture-v1",
            request_id="request-1",
            prompt_sha256="2" * 64,
            response_sha256="3" * 64,
            budget_reservation_id="fixture:reservation-1",
            latency_ms=1,
            cost_usd=0,
        ),
    }
    values.update(changes)
    return LLMTradeProposalV1(**values)


def _failure(**changes: object) -> LLMCallFailureV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": SNAPSHOT,
        "sample_deadline_ts_ms": T0 + 30_000,
        "attempt_id": "attempt-1",
        "provider": "local",
        "requested_model": "fixture",
        "prompt_sha256": "2" * 64,
        "budget_reservation_id": "fixture:reservation-1",
        "attempt_started_at_ts_ms": T0 + 100,
        "failure_observed_at_ts_ms": T0 + 1_000,
        "failure_class": "TIMEOUT",
    }
    values.update(changes)
    return LLMCallFailureV1(**values)


def _completion(proposal: LLMTradeProposalV1, **changes: object) -> LLMProposalCompletionReceiptV1:
    values: dict[str, object] = {
        "campaign_id": "adaptive-research-v1",
        "arm_id": "matched-proposals",
        "sample_id": "sample-001",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "market_as_of_ts_ms": T0,
        "market_snapshot_sha256": SNAPSHOT,
        "sample_deadline_ts_ms": T0 + 30_000,
        "attempt_id": "attempt-1",
        "proposal_id": proposal.proposal_id,
        "model_provenance": proposal.model_provenance,
        "attempt_started_at_ts_ms": T0 + 100,
        "response_observed_at_ts_ms": T0 + 1_000,
    }
    values.update(changes)
    return LLMProposalCompletionReceiptV1(**values)


def test_no_intent_and_independent_llm_direction_are_both_recorded() -> None:
    proposal = _proposal()
    completion = _completion(proposal)
    paired = build_research_decision_sample(
        _sample(),
        strategy_evaluation=_evaluation(),
        llm_proposal=proposal,
        llm_completion=completion,
        llm_was_called=True,
    )

    assert type(paired) is ResearchDecisionSampleV1
    assert not isinstance(paired, RiskTradeDecisionV1)
    assert paired.authority == "SIM_RESEARCH_ONLY"
    assert paired.strategy_outcome == "NO_INTENT"
    assert paired.strategy_intent_id is None
    assert paired.strategy_evaluation_sha256 == EVALUATION
    assert paired.llm_outcome == "SHORT_BIAS"
    assert paired.llm_proposal_id == proposal.proposal_id
    assert paired.llm_completion_receipt_id == completion.completion_receipt_id
    assert paired.llm_completion_started_at_ts_ms == T0 + 100
    assert paired.llm_completion_observed_at_ts_ms == T0 + 1_000
    assert paired.llm_proposal_expires_at_ts_ms == T0 + 20_000
    assert ResearchDecisionSampleV1.from_json(paired.to_json()) == paired


def test_opposite_direction_is_preserved_not_resolved_into_an_order() -> None:
    intent = _intent()
    proposal = _proposal()
    completion = _completion(proposal)
    paired = build_research_decision_sample(
        _sample(),
        strategy_evaluation=_evaluation(intent=intent),
        strategy_intent=intent,
        llm_proposal=proposal,
        llm_completion=completion,
        llm_was_called=True,
    )

    assert paired.strategy_outcome == "LONG"
    assert paired.strategy_intent_id == intent.intent_id
    assert paired.llm_outcome == "SHORT_BIAS"
    assert paired.llm_proposal_id == proposal.proposal_id
    assert paired.strategy_intent_expires_at_ts_ms == T0 + 120_000
    assert paired.sample_record_id
    assert not hasattr(paired, "order_id")
    assert not hasattr(paired, "risk_decision")


def test_same_scheduled_inputs_replay_to_the_same_canonical_record() -> None:
    sample = _sample()
    evaluation = _evaluation()
    proposal = _proposal()
    completion = _completion(proposal)
    first = build_research_decision_sample(
        sample,
        strategy_evaluation=evaluation,
        llm_proposal=proposal,
        llm_completion=completion,
        llm_was_called=True,
    )
    replayed = build_research_decision_sample(
        sample,
        strategy_evaluation=evaluation,
        llm_proposal=proposal,
        llm_completion=completion,
        llm_was_called=True,
    )
    later = build_research_decision_sample(
        replace(sample, paired_at_ts_ms=T0 + 6_000),
        strategy_evaluation=evaluation,
        llm_proposal=proposal,
        llm_completion=completion,
        llm_was_called=True,
    )

    assert first.sample_record_id == replayed.sample_record_id
    assert first.canonical_sample_bytes() == replayed.canonical_sample_bytes()
    assert first.sample_record_id != later.sample_record_id


def test_absence_is_not_misreported_as_a_completed_evaluation_or_call() -> None:
    absent = build_research_decision_sample(_sample())
    assert absent.strategy_outcome == "NOT_EVALUATED"
    assert absent.llm_outcome == "NOT_CALLED"
    assert absent.strategy_evaluation_sha256 is None
    assert absent.llm_proposal_id is None

    with pytest.raises(ValueError, match="evaluation receipt"):
        build_research_decision_sample(_sample(), strategy_intent=_intent())
    with pytest.raises(ValueError, match="requires a completed proposal or failure"):
        build_research_decision_sample(_sample(), llm_was_called=True)
    with pytest.raises(ValueError, match="llm_was_called is false"):
        build_research_decision_sample(_sample(), llm_proposal=_proposal())
    proposal = _proposal()
    with pytest.raises(ValueError, match="requires a completion receipt"):
        build_research_decision_sample(_sample(), llm_proposal=proposal, llm_was_called=True)
    with pytest.raises(ValueError, match="requires a matching proposal"):
        build_research_decision_sample(
            _sample(),
            llm_completion=_completion(proposal),
            llm_was_called=True,
        )


@pytest.mark.parametrize("action", [LLMProposalAction.NO_PROPOSAL, LLMProposalAction.DEFER])
def test_explicit_non_directional_llm_outcomes_are_not_equated_with_not_called(
    action: LLMProposalAction,
) -> None:
    proposal = _proposal(action=action, expires_at_ts_ms=T0, evidence=())
    paired = build_research_decision_sample(
        _sample(),
        llm_proposal=proposal,
        llm_completion=_completion(proposal),
        llm_was_called=True,
    )
    assert paired.llm_outcome == action.value
    assert paired.llm_proposal_id == proposal.proposal_id
    assert paired.llm_proposal_expires_at_ts_ms is None


def test_no_intent_can_be_paired_with_a_cited_directionless_move_alert() -> None:
    alert = _proposal(action=LLMProposalAction.VOLATILITY_ALERT)
    paired = build_research_decision_sample(
        _sample(),
        strategy_evaluation=_evaluation(),
        llm_proposal=alert,
        llm_completion=_completion(alert),
        llm_was_called=True,
    )

    assert paired.strategy_outcome == "NO_INTENT"
    assert paired.llm_outcome == "VOLATILITY_ALERT"
    assert paired.llm_proposal_id == alert.proposal_id
    assert paired.llm_proposal_expires_at_ts_ms == T0 + 20_000
    assert not hasattr(paired, "order_id")


def test_failed_call_is_not_reported_as_no_proposal_or_not_called() -> None:
    failure = _failure()
    paired = build_research_decision_sample(
        _sample(),
        strategy_evaluation=_evaluation(),
        llm_failure=failure,
        llm_was_called=True,
    )

    assert paired.strategy_outcome == "NO_INTENT"
    assert paired.llm_outcome == "CALL_FAILED"
    assert paired.llm_failure_receipt_id == failure.failure_receipt_id
    assert paired.llm_failure_class == "TIMEOUT"
    assert paired.llm_failure_observed_at_ts_ms == T0 + 1_000
    assert paired.llm_proposal_id is None
    assert paired.llm_proposal_expires_at_ts_ms is None
    assert ResearchDecisionSampleV1.from_json(paired.to_json()) == paired


def test_failure_must_be_matching_and_observed_before_causal_pairing() -> None:
    for change in (
        {"campaign_id": "other-campaign"},
        {"market_snapshot_sha256": "9" * 64},
        {"sample_deadline_ts_ms": T0 + 31_000},
    ):
        with pytest.raises(ValueError, match="does not match"):
            build_research_decision_sample(
                _sample(),
                llm_failure=_failure(**change),
                llm_was_called=True,
            )

    late = _failure(failure_observed_at_ts_ms=T0 + 31_000)
    assert late.is_late
    with pytest.raises(ValueError, match="observed after the causal pairing clock"):
        build_research_decision_sample(
            _sample(),
            llm_failure=late,
            llm_was_called=True,
        )
    with pytest.raises(ValueError, match="observed after the causal pairing clock"):
        build_research_decision_sample(
            _sample(),
            llm_failure=_failure(failure_observed_at_ts_ms=T0 + 5_001),
            llm_was_called=True,
        )
    with pytest.raises(ValueError, match="both complete a proposal and fail"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=_proposal(),
            llm_failure=_failure(),
            llm_was_called=True,
        )
    with pytest.raises(ValueError, match="llm_was_called is false"):
        build_research_decision_sample(_sample(), llm_failure=_failure())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("campaign_id", "other-campaign"),
        ("arm_id", "other-arm"),
        ("sample_id", "other-sample"),
        ("symbol", "ETHUSDT"),
        ("timeframe", "5m"),
        ("market_as_of_ts_ms", T0 + 1),
        ("market_snapshot_sha256", "9" * 64),
        ("sample_deadline_ts_ms", T0 + 31_000),
    ],
)
def test_completion_must_match_entire_scheduled_scope(field: str, value: object) -> None:
    proposal = _proposal()
    with pytest.raises(ValueError, match=f"LLM completion {field} does not match"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=proposal,
            llm_completion=_completion(proposal, **{field: value}),
            llm_was_called=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "other-provider"),
        ("requested_model", "other-model"),
        ("resolved_model", "other-model-v2"),
        ("system_fingerprint", "fingerprint-2"),
        ("reasoning_effort", "high"),
        ("request_id", "other-request"),
        ("prompt_sha256", "8" * 64),
        ("response_sha256", "9" * 64),
        ("budget_reservation_id", "other:reservation"),
        ("latency_ms", 2),
        ("cost_usd", 1.0),
    ],
)
def test_completion_must_match_all_gateway_provenance(field: str, value: object) -> None:
    proposal = _proposal()
    provenance = LLMProposalModelProvenanceV1(
        **(proposal.model_provenance.model_dump() | {field: value}),
    )
    with pytest.raises(ValueError, match="gateway provenance does not match"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=proposal,
            llm_completion=_completion(proposal, model_provenance=provenance),
            llm_was_called=True,
        )


def test_completion_must_link_proposal_and_arrive_before_pairing() -> None:
    proposal = _proposal()
    with pytest.raises(ValueError, match="proposal ID does not match"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=proposal,
            llm_completion=_completion(proposal, proposal_id="9" * 64),
            llm_was_called=True,
        )

    after_pair = _completion(proposal, response_observed_at_ts_ms=T0 + 5_001)
    after_deadline = _completion(proposal, response_observed_at_ts_ms=T0 + 31_000)
    assert after_deadline.is_late
    for completion in (after_pair, after_deadline):
        with pytest.raises(ValueError, match="observed after the causal pairing clock"):
            build_research_decision_sample(
                _sample(),
                llm_proposal=proposal,
                llm_completion=completion,
                llm_was_called=True,
            )

    on_time = build_research_decision_sample(
        _sample(),
        llm_proposal=proposal,
        llm_completion=_completion(proposal),
        llm_was_called=True,
    )
    later_observation = build_research_decision_sample(
        _sample(),
        llm_proposal=proposal,
        llm_completion=_completion(proposal, response_observed_at_ts_ms=T0 + 2_000),
        llm_was_called=True,
    )
    assert on_time.sample_record_id != later_observation.sample_record_id


def test_pairing_rejects_noncanonical_copied_proposal_or_completion() -> None:
    proposal = _proposal()
    completion = _completion(proposal)

    with pytest.raises(ValueError, match="proposal ID does not match its canonical payload"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=proposal.model_copy(update={"rationale": "changed"}),
            llm_completion=completion,
            llm_was_called=True,
        )
    with pytest.raises(ValueError, match="completion receipt ID does not match its canonical payload"):
        build_research_decision_sample(
            _sample(),
            llm_proposal=proposal,
            llm_completion=completion.model_copy(update={"attempt_id": "different-attempt"}),
            llm_was_called=True,
        )


def test_pairing_rejects_noncanonical_copied_strategy_intent_or_failure() -> None:
    intent = _intent()
    with pytest.raises(ValueError, match="strategy intent ID does not match its canonical payload"):
        build_research_decision_sample(
            _sample(),
            strategy_evaluation=_evaluation(intent=intent),
            strategy_intent=intent.model_copy(update={"side": Side.SHORT}),
        )

    failure = _failure()
    with pytest.raises(ValueError, match="LLM failure receipt ID does not match its canonical payload"):
        build_research_decision_sample(
            _sample(),
            llm_failure=failure.model_copy(update={"failure_class": "PROVIDER_ERROR"}),
            llm_was_called=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("campaign_id", "other-campaign"),
        ("arm_id", "other-arm"),
        ("sample_id", "other-sample"),
        ("symbol", "ETHUSDT"),
        ("timeframe", "5m"),
        ("market_as_of_ts_ms", T0 - 60_000),
        ("market_as_of_ts_ms", T0 + 60_000),
        ("market_snapshot_sha256", "9" * 64),
    ],
)
def test_llm_cross_sample_or_stale_provenance_is_rejected(field: str, value: object) -> None:
    changes = {field: value}
    if field == "market_as_of_ts_ms":
        changes["evidence"] = (
            EvidenceReferenceV1(
                kind="closed_bar",
                reference=f"BTCUSDT:1m:{value}",
                content_sha256="1" * 64,
                observed_at_ms=value,
            ),
        )
        if value > T0:
            changes["expires_at_ts_ms"] = value + 20_000
    with pytest.raises(ValueError, match="does not match"):
        proposal = _proposal(**changes)
        build_research_decision_sample(
            _sample(), llm_proposal=proposal, llm_completion=_completion(proposal), llm_was_called=True
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("campaign_id", "other-campaign"),
        ("arm_id", "other-arm"),
        ("sample_id", "other-sample"),
        ("strategy_id", "other-strategy"),
        ("strategy_revision", "other-revision"),
        ("symbol", "ETHUSDT"),
        ("timeframe", "5m"),
        ("evidence_as_of_ts_ms", T0 - 60_000),
        ("evidence_as_of_ts_ms", T0 + 60_000),
        ("market_snapshot_sha256", "9" * 64),
    ],
)
def test_strategy_evaluation_wrong_scope_or_snapshot_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="does not match|stale or future"):
        build_research_decision_sample(_sample(), strategy_evaluation=_evaluation(**{field: value}))


def test_intent_must_match_evaluation_and_decision_window() -> None:
    intent = _intent()
    with pytest.raises(ValueError, match="intent ID"):
        build_research_decision_sample(
            _sample(), strategy_evaluation=_evaluation(intent_id="9" * 64), strategy_intent=intent
        )
    with pytest.raises(ValueError, match="refers to an intent"):
        build_research_decision_sample(_sample(), strategy_evaluation=_evaluation(intent_id="9" * 64))
    with pytest.raises(ValueError, match="timestamp is stale or future"):
        build_research_decision_sample(
            _sample(),
            strategy_evaluation=_evaluation(intent=_intent(decision_ts_ms=T0 - 60_000)),
            strategy_intent=_intent(decision_ts_ms=T0 - 60_000),
        )
    with pytest.raises(ValueError, match="strategy intent symbol"):
        other = _intent(symbol="ETHUSDT")
        build_research_decision_sample(
            _sample(),
            strategy_evaluation=_evaluation(intent=other),
            strategy_intent=other,
        )


def test_intent_must_use_the_scheduled_decision_bar() -> None:
    other_bar = _intent(
        provenance=StrategyProvenanceV1(
            strategy_code_sha256="c" * 64,
            config_sha256="d" * 64,
            input_window_sha256="e" * 64,
            features_sha256="f" * 64,
            input_bar_sha256s=("9" * 64,),
        )
    )
    with pytest.raises(ValueError, match="decision bar does not match"):
        build_research_decision_sample(
            _sample(),
            strategy_evaluation=_evaluation(intent=other_bar),
            strategy_intent=other_bar,
        )


def test_expired_directional_proposal_and_intent_fail_closed() -> None:
    with pytest.raises(ValueError, match="expired"):
        proposal = _proposal()
        build_research_decision_sample(
            _sample(paired_at_ts_ms=T0 + 20_000),
            llm_proposal=proposal,
            llm_completion=_completion(proposal),
            llm_was_called=True,
        )
    intent = _intent()
    with pytest.raises(ValueError, match="expired"):
        build_research_decision_sample(
            _sample(paired_at_ts_ms=T0 + 120_000, sample_deadline_ts_ms=T0 + 180_000),
            strategy_evaluation=_evaluation(intent=intent),
            strategy_intent=intent,
        )


def test_llm_response_cannot_arrive_before_its_measured_latency() -> None:
    slow = _proposal(
        model_provenance=LLMProposalModelProvenanceV1(
            provider="local",
            requested_model="fixture",
            resolved_model="fixture-v1",
            request_id="request-1",
            prompt_sha256="2" * 64,
            response_sha256="3" * 64,
            budget_reservation_id="fixture:reservation-1",
            latency_ms=6_000,
            cost_usd=0,
        )
    )
    late_completion = _completion(slow, response_observed_at_ts_ms=T0 + 6_100)
    with pytest.raises(ValueError, match="observed after the causal pairing clock"):
        build_research_decision_sample(
            _sample(paired_at_ts_ms=T0 + 5_000),
            llm_proposal=slow,
            llm_completion=late_completion,
            llm_was_called=True,
        )


def test_schedule_rejects_future_pairing_and_expired_snapshot() -> None:
    with pytest.raises(ValueError, match="scheduled sample window"):
        _sample(paired_at_ts_ms=T0 - 1)
    with pytest.raises(ValueError, match="scheduled sample window"):
        _sample(paired_at_ts_ms=T0 + 30_000)
    with pytest.raises(ValueError, match="normalized uppercase"):
        _sample(symbol="btcusdt")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _sample(market_snapshot_sha256="A" * 64)
    with pytest.raises(ValueError, match="integer milliseconds"):
        _sample(paired_at_ts_ms=True)


def test_evaluation_evidence_is_immutable_and_scoped() -> None:
    evidence = _evaluation()
    with pytest.raises(AttributeError):
        evidence.evaluation_sha256 = "f" * 64  # type: ignore[misc]
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(evidence, evaluation_sha256="x")

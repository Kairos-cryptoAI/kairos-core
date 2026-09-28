"""Pair contemporaneous strategy and LLM observations for research only.

This module cannot create an intent, risk decision, or order.  In particular,
an LLM hypothesis remains visible when a strategy was evaluated and emitted no
intent, but it is never promoted to an executable strategy candidate here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from .contracts.base import canonical_sha256
from .contracts.llm_call_failure import LLMCallFailureClass, LLMCallFailureV1
from .contracts.llm_proposal import LLMTradeProposalV1
from .contracts.llm_proposal_completion import LLMProposalCompletionReceiptV1
from .contracts.research_decision import ResearchDecisionSampleV1
from .contracts.strategy import StrategyIntentV1

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
StrategyOutcome = Literal["LONG", "SHORT", "NO_INTENT", "NOT_EVALUATED"]
LLMOutcome = Literal[
    "LONG_BIAS", "SHORT_BIAS", "VOLATILITY_ALERT", "NO_PROPOSAL", "DEFER", "CALL_FAILED", "NOT_CALLED"
]
LLMObservation = tuple[
    LLMOutcome,
    str | None,
    int | None,
    str | None,
    int | None,
    str | None,
    int | None,
    int | None,
    str | None,
    LLMCallFailureClass | None,
    int | None,
    int | None,
]


def _identifier(value: str, name: str, *, max_length: int = 128) -> None:
    if not isinstance(value, str) or len(value) > max_length or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a normalized identifier")


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _nonnegative_ms(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be non-negative integer milliseconds")


@dataclass(frozen=True, slots=True)
class ScheduledResearchSampleV1:
    """Trusted, preassigned observation key and replay-clock decision window."""

    campaign_id: str
    arm_id: str
    sample_id: str
    symbol: str
    timeframe: str
    market_as_of_ts_ms: int
    market_snapshot_sha256: str
    strategy_id: str
    strategy_revision: str
    paired_at_ts_ms: int
    sample_deadline_ts_ms: int

    def __post_init__(self) -> None:
        for name in ("campaign_id", "arm_id", "sample_id", "timeframe", "strategy_id", "strategy_revision"):
            _identifier(getattr(self, name), name)
        if (
            not isinstance(self.symbol, str)
            or len(self.symbol) > 32
            or _SYMBOL.fullmatch(self.symbol) is None
        ):
            raise ValueError("symbol must be normalized uppercase")
        _sha256(self.market_snapshot_sha256, "market_snapshot_sha256")
        for name in ("market_as_of_ts_ms", "paired_at_ts_ms", "sample_deadline_ts_ms"):
            _nonnegative_ms(getattr(self, name), name)
        if not self.market_as_of_ts_ms <= self.paired_at_ts_ms < self.sample_deadline_ts_ms:
            raise ValueError("pairing must occur within the scheduled sample window")


@dataclass(frozen=True, slots=True)
class StrategyEvaluationEvidenceV1:
    """External evaluator's attestation, including a no-intent evaluation.

    ``evaluation_sha256`` identifies an independently stored deterministic
    evaluation receipt.  Constructing this object does not itself prove that
    an evaluator ran; consumers must validate the referenced receipt.
    """

    campaign_id: str
    arm_id: str
    sample_id: str
    strategy_id: str
    strategy_revision: str
    symbol: str
    timeframe: str
    evidence_as_of_ts_ms: int
    market_snapshot_sha256: str
    evaluation_sha256: str
    intent_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("campaign_id", "arm_id", "sample_id", "strategy_id", "strategy_revision", "timeframe"):
            _identifier(getattr(self, name), name)
        if (
            not isinstance(self.symbol, str)
            or len(self.symbol) > 32
            or _SYMBOL.fullmatch(self.symbol) is None
        ):
            raise ValueError("symbol must be normalized uppercase")
        _nonnegative_ms(self.evidence_as_of_ts_ms, "evidence_as_of_ts_ms")
        _sha256(self.market_snapshot_sha256, "market_snapshot_sha256")
        _sha256(self.evaluation_sha256, "evaluation_sha256")
        if self.intent_id is not None:
            _sha256(self.intent_id, "intent_id")


def _check_strategy(
    sample: ScheduledResearchSampleV1,
    evidence: StrategyEvaluationEvidenceV1 | None,
    intent: StrategyIntentV1 | None,
) -> tuple[StrategyOutcome, str | None, str | None, int | None, str | None, int | None]:
    if evidence is None:
        if intent is not None:
            raise ValueError("a strategy intent requires a matching evaluation receipt")
        return "NOT_EVALUATED", None, None, None, None, None

    for name in (
        "campaign_id",
        "arm_id",
        "sample_id",
        "strategy_id",
        "strategy_revision",
        "symbol",
        "timeframe",
    ):
        if getattr(evidence, name) != getattr(sample, name):
            raise ValueError(f"strategy evaluation {name} does not match the scheduled sample")
    if evidence.evidence_as_of_ts_ms != sample.market_as_of_ts_ms:
        raise ValueError("strategy evaluation is stale or future relative to the scheduled sample")
    if evidence.market_snapshot_sha256 != sample.market_snapshot_sha256:
        raise ValueError("strategy evaluation snapshot does not match the scheduled sample")

    if intent is None:
        if evidence.intent_id is not None:
            raise ValueError("no-intent evaluation receipt refers to an intent")
        return (
            "NO_INTENT",
            None,
            evidence.evaluation_sha256,
            evidence.evidence_as_of_ts_ms,
            evidence.market_snapshot_sha256,
            None,
        )

    if intent.intent_id != canonical_sha256(intent.identity_payload()):
        raise ValueError("strategy intent ID does not match its canonical payload")
    if intent.intent_id != evidence.intent_id:
        raise ValueError("strategy intent ID does not match the evaluation receipt")
    for name in ("strategy_id", "strategy_revision", "symbol", "timeframe"):
        if getattr(intent, name) != getattr(sample, name):
            raise ValueError(f"strategy intent {name} does not match the scheduled sample")
    if intent.decision_ts_ms != sample.market_as_of_ts_ms:
        raise ValueError("strategy intent decision timestamp is stale or future")
    if intent.provenance.input_bar_sha256s[-1] != sample.market_snapshot_sha256:
        raise ValueError("strategy intent decision bar does not match the scheduled snapshot")
    if sample.paired_at_ts_ms >= intent.entry_expires_ts_ms:
        raise ValueError("strategy intent expired before the pair was formed")
    return (
        cast(StrategyOutcome, intent.side.value),
        intent.intent_id,
        evidence.evaluation_sha256,
        evidence.evidence_as_of_ts_ms,
        evidence.market_snapshot_sha256,
        intent.entry_expires_ts_ms,
    )


def _check_llm(
    sample: ScheduledResearchSampleV1,
    proposal: LLMTradeProposalV1 | None,
    completion: LLMProposalCompletionReceiptV1 | None,
    failure: LLMCallFailureV1 | None,
    *,
    llm_was_called: bool,
) -> LLMObservation:
    if not isinstance(llm_was_called, bool):
        raise ValueError("llm_was_called must be a boolean")
    if proposal is not None and failure is not None:
        raise ValueError("an LLM attempt cannot both complete a proposal and fail")
    if completion is not None and proposal is None:
        raise ValueError("an LLM completion receipt requires a matching proposal")
    if completion is not None and failure is not None:
        raise ValueError("an LLM attempt cannot have both completion and failure receipts")
    if failure is not None:
        if not llm_was_called:
            raise ValueError("an LLM failure cannot exist when llm_was_called is false")
        if failure.failure_receipt_id != canonical_sha256(failure.identity_payload()):
            raise ValueError("LLM failure receipt ID does not match its canonical payload")
        for name in (
            "campaign_id",
            "arm_id",
            "sample_id",
            "symbol",
            "timeframe",
            "market_as_of_ts_ms",
            "market_snapshot_sha256",
            "sample_deadline_ts_ms",
        ):
            if getattr(failure, name) != getattr(sample, name):
                raise ValueError(f"LLM failure {name} does not match the scheduled sample")
        if failure.failure_observed_at_ts_ms > sample.paired_at_ts_ms:
            raise ValueError("LLM failure was observed after the causal pairing clock")
        if failure.failure_receipt_id is None:
            raise ValueError("LLM failure receipt is missing its canonical ID")
        return (
            "CALL_FAILED",
            None,
            failure.market_as_of_ts_ms,
            failure.market_snapshot_sha256,
            None,
            None,
            None,
            None,
            failure.failure_receipt_id,
            failure.failure_class,
            failure.attempt_started_at_ts_ms,
            failure.failure_observed_at_ts_ms,
        )
    if proposal is None:
        if llm_was_called:
            raise ValueError("an attempted LLM call requires a completed proposal or failure receipt")
        return "NOT_CALLED", None, None, None, None, None, None, None, None, None, None, None
    if not llm_was_called:
        raise ValueError("an LLM proposal cannot exist when llm_was_called is false")
    if completion is None:
        raise ValueError("a completed LLM proposal requires a completion receipt")
    if proposal.proposal_id != canonical_sha256(proposal.identity_payload()):
        raise ValueError("LLM proposal ID does not match its canonical payload")
    if completion.completion_receipt_id != canonical_sha256(completion.identity_payload()):
        raise ValueError("LLM completion receipt ID does not match its canonical payload")
    for name in ("campaign_id", "arm_id", "sample_id", "symbol", "timeframe", "market_as_of_ts_ms"):
        if getattr(proposal, name) != getattr(sample, name):
            raise ValueError(f"LLM proposal {name} does not match the scheduled sample")
    if proposal.market_snapshot_sha256 != sample.market_snapshot_sha256:
        raise ValueError("LLM proposal snapshot does not match the scheduled sample")
    for name in (
        "campaign_id",
        "arm_id",
        "sample_id",
        "symbol",
        "timeframe",
        "market_as_of_ts_ms",
        "market_snapshot_sha256",
        "sample_deadline_ts_ms",
    ):
        if getattr(completion, name) != getattr(sample, name):
            raise ValueError(f"LLM completion {name} does not match the scheduled sample")
    if completion.proposal_id != proposal.proposal_id:
        raise ValueError("LLM completion proposal ID does not match the linked proposal")
    if completion.model_provenance != proposal.model_provenance:
        raise ValueError("LLM completion gateway provenance does not match the linked proposal")
    if completion.response_observed_at_ts_ms > sample.paired_at_ts_ms:
        raise ValueError("LLM completion was observed after the causal pairing clock")
    candidate = proposal.action.value in ("LONG_BIAS", "SHORT_BIAS", "VOLATILITY_ALERT")
    if candidate and sample.paired_at_ts_ms >= proposal.expires_at_ts_ms:
        raise ValueError("advisory LLM hypothesis expired before the pair was formed")
    return (
        cast(LLMOutcome, proposal.action.value),
        proposal.proposal_id,
        proposal.market_as_of_ts_ms,
        proposal.market_snapshot_sha256,
        proposal.expires_at_ts_ms if candidate else None,
        completion.completion_receipt_id,
        completion.attempt_started_at_ts_ms,
        completion.response_observed_at_ts_ms,
        None,
        None,
        None,
        None,
    )


def build_research_decision_sample(
    sample: ScheduledResearchSampleV1,
    *,
    strategy_evaluation: StrategyEvaluationEvidenceV1 | None = None,
    strategy_intent: StrategyIntentV1 | None = None,
    llm_proposal: LLMTradeProposalV1 | None = None,
    llm_completion: LLMProposalCompletionReceiptV1 | None = None,
    llm_failure: LLMCallFailureV1 | None = None,
    llm_was_called: bool = False,
) -> ResearchDecisionSampleV1:
    """Record both observations without deriving an executable action.

    Missing evaluation is not the same as a no-intent evaluation, and missing
    proposal is not the same as an explicit ``NO_PROPOSAL`` result.
    """

    if not isinstance(sample, ScheduledResearchSampleV1):
        raise TypeError("sample must be a ScheduledResearchSampleV1")
    if strategy_evaluation is not None and not isinstance(strategy_evaluation, StrategyEvaluationEvidenceV1):
        raise TypeError("strategy_evaluation must be a StrategyEvaluationEvidenceV1")
    if strategy_intent is not None and not isinstance(strategy_intent, StrategyIntentV1):
        raise TypeError("strategy_intent must be a StrategyIntentV1")
    if llm_proposal is not None and not isinstance(llm_proposal, LLMTradeProposalV1):
        raise TypeError("llm_proposal must be a LLMTradeProposalV1")
    if llm_completion is not None and not isinstance(llm_completion, LLMProposalCompletionReceiptV1):
        raise TypeError("llm_completion must be a LLMProposalCompletionReceiptV1")
    if llm_failure is not None and not isinstance(llm_failure, LLMCallFailureV1):
        raise TypeError("llm_failure must be a LLMCallFailureV1")

    (
        strategy_outcome,
        strategy_intent_id,
        strategy_evaluation_sha256,
        strategy_evidence_as_of_ts_ms,
        strategy_market_snapshot_sha256,
        strategy_intent_expires_at_ts_ms,
    ) = _check_strategy(sample, strategy_evaluation, strategy_intent)
    (
        llm_outcome,
        llm_proposal_id,
        llm_evidence_as_of_ts_ms,
        llm_market_snapshot_sha256,
        llm_proposal_expires_at_ts_ms,
        llm_completion_receipt_id,
        llm_completion_started_at_ts_ms,
        llm_completion_observed_at_ts_ms,
        llm_failure_receipt_id,
        llm_failure_class,
        llm_failure_started_at_ts_ms,
        llm_failure_observed_at_ts_ms,
    ) = _check_llm(sample, llm_proposal, llm_completion, llm_failure, llm_was_called=llm_was_called)

    return ResearchDecisionSampleV1(
        campaign_id=sample.campaign_id,
        arm_id=sample.arm_id,
        sample_id=sample.sample_id,
        symbol=sample.symbol,
        timeframe=sample.timeframe,
        market_as_of_ts_ms=sample.market_as_of_ts_ms,
        market_snapshot_sha256=sample.market_snapshot_sha256,
        paired_at_ts_ms=sample.paired_at_ts_ms,
        sample_deadline_ts_ms=sample.sample_deadline_ts_ms,
        strategy_id=sample.strategy_id,
        strategy_revision=sample.strategy_revision,
        strategy_outcome=strategy_outcome,
        strategy_intent_id=strategy_intent_id,
        strategy_evaluation_sha256=strategy_evaluation_sha256,
        strategy_evidence_as_of_ts_ms=strategy_evidence_as_of_ts_ms,
        strategy_market_snapshot_sha256=strategy_market_snapshot_sha256,
        strategy_intent_expires_at_ts_ms=strategy_intent_expires_at_ts_ms,
        llm_outcome=llm_outcome,
        llm_proposal_id=llm_proposal_id,
        llm_evidence_as_of_ts_ms=llm_evidence_as_of_ts_ms,
        llm_market_snapshot_sha256=llm_market_snapshot_sha256,
        llm_proposal_expires_at_ts_ms=llm_proposal_expires_at_ts_ms,
        llm_completion_receipt_id=llm_completion_receipt_id,
        llm_completion_started_at_ts_ms=llm_completion_started_at_ts_ms,
        llm_completion_observed_at_ts_ms=llm_completion_observed_at_ts_ms,
        llm_failure_receipt_id=llm_failure_receipt_id,
        llm_failure_class=llm_failure_class,
        llm_failure_started_at_ts_ms=llm_failure_started_at_ts_ms,
        llm_failure_observed_at_ts_ms=llm_failure_observed_at_ts_ms,
    )

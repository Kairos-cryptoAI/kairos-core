"""Wire-format guarantees for the shared enums."""

from kairos_core.enums import (
    CandidateReviewTier,
    EntryPolicy,
    EvedexProfile,
    OrderRole,
    ReasonCode,
    ReasoningEffort,
    ReviewDecision,
    RouterMode,
    SystemMode,
    TradingMode,
)
from kairos_core.topics import ALL_TOPICS, Topics


def test_reasoning_effort_values():
    assert [e.value for e in ReasoningEffort] == ["low", "medium", "high", "xhigh"]
    assert str(ReasoningEffort.HIGH) == "high"


def test_router_modes():
    assert RouterMode.ROUTE_PRO.value == "ROUTE_PRO"
    assert RouterMode.ROUTE_GPT.value == "ROUTE_GPT"


def test_system_modes():
    assert SystemMode.NORMAL.value == "NORMAL"
    assert SystemMode.TEXT_LOCAL_FILTER.value == "TEXT_LOCAL_FILTER"
    assert SystemMode.CONFLICT_SAFE.value == "CONFLICT_SAFE"
    assert SystemMode.LOCAL_QUANT_MODE.value == "LOCAL_QUANT_MODE"


def test_reason_codes_are_actionable():
    # The execution engine switches on these codes; they must stay stable.
    assert "NO_TRADE" in {c.value for c in ReasonCode}
    assert "ENTER_LONG_TREND" in {c.value for c in ReasonCode}


def test_strategy_parity_and_paper_wire_values_are_stable():
    assert [value.value for value in ReviewDecision] == ["ALLOW", "VETO", "DEFER"]
    assert [value.value for value in CandidateReviewTier] == ["NORMAL", "CONFLICT"]
    assert EntryPolicy.NEXT_BAR_MARKET.value == "NEXT_BAR_MARKET"
    assert [value.value for value in TradingMode] == ["DRY_RUN", "PAPER", "LIVE"]
    assert [value.value for value in EvedexProfile] == ["DEV", "DEMO", "PROD"]
    assert OrderRole.STOP_LOSS.value == "STOP_LOSS"
    assert OrderRole.TAKE_PROFIT.value == "TAKE_PROFIT"


def test_new_topics_are_distinct_from_the_legacy_dry_run_route():
    assert Topics.STRATEGY_INTENT != Topics.TACTICAL_COMMAND
    assert Topics.RISK_TRADE_DECISION != Topics.VALIDATED_ORDER
    assert Topics.ACCOUNT_SNAPSHOT_V2 != Topics.ACCOUNT_SNAPSHOT
    assert len(ALL_TOPICS) == len(set(ALL_TOPICS))

"""Wire-format guarantees for the shared enums."""
from kairos_core.enums import ReasoningEffort, ReasonCode, RouterMode, SystemMode


def test_reasoning_effort_values():
    assert [e.value for e in ReasoningEffort] == ["low", "medium", "high", "xhigh"]


def test_router_modes():
    assert RouterMode.ROUTE_PRO.value == "ROUTE_PRO"
    assert RouterMode.ROUTE_GPT.value == "ROUTE_GPT"


def test_system_modes():
    assert SystemMode.LOCAL_QUANT_MODE.value == "LOCAL_QUANT_MODE"


def test_reason_codes_are_actionable():
    # The execution engine switches on these codes; they must stay stable.
    assert "NO_TRADE" in {c.value for c in ReasonCode}
    assert "ENTER_LONG_TREND" in {c.value for c in ReasonCode}

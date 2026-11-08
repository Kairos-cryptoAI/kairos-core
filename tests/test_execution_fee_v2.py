"""V2 retains unknown, currency and source distinctions without changing V1."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kairos_core import (
    ExecutionFeeBundleV2,
    ExecutionFeeComponentV2,
    TradeExecutionEventV1,
    TradeExecutionEventV2,
    canonical_json_bytes,
    parse_trade_execution_event,
)
from kairos_core.topics import Topics
from tests.test_paper_contracts import T0, TRADE_ID, _event


def _v2(**overrides):
    original = _event().model_dump(mode="python")
    for key in ("contract_version", "event_id", "message_id", "fee_usd"):
        original.pop(key)
    original["fee"] = ExecutionFeeBundleV2(scope_kind="TRADE", scope_reference=TRADE_ID, coverage="UNKNOWN")
    original.update(overrides)
    return TradeExecutionEventV2(**original)


def _component(**overrides):
    values = {
        "component_id": "fee-1",
        "fill_id": "fill-1",
        "asset": "USDT",
        "amount": "0.000000123456789",
        "amount_role": "DEBIT",
        "precision": "EXACT_RAW_DECIMAL",
        "source_id": "venue-read",
        "source_version": "v1",
        "source_received_at_ms": T0,
        "raw_sha256": "a" * 64,
    }
    values.update(overrides)
    return ExecutionFeeComponentV2(**values)


def test_v1_bytes_ids_and_parser_remain_unchanged():
    v1 = _event()
    old_bytes = canonical_json_bytes(v1)
    old_id = v1.event_id
    parsed = parse_trade_execution_event(v1.model_dump(mode="json"))
    assert type(parsed) is TradeExecutionEventV1
    assert parsed.event_id == old_id
    assert canonical_json_bytes(parsed) == old_bytes
    assert Topics.TRADE_EXECUTION_EVENT == "kairos.execution.trade_event.v1"
    assert Topics.TRADE_EXECUTION_EVENT_V2 == "kairos.execution.trade_event.v2"


def test_unknown_fee_is_not_a_zero_and_roundtrips_with_own_id():
    event = _v2()
    assert event.fee_usd is None and event.fee.coverage == "UNKNOWN"
    assert event.event_id != _event().event_id
    assert type(parse_trade_execution_event(event.model_dump(mode="json"))) is TradeExecutionEventV2
    assert TradeExecutionEventV2.model_validate_json(event.model_dump_json()) == event


def test_multicurrency_precise_and_rebate_keep_original_values():
    first = _component()
    second = _component(component_id="rebate-2", asset="BTC", amount="-0.000000000001", amount_role="REBATE")
    bundle = ExecutionFeeBundleV2(
        scope_kind="TRADE", scope_reference=TRADE_ID, coverage="INCOMPLETE", components=(first, second)
    )
    event = _v2(fee=bundle)
    assert event.fee_usd is None
    assert event.fee.components[0].amount == Decimal("0.000000123456789")
    assert event.fee.components[1].amount == Decimal("-0.000000000001")
    assert event.model_dump(mode="json")["fee"]["components"][1]["amount"] == "-1E-12"


@pytest.mark.parametrize("value", [0.0, 0.1, float("nan"), True, 1])
def test_lossy_or_non_decimal_source_amount_is_rejected(value):
    with pytest.raises(ValidationError):
        _component(amount=value)


def test_final_valuation_requires_finality_and_fx_provenance_and_exact_components():
    component = _component()
    with pytest.raises(ValidationError):
        ExecutionFeeBundleV2(scope_kind="TRADE", scope_reference=TRADE_ID, coverage="FINAL")
    with pytest.raises(ValidationError):
        ExecutionFeeBundleV2(
            scope_kind="TRADE",
            scope_reference=TRADE_ID,
            coverage="INCOMPLETE",
            usd_status="FINAL",
            valuation_evidence_sha256="b" * 64,
        )
    fee = ExecutionFeeBundleV2(
        scope_kind="TRADE",
        scope_reference=TRADE_ID,
        coverage="FINAL",
        components=(component,),
        finality_evidence_sha256="c" * 64,
        usd_status="PROVISIONAL",
        valuation_evidence_sha256="b" * 64,
    )
    event = _v2(fee=fee, fee_usd="0.000000123")
    assert event.fee_usd == Decimal("0.000000123")
    with pytest.raises(ValidationError):
        _v2(fee=fee, fee_usd=0.000000123)
    with pytest.raises(ValidationError, match="unavailable qualified sign"):
        ExecutionFeeBundleV2.model_validate(fee.model_copy(update={"usd_status": "FINAL"}))


def test_final_coverage_cannot_hide_unknown_components_or_nonzero_empty_fee():
    with pytest.raises(ValidationError, match="unknown amount"):
        ExecutionFeeBundleV2(
            scope_kind="TRADE",
            scope_reference=TRADE_ID,
            coverage="FINAL",
            finality_evidence_sha256="c" * 64,
            components=(_component(amount=None, precision="UNKNOWN"),),
        )
    empty = ExecutionFeeBundleV2(
        scope_kind="TRADE",
        scope_reference=TRADE_ID,
        coverage="FINAL",
        finality_evidence_sha256="c" * 64,
        usd_status="FINAL",
        valuation_evidence_sha256="b" * 64,
    )
    assert _v2(fee=empty, fee_usd="0").fee_usd == 0
    with pytest.raises(ValidationError, match="empty fee"):
        _v2(fee=empty, fee_usd="1")


def test_final_zero_components_require_zero_usd_and_normalize_negative_zero():
    component = _component(amount="-0.00", amount_role="DEBIT")
    bundle = ExecutionFeeBundleV2(
        scope_kind="TRADE",
        scope_reference=TRADE_ID,
        coverage="FINAL",
        components=(component,),
        finality_evidence_sha256="c" * 64,
        usd_status="FINAL",
        valuation_evidence_sha256="b" * 64,
    )
    for amount in ("123", "-123"):
        with pytest.raises(ValidationError, match="must be zero USD"):
            _v2(fee=bundle, fee_usd=amount)
    event = _v2(fee=bundle, fee_usd="-0.00")
    assert event.fee_usd == Decimal(0) and not event.fee_usd.is_signed()
    assert event.fee.components[0].amount.is_signed()


def test_amount_role_is_not_inferred_from_sign_and_unknown_cannot_be_final_usd():
    unknown_positive = _component(amount="0.01", amount_role="UNKNOWN")
    unknown_negative = _component(component_id="negative", amount="-0.01", amount_role="UNKNOWN")
    assert unknown_positive.amount_role == unknown_negative.amount_role == "UNKNOWN"
    with pytest.raises(ValidationError, match="known amount roles"):
        ExecutionFeeBundleV2(
            scope_kind="TRADE",
            scope_reference=TRADE_ID,
            coverage="FINAL",
            finality_evidence_sha256="c" * 64,
            usd_status="FINAL",
            valuation_evidence_sha256="b" * 64,
            components=(unknown_positive, unknown_negative),
        )


def test_fee_update_has_exact_prior_and_scope_without_changing_v1():
    original = _v2()
    fee = original.fee.model_copy(update={"supersedes_event_id": original.event_id})
    updated = _v2(
        event_seq=2,
        event_type="FEE_UPDATED",
        fee=fee,
        requested_quantity=None,
        filled_quantity=None,
        position_quantity=None,
    )
    assert updated.event_id != original.event_id
    assert updated.fee.supersedes_event_id == original.event_id
    with pytest.raises(ValidationError):
        _v2(event_type="FEE_UPDATED")
    with pytest.raises(ValidationError):
        TradeExecutionEventV1.model_validate(updated.model_dump(mode="json"))


def test_fee_update_must_not_invent_or_default_position_and_order_quantities():
    first = _v2()
    fee = first.fee.model_copy(update={"supersedes_event_id": first.event_id})
    for field in ("requested_quantity", "filled_quantity", "position_quantity"):
        quantities = {"requested_quantity": None, "filled_quantity": None, "position_quantity": None}
        quantities[field] = 0.0
        with pytest.raises(ValidationError, match="cannot invent"):
            _v2(event_type="FEE_UPDATED", fee=fee, **quantities)
    for field in ("requested_quantity", "filled_quantity", "position_quantity"):
        with pytest.raises(ValidationError, match="requires explicit"):
            _v2(**{field: None})
    with pytest.raises(ValidationError, match="cannot invent an execution price"):
        _v2(
            event_type="FEE_UPDATED",
            fee=fee,
            requested_quantity=None,
            filled_quantity=None,
            position_quantity=None,
            average_price=100,
        )


def test_unknown_version_and_wrong_scope_are_rejected():
    payload = _v2().model_dump(mode="json")
    payload["contract_version"] = "trade-execution-event.v99"
    with pytest.raises(ValueError, match="unsupported"):
        parse_trade_execution_event(payload)
    with pytest.raises(ValidationError):
        _v2(fee=ExecutionFeeBundleV2(scope_kind="TRADE", scope_reference="other", coverage="UNKNOWN"))


def test_fill_scope_is_fail_closed_until_qualified_fill_ownership_exists():
    with pytest.raises(ValidationError, match="qualified fill source"):
        ExecutionFeeBundleV2(scope_kind="FILL", scope_reference="fill-1", coverage="UNKNOWN")
    with pytest.raises(ValidationError, match="qualified fill source"):
        ExecutionFeeBundleV2(
            scope_kind="FILL", scope_reference="fill-1", coverage="INCOMPLETE", components=(_component(),)
        )


def test_v2_revalidates_copied_nested_instances_and_event_fields():
    unknown = ExecutionFeeBundleV2(scope_kind="TRADE", scope_reference=TRADE_ID, coverage="UNKNOWN")
    with pytest.raises(ValidationError):
        _v2(fee=unknown.model_copy(update={"coverage": "BOGUS"}))
    with pytest.raises(ValidationError):
        _v2(fee=unknown.model_copy(update={"usd_status": "BOGUS"}))
    invalid_component = _component().model_copy(update={"precision": "BOGUS"})
    with pytest.raises(ValidationError):
        ExecutionFeeBundleV2(
            scope_kind="TRADE",
            scope_reference=TRADE_ID,
            coverage="INCOMPLETE",
            components=(invalid_component,),
        )
    for field, value in (("event_type", "BOGUS"), ("contract_version", "trade-execution-event.v1")):
        with pytest.raises(ValidationError):
            TradeExecutionEventV2.model_validate(_v2().model_copy(update={field: value}))


def test_v2_nested_roundtrip_preserves_types_and_canonical_id():
    fee = ExecutionFeeBundleV2(
        scope_kind="TRADE", scope_reference=TRADE_ID, coverage="INCOMPLETE", components=(_component(),)
    )
    event = _v2(fee=fee)
    parsed = TradeExecutionEventV2.model_validate_json(event.model_dump_json())
    assert type(parsed.fee) is ExecutionFeeBundleV2
    assert type(parsed.fee.components[0]) is ExecutionFeeComponentV2
    assert type(parsed.fee.components[0].amount) is Decimal
    assert parsed.event_id == event.event_id
    assert canonical_json_bytes(parsed) == canonical_json_bytes(event)

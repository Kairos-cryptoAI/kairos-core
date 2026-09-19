"""Versioned, SIM-only contracts for the offline market-data simulator.

These messages intentionally live beside the PAPER contracts without extending
``TradingMode``.  They describe recorded Binance inputs and model outcomes;
they never represent a venue order, an account, an EVEDEX profile or a trading
readiness decision.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from ..enums import Side
from .base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    canonical_sha256,
    datetime_from_unix_ms,
)
from .strategy import StrategyIntentV1

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
SimulationSymbol = Literal["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
BookContinuity = Literal["ADMITTED", "GAP", "RECONNECT", "UNKNOWN", "UNAVAILABLE"]
SimulationEventType = Literal[
    "ADMITTED",
    "ENTRY_FILLED",
    "ENTRY_PARTIAL",
    "ENTRY_NO_FILL",
    "STOP_TRIGGERED",
    "TARGET_TRIGGERED",
    "TIMEOUT_TRIGGERED",
    "NO_ADMITTED_BOOK",
    "SOURCE_BARRIER",
    "RECOVERED",
    "FLAT",
    "UNRESOLVED",
]


def _normalized_identifier(value: str, *, name: str, uppercase: bool = False) -> str:
    expected = value.strip().upper() if uppercase else value.strip()
    if not expected or value != expected:
        qualifier = " uppercase" if uppercase else ""
        raise ValueError(f"{name} must be a non-empty normalized{qualifier} string")
    return value


def _set_default_envelope(message: StrictKairosMessage, *, stable_id: str, timestamp_ms: int) -> None:
    if "message_id" not in message.model_fields_set:
        object.__setattr__(message, "message_id", stable_id)
    if "correlation_id" not in message.model_fields_set:
        object.__setattr__(message, "correlation_id", stable_id)
    if "produced_at" not in message.model_fields_set:
        object.__setattr__(message, "produced_at", datetime_from_unix_ms(timestamp_ms))


class RecordedBookLevelV1(StrictValueModel):
    """One displayed level of a previously persisted Binance UM top-N book."""

    price: PositiveFloat
    quantity: PositiveFloat


class RecordedTopNBookFrameV1(StrictKairosMessage):
    """Hash-chained recorded book frame, not proof of an observed venue fill."""

    contract_version: Literal["sim-book-frame.v1"] = "sim-book-frame.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    market_data_venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    stream_kind: Literal["TOP_N_SNAPSHOT"] = "TOP_N_SNAPSHOT"
    tape_id: str = Field(..., min_length=1, max_length=128)
    stream_epoch: str = Field(..., min_length=1, max_length=128)
    symbol: SimulationSymbol
    tape_sequence: PositiveInt
    exchange_update_id: PositiveInt
    exchange_at_ms: NonNegativeInt
    received_at_ms: NonNegativeInt
    persisted_at_ms: NonNegativeInt
    raw_payload_sha256: Sha256Hex
    previous_frame_sha256: Sha256Hex | None = None
    continuity: BookContinuity
    bids: tuple[RecordedBookLevelV1, ...] = Field(default_factory=tuple, max_length=100)
    asks: tuple[RecordedBookLevelV1, ...] = Field(default_factory=tuple, max_length=100)
    frame_sha256: Sha256Hex | None = None

    @field_validator("tape_id", "stream_epoch")
    @classmethod
    def validate_identifier(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_frame(self) -> Self:
        if not self.exchange_at_ms <= self.received_at_ms <= self.persisted_at_ms:
            raise ValueError("book frame requires exchange <= received <= persisted timestamps")
        if self.tape_sequence == 1 and self.previous_frame_sha256 is not None:
            raise ValueError("the first tape frame cannot reference a predecessor")
        if self.tape_sequence > 1 and self.previous_frame_sha256 is None:
            raise ValueError("a non-root tape frame must reference its predecessor")
        if self.previous_frame_sha256 == self.raw_payload_sha256:
            raise ValueError("a book frame predecessor cannot equal its raw payload hash")
        if self.continuity == "ADMITTED" and (not self.bids or not self.asks):
            raise ValueError("an admitted book frame requires both displayed sides")
        bid_prices = tuple(level.price for level in self.bids)
        ask_prices = tuple(level.price for level in self.asks)
        if bid_prices != tuple(sorted(set(bid_prices), reverse=True)):
            raise ValueError("book bids must be unique and strictly descending")
        if ask_prices != tuple(sorted(set(ask_prices))):
            raise ValueError("book asks must be unique and strictly ascending")
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError("book must not be locked or crossed")
        expected = canonical_sha256(self.identity_payload())
        if self.frame_sha256 is not None and self.frame_sha256 != expected:
            raise ValueError("frame_sha256 does not match the canonical recorded book frame")
        object.__setattr__(self, "frame_sha256", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.persisted_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "asks": [level.model_dump(mode="json") for level in self.asks],
            "bids": [level.model_dump(mode="json") for level in self.bids],
            "continuity": self.continuity,
            "contract_version": self.contract_version,
            "exchange_at_ms": self.exchange_at_ms,
            "exchange_update_id": self.exchange_update_id,
            "execution_environment": self.execution_environment,
            "market_data_venue": self.market_data_venue,
            "persisted_at_ms": self.persisted_at_ms,
            "previous_frame_sha256": self.previous_frame_sha256,
            "raw_payload_sha256": self.raw_payload_sha256,
            "received_at_ms": self.received_at_ms,
            "stream_epoch": self.stream_epoch,
            "stream_kind": self.stream_kind,
            "symbol": self.symbol,
            "tape_id": self.tape_id,
            "tape_sequence": self.tape_sequence,
        }

    def canonical_frame_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())


class SimulationAssumptionsV1(StrictValueModel):
    """Frozen, explicit model assumptions used by one isolated simulator session."""

    model_version: Literal["causal-taker-ioc.model-v1"] = "causal-taker-ioc.model-v1"
    liquidity_policy: Literal["SESSION_PRICE_DEBIT_NO_REPLENISHMENT"] = "SESSION_PRICE_DEBIT_NO_REPLENISHMENT"
    ambiguous_bar_policy: Literal["STOP_WINS"] = "STOP_WINS"
    latency_ms: NonNegativeInt
    maximum_book_age_ms: PositiveInt
    maximum_frame_latency_ms: PositiveInt
    depth_participation_fraction: float = Field(..., gt=0, le=1)
    adverse_slippage_bps: NonNegativeFloat
    taker_fee_bps: NonNegativeFloat
    price_tick: PositiveFloat
    quantity_step: PositiveFloat
    max_terminal_commands: int = Field(default=1_024, ge=1, le=1_024)
    assumptions_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_assumptions(self) -> Self:
        if self.adverse_slippage_bps >= 10_000 or self.taker_fee_bps > 10_000:
            raise ValueError("model slippage must be below 100%, fees at most 100%")
        expected = canonical_sha256(self.identity_payload())
        if self.assumptions_sha256 is not None and self.assumptions_sha256 != expected:
            raise ValueError("assumptions_sha256 does not match the canonical simulation assumptions")
        object.__setattr__(self, "assumptions_sha256", expected)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "adverse_slippage_bps": self.adverse_slippage_bps,
            "ambiguous_bar_policy": self.ambiguous_bar_policy,
            "depth_participation_fraction": self.depth_participation_fraction,
            "latency_ms": self.latency_ms,
            "liquidity_policy": self.liquidity_policy,
            "max_terminal_commands": self.max_terminal_commands,
            "maximum_book_age_ms": self.maximum_book_age_ms,
            "maximum_frame_latency_ms": self.maximum_frame_latency_ms,
            "model_version": self.model_version,
            "price_tick": self.price_tick,
            "quantity_step": self.quantity_step,
            "taker_fee_bps": self.taker_fee_bps,
        }


class SimulationStrategyRefV1(StrictValueModel):
    """An explicitly approved-for-research strategy identity, never a PAPER allow-list."""

    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)

    @field_validator("strategy_id", "strategy_revision")
    @classmethod
    def validate_identifier(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)


class SimulationSessionV1(StrictKairosMessage):
    """Immutable, isolated offline replay session definition."""

    contract_version: Literal["simulation-session.v1"] = "simulation-session.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    session_id: Sha256Hex | None = None
    tape_id: str = Field(..., min_length=1, max_length=128)
    tape_sha256: Sha256Hex
    assumptions: SimulationAssumptionsV1
    strategy_allowlist: tuple[SimulationStrategyRefV1, ...] = Field(..., min_length=1, max_length=32)
    started_at_ms: NonNegativeInt
    ends_at_ms: PositiveInt
    admission_policy: Literal["EXPLICIT_SIMULATOR_SESSION_ONLY"] = "EXPLICIT_SIMULATOR_SESSION_ONLY"
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @field_validator("tape_id")
    @classmethod
    def validate_tape(cls, value: str) -> str:
        return _normalized_identifier(value, name="tape_id")

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if self.ends_at_ms <= self.started_at_ms:
            raise ValueError("simulation session must end after it starts")
        refs = tuple(
            sorted(self.strategy_allowlist, key=lambda item: (item.strategy_id, item.strategy_revision))
        )
        keys = [(item.strategy_id, item.strategy_revision) for item in refs]
        if len(keys) != len(set(keys)):
            raise ValueError("simulation strategy allowlist must not contain duplicates")
        object.__setattr__(self, "strategy_allowlist", refs)
        expected = canonical_sha256(self.identity_payload())
        if self.session_id is not None and self.session_id != expected:
            raise ValueError("session_id does not match the canonical simulation session")
        object.__setattr__(self, "session_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.started_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_policy": self.admission_policy,
            "alpha_claim": self.alpha_claim,
            "assumptions_sha256": self.assumptions.assumptions_sha256,
            "contract_version": self.contract_version,
            "ends_at_ms": self.ends_at_ms,
            "execution_environment": self.execution_environment,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "started_at_ms": self.started_at_ms,
            "strategy_allowlist": [item.model_dump(mode="json") for item in self.strategy_allowlist],
            "tape_id": self.tape_id,
            "tape_sha256": self.tape_sha256,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationAdmissionV1(StrictKairosMessage):
    """Explicit research admission of an immutable strategy intent into one SIM session."""

    contract_version: Literal["simulation-admission.v1"] = "simulation-admission.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    admission_id: Sha256Hex | None = None
    session: SimulationSessionV1
    session_id: Sha256Hex | None = None
    intent: StrategyIntentV1
    intent_sha256: Sha256Hex | None = None
    quantity: PositiveFloat
    price_cap: PositiveFloat
    admitted_at_ms: NonNegativeInt
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        if self.intent.symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}:
            raise ValueError("simulation admission supports only the fixed five-symbol universe")
        if self.intent.venue != "BINANCE_UM":
            raise ValueError("simulation admission accepts only Binance UM strategy intents")
        if not self.session.started_at_ms <= self.admitted_at_ms <= self.session.ends_at_ms:
            raise ValueError("simulation admission must occur inside its immutable session")
        if not self.intent.decision_ts_ms <= self.admitted_at_ms <= self.intent.entry_expires_ts_ms:
            raise ValueError("simulation admission must occur before the immutable intent expires")
        allowed = {(item.strategy_id, item.strategy_revision) for item in self.session.strategy_allowlist}
        if (self.intent.strategy_id, self.intent.strategy_revision) not in allowed:
            raise ValueError("strategy intent is not on this simulation session allowlist")
        if self.intent.side is Side.LONG and self.price_cap < self.intent.reference_price:
            raise ValueError("LONG simulation admission price cap cannot improve on the reference price")
        if self.intent.side is Side.SHORT and self.price_cap > self.intent.reference_price:
            raise ValueError("SHORT simulation admission price cap cannot improve on the reference price")
        session_id = self.session.session_id
        intent_id = self.intent.intent_id
        if session_id is None or intent_id is None:
            raise ValueError("simulation admission requires canonical session and intent identities")
        if self.session_id is not None and self.session_id != session_id:
            raise ValueError("session_id does not match the immutable session")
        if self.intent_sha256 is not None and self.intent_sha256 != intent_id:
            raise ValueError("intent_sha256 does not match the immutable strategy intent")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "intent_sha256", intent_id)
        expected = canonical_sha256(self.identity_payload())
        if self.admission_id is not None and self.admission_id != expected:
            raise ValueError("admission_id does not match the canonical simulation admission")
        object.__setattr__(self, "admission_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.admitted_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admitted_at_ms": self.admitted_at_ms,
            "alpha_claim": self.alpha_claim,
            "contract_version": self.contract_version,
            "execution_environment": self.execution_environment,
            "intent_id": self.intent.intent_id,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "price_cap": self.price_cap,
            "quantity": self.quantity,
            "session_id": self.session.session_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationTradeEventV1(StrictKairosMessage):
    """Append-only SIM lifecycle fact; it cannot be used as an execution event."""

    contract_version: Literal["simulation-trade-event.v1"] = "simulation-trade-event.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    event_id: Sha256Hex | None = None
    session_id: Sha256Hex
    admission_id: Sha256Hex
    intent_id: Sha256Hex
    trade_id: Sha256Hex
    event_seq: PositiveInt
    event_type: SimulationEventType
    occurred_at_ms: NonNegativeInt
    symbol: SimulationSymbol
    side: Literal["LONG", "SHORT"]
    filled_quantity: NonNegativeFloat = 0.0
    average_price: PositiveFloat | None = None
    model_frame_sha256: Sha256Hex | None = None
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if any(not code or code != code.strip() or len(code) > 100 for code in self.reason_codes):
            raise ValueError("simulation event reason codes must be normalized non-empty strings")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        requires_fill = self.event_type in {
            "ENTRY_FILLED",
            "ENTRY_PARTIAL",
            "STOP_TRIGGERED",
            "TARGET_TRIGGERED",
        }
        prohibits_fill = self.event_type in {"ENTRY_NO_FILL", "NO_ADMITTED_BOOK", "SOURCE_BARRIER"}
        if requires_fill and (self.filled_quantity <= 0 or self.average_price is None):
            raise ValueError("filled simulation events require quantity and average price")
        if prohibits_fill and (self.filled_quantity != 0 or self.average_price is not None):
            raise ValueError("non-fill simulation events cannot claim a model fill")
        expected = canonical_sha256(self.identity_payload())
        if self.event_id is not None and self.event_id != expected:
            raise ValueError("event_id does not match the canonical simulation trade event")
        object.__setattr__(self, "event_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.occurred_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "alpha_claim": self.alpha_claim,
            "average_price": self.average_price,
            "contract_version": self.contract_version,
            "event_seq": self.event_seq,
            "event_type": self.event_type,
            "execution_environment": self.execution_environment,
            "filled_quantity": self.filled_quantity,
            "intent_id": self.intent_id,
            "model_frame_sha256": self.model_frame_sha256,
            "occurred_at_ms": self.occurred_at_ms,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "reason_codes": self.reason_codes,
            "session_id": self.session_id,
            "side": self.side,
            "symbol": self.symbol,
            "trade_id": self.trade_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationResultV1(StrictKairosMessage):
    """Terminal SIM-only result with explicit non-eligibility boundaries."""

    contract_version: Literal["simulation-result.v1"] = "simulation-result.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    venue_execution_observed: Literal[False] = False
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False
    result_id: Sha256Hex | None = None
    session_id: Sha256Hex
    admission_id: Sha256Hex
    intent_id: Sha256Hex
    trade_id: Sha256Hex
    terminal_event_id: Sha256Hex
    completed_at_ms: NonNegativeInt
    final_state: Literal["FLAT", "UNRESOLVED", "NO_FILL", "BLOCKED"]
    entry_filled_quantity: NonNegativeFloat
    exit_filled_quantity: NonNegativeFloat
    entry_average_price: PositiveFloat | None = None
    exit_average_price: PositiveFloat | None = None
    model_realized_pnl_quote: float = 0.0
    model_fee_quote: NonNegativeFloat = 0.0
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if any(not code or code != code.strip() or len(code) > 100 for code in self.reason_codes):
            raise ValueError("simulation result reason codes must be normalized non-empty strings")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if self.final_state == "FLAT":
            if (
                self.entry_filled_quantity <= 0
                or self.exit_filled_quantity != self.entry_filled_quantity
                or self.entry_average_price is None
                or self.exit_average_price is None
            ):
                raise ValueError("a flat simulation result requires matched entry and exit model fills")
        elif self.final_state == "UNRESOLVED":
            if (
                self.entry_filled_quantity <= 0
                or self.exit_filled_quantity != 0
                or self.entry_average_price is None
            ):
                raise ValueError("an unresolved result requires an unclosed model entry")
            if self.exit_average_price is not None:
                raise ValueError("an unresolved result cannot invent an exit price")
        else:
            if (
                self.entry_filled_quantity != 0
                or self.exit_filled_quantity != 0
                or self.entry_average_price is not None
                or self.exit_average_price is not None
                or self.model_realized_pnl_quote != 0
                or self.model_fee_quote != 0
            ):
                raise ValueError("no-fill and blocked results cannot invent economic outcomes")
        expected = canonical_sha256(self.identity_payload())
        if self.result_id is not None and self.result_id != expected:
            raise ValueError("result_id does not match the canonical simulation result")
        object.__setattr__(self, "result_id", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.completed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "alpha_claim": self.alpha_claim,
            "completed_at_ms": self.completed_at_ms,
            "contract_version": self.contract_version,
            "entry_average_price": self.entry_average_price,
            "entry_filled_quantity": self.entry_filled_quantity,
            "execution_environment": self.execution_environment,
            "exit_average_price": self.exit_average_price,
            "exit_filled_quantity": self.exit_filled_quantity,
            "final_state": self.final_state,
            "intent_id": self.intent_id,
            "model_fee_quote": self.model_fee_quote,
            "model_realized_pnl_quote": self.model_realized_pnl_quote,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "reason_codes": self.reason_codes,
            "session_id": self.session_id,
            "terminal_event_id": self.terminal_event_id,
            "trade_id": self.trade_id,
            "trial15_eligible": self.trial15_eligible,
            "venue_execution_observed": self.venue_execution_observed,
        }

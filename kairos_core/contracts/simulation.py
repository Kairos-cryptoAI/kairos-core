"""Versioned, SIM-only contracts for the offline market-data simulator.

These messages intentionally live beside the PAPER contracts without extending
``TradingMode``.  They describe recorded Binance inputs and model outcomes;
they never represent a venue order, an account, an EVEDEX profile or a trading
readiness decision.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from ..enums import ReviewDecision, Side
from .base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    canonical_sha256,
    datetime_from_unix_ms,
)
from .strategy import CandidateReviewV1, StrategyIntentV1

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
SimulationTradeState = Literal["PENDING", "ACTIVE", "FLAT", "UNRESOLVED", "NO_FILL", "BLOCKED"]
SimulationCommandKind = Literal["ENTRY_IOC", "STOP_EXIT_IOC", "TARGET_EXIT_IOC", "TIMEOUT_EXIT_IOC"]
SimulationOrderSide = Literal["BUY", "SELL"]
SimulationReceiptStatus = Literal["FILLED", "PARTIAL", "NO_FILL", "BLOCKED"]
SimulationSessionReceiptState = Literal["COMPLETED", "BLOCKED"]


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
    """Hash-chained recorded book frame, not proof of an observed venue fill.

    ``tape_sequence`` is one monotonically increasing sequence for the entire
    tape, across every symbol.  This intentionally gives an offline replay a
    single total order; a per-symbol execution controller may still retain its
    own causal cursor after selecting frames for its symbol.
    """

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
        if self.admitted_at_ms < self.intent.entry_eligible_ts_ms:
            raise ValueError("simulation admission cannot precede immutable next-bar entry eligibility")
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
                or self.exit_filled_quantity >= self.entry_filled_quantity
                or self.entry_average_price is None
            ):
                raise ValueError("an unresolved result requires a strictly positive remaining model exposure")
            if (self.exit_filled_quantity == 0) != (self.exit_average_price is None):
                raise ValueError(
                    "an unresolved result must show an exit price exactly when it has a partial exit"
                )
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


class SimulationChainHeadV1(StrictValueModel):
    """One immutable per-symbol closed-bar chain head captured when a tape seals."""

    symbol: SimulationSymbol
    entry_count: NonNegativeInt
    head_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_head(self) -> Self:
        if (self.entry_count == 0) != (self.head_sha256 is None):
            raise ValueError("an empty simulation chain must not claim a head hash")
        return self


class SimulationBookChainHeadV1(StrictValueModel):
    """The globally ordered recorded-book chain head captured when a tape seals."""

    entry_count: NonNegativeInt
    head_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_head(self) -> Self:
        if (self.entry_count == 0) != (self.head_sha256 is None):
            raise ValueError("an empty simulation book chain must not claim a head hash")
        return self


class SimulationTapeSealV1(StrictKairosMessage):
    """Frozen manifest for the only inputs an offline simulator may replay.

    The bar chains are independently contiguous per symbol.  The book chain is
    deliberately global across the tape, so frames from the five symbols have
    one auditable total order.  A session must reference this exact hash rather
    than a mutable directory or a live market-data endpoint.
    """

    contract_version: Literal["simulation-tape-seal.v1"] = "simulation-tape-seal.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    market_data_venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    tape_id: str = Field(..., min_length=1, max_length=128)
    sealed_at_ms: NonNegativeInt
    bar_chains: tuple[SimulationChainHeadV1, ...] = Field(..., min_length=5, max_length=5)
    book_chain: SimulationBookChainHeadV1
    tape_sha256: Sha256Hex | None = None
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @field_validator("tape_id")
    @classmethod
    def validate_tape_id(cls, value: str) -> str:
        return _normalized_identifier(value, name="tape_id")

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        chains = tuple(sorted(self.bar_chains, key=lambda item: item.symbol))
        symbols = tuple(item.symbol for item in chains)
        expected_symbols = tuple(sorted(("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")))
        if symbols != expected_symbols:
            raise ValueError(
                "simulation tape seal requires exactly one closed-bar chain for each fixed symbol"
            )
        object.__setattr__(self, "bar_chains", chains)
        expected = canonical_sha256(self.identity_payload())
        if self.tape_sha256 is not None and self.tape_sha256 != expected:
            raise ValueError("tape_sha256 does not match the canonical simulation tape seal")
        object.__setattr__(self, "tape_sha256", expected)
        _set_default_envelope(self, stable_id=expected, timestamp_ms=self.sealed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "alpha_claim": self.alpha_claim,
            "bar_chains": [item.model_dump(mode="json") for item in self.bar_chains],
            "book_chain": self.book_chain.model_dump(mode="json"),
            "contract_version": self.contract_version,
            "execution_environment": self.execution_environment,
            "market_data_venue": self.market_data_venue,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "sealed_at_ms": self.sealed_at_ms,
            "tape_id": self.tape_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationRiskDecisionV1(StrictKairosMessage):
    """Deterministic SIM-only admission decision with review and book lineage.

    This is deliberately not ``RiskTradeDecisionV1``: it carries neither a
    trading mode, account, venue profile nor any authority to create an order.
    It exists so the development simulator can prove the same candidate and
    review path without impersonating the EVEDEX PAPER risk contour.
    """

    contract_version: Literal["simulation-risk-decision.v1"] = "simulation-risk-decision.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    decision_id: Sha256Hex | None = None
    session: SimulationSessionV1
    intent: StrategyIntentV1
    review: CandidateReviewV1
    selected_book_frame: RecordedTopNBookFrameV1 | None = None
    session_id: Sha256Hex | None = None
    intent_id: Sha256Hex | None = None
    review_id: Sha256Hex | None = None
    selected_book_frame_sha256: Sha256Hex | None = None
    approved: bool
    rejection_reasons: tuple[str, ...] = ()
    quantity: NonNegativeFloat
    price_cap: PositiveFloat | None = None
    decided_at_ms: NonNegativeInt
    admission_policy: Literal["RECORDED_BOOK_SIMULATION_ONLY"] = "RECORDED_BOOK_SIMULATION_ONLY"
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        session_id = self.session.session_id
        intent_id = self.intent.intent_id
        review_id = self.review.review_id
        if session_id is None or intent_id is None or review_id is None:
            raise ValueError(
                "simulation risk decision requires canonical session, intent and review identities"
            )
        expected_values = {
            "session_id": session_id,
            "intent_id": intent_id,
            "review_id": review_id,
        }
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation decision lineage")
            object.__setattr__(self, field_name, expected)
        if self.review.intent.intent_id != intent_id:
            raise ValueError("simulation review and decision must carry the same immutable intent")
        allowed = {(item.strategy_id, item.strategy_revision) for item in self.session.strategy_allowlist}
        if (self.intent.strategy_id, self.intent.strategy_revision) not in allowed:
            raise ValueError("simulation risk decision intent is not on the session allowlist")
        if self.decided_at_ms < self.review.reviewed_at_ms:
            raise ValueError("simulation risk decision cannot predate candidate review")
        if not self.session.started_at_ms <= self.decided_at_ms <= self.session.ends_at_ms:
            raise ValueError("simulation risk decision must occur inside its immutable session")
        if self.decided_at_ms < self.intent.entry_eligible_ts_ms:
            raise ValueError("simulation risk decision cannot precede immutable next-bar entry eligibility")
        canonical_reasons = tuple(sorted(set(self.rejection_reasons)))
        if any(not reason or reason != reason.strip() or len(reason) > 100 for reason in canonical_reasons):
            raise ValueError("simulation rejection reasons must be normalized non-empty strings")
        object.__setattr__(self, "rejection_reasons", canonical_reasons)
        frame = self.selected_book_frame
        frame_sha256 = None if frame is None else frame.frame_sha256
        if self.selected_book_frame_sha256 is not None and self.selected_book_frame_sha256 != frame_sha256:
            raise ValueError("selected_book_frame_sha256 does not match the immutable recorded frame")
        object.__setattr__(self, "selected_book_frame_sha256", frame_sha256)
        if self.approved:
            if self.review.decision is not ReviewDecision.ALLOW:
                raise ValueError("only an ALLOW review can be approved for simulator admission")
            if self.decided_at_ms > self.intent.entry_expires_ts_ms:
                raise ValueError("an expired strategy intent cannot be simulator-approved")
            if self.quantity <= 0 or self.price_cap is None:
                raise ValueError("an approved simulation decision requires quantity and price cap")
            if canonical_reasons:
                raise ValueError("an approved simulation decision cannot contain rejection reasons")
            if frame is None or frame_sha256 is None or frame.continuity != "ADMITTED":
                raise ValueError("an approved simulation decision requires an admitted recorded book frame")
            if frame.tape_id != self.session.tape_id or frame.symbol != self.intent.symbol:
                raise ValueError(
                    "simulation decision frame must belong to the session tape and intent symbol"
                )
            if frame.persisted_at_ms > self.decided_at_ms:
                raise ValueError("simulation decision cannot select a future recorded book frame")
            if self.decided_at_ms - frame.persisted_at_ms > self.session.assumptions.maximum_book_age_ms:
                raise ValueError("simulation decision selected book frame is stale")
            if (
                frame.persisted_at_ms - frame.exchange_at_ms
                > self.session.assumptions.maximum_frame_latency_ms
            ):
                raise ValueError("simulation decision selected frame exceeds its frozen latency bound")
            if self.intent.side is Side.LONG and self.price_cap < frame.asks[0].price:
                raise ValueError("LONG simulation price cap cannot miss the selected recorded ask")
            if self.intent.side is Side.SHORT and self.price_cap > frame.bids[0].price:
                raise ValueError("SHORT simulation price cap cannot miss the selected recorded bid")
        elif self.quantity != 0 or self.price_cap is not None or not canonical_reasons:
            raise ValueError(
                "a rejected simulation decision requires zero size, no price cap and rejection reasons"
            )
        expected_id = canonical_sha256(self.identity_payload())
        if self.decision_id is not None and self.decision_id != expected_id:
            raise ValueError("decision_id does not match the canonical simulation risk decision")
        object.__setattr__(self, "decision_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.decided_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_policy": self.admission_policy,
            "alpha_claim": self.alpha_claim,
            "approved": self.approved,
            "contract_version": self.contract_version,
            "decided_at_ms": self.decided_at_ms,
            "execution_environment": self.execution_environment,
            "intent_id": self.intent_id,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "price_cap": self.price_cap,
            "quantity": self.quantity,
            "rejection_reasons": self.rejection_reasons,
            "review_id": self.review_id,
            "selected_book_frame_sha256": self.selected_book_frame_sha256,
            "session_id": self.session_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationAdmissionV2(StrictKairosMessage):
    """An admission derived only from an approved immutable SIM risk decision."""

    contract_version: Literal["simulation-admission.v2"] = "simulation-admission.v2"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    admission_id: Sha256Hex | None = None
    decision: SimulationRiskDecisionV1
    session: SimulationSessionV1 | None = None
    intent: StrategyIntentV1 | None = None
    review: CandidateReviewV1 | None = None
    session_id: Sha256Hex | None = None
    intent_sha256: Sha256Hex | None = None
    review_id: Sha256Hex | None = None
    decision_id: Sha256Hex | None = None
    selected_book_frame_sha256: Sha256Hex | None = None
    quantity: PositiveFloat | None = None
    price_cap: PositiveFloat | None = None
    admitted_at_ms: NonNegativeInt
    admission_policy: Literal["APPROVED_SIMULATION_DECISION_ONLY"] = "APPROVED_SIMULATION_DECISION_ONLY"
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        decision = self.decision
        if not decision.approved or decision.decision_id is None:
            raise ValueError("simulation admission requires an approved canonical simulation risk decision")
        expected_values = {
            "session": decision.session,
            "intent": decision.intent,
            "review": decision.review,
            "session_id": decision.session_id,
            "intent_sha256": decision.intent_id,
            "review_id": decision.review_id,
            "decision_id": decision.decision_id,
            "selected_book_frame_sha256": decision.selected_book_frame_sha256,
            "quantity": decision.quantity,
            "price_cap": decision.price_cap,
        }
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation risk decision")
            object.__setattr__(self, field_name, expected)
        if self.session is None or self.intent is None or self.quantity is None or self.price_cap is None:
            raise ValueError("simulation admission requires complete immutable decision lineage")
        if not decision.decided_at_ms <= self.admitted_at_ms <= self.intent.entry_expires_ts_ms:
            raise ValueError("simulation admission must follow its decision and precede intent expiry")
        if self.admitted_at_ms < self.intent.entry_eligible_ts_ms:
            raise ValueError("simulation admission cannot precede immutable next-bar entry eligibility")
        if self.admitted_at_ms > self.session.ends_at_ms:
            raise ValueError("simulation admission must occur inside its immutable session")
        expected_id = canonical_sha256(self.identity_payload())
        if self.admission_id is not None and self.admission_id != expected_id:
            raise ValueError("admission_id does not match the canonical simulation admission")
        object.__setattr__(self, "admission_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.admitted_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_policy": self.admission_policy,
            "alpha_claim": self.alpha_claim,
            "contract_version": self.contract_version,
            "decision_id": self.decision_id,
            "execution_environment": self.execution_environment,
            "intent_id": self.intent_sha256,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "price_cap": self.price_cap,
            "quantity": self.quantity,
            "review_id": self.review_id,
            "selected_book_frame_sha256": self.selected_book_frame_sha256,
            "session_id": self.session_id,
            "trial15_eligible": self.trial15_eligible,
            "admitted_at_ms": self.admitted_at_ms,
        }


class SimulationTradeV1(StrictKairosMessage):
    """Immutable admission lineage for one simulator-only trade lifecycle."""

    contract_version: Literal["simulation-trade.v1"] = "simulation-trade.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    trade_id: Sha256Hex | None = None
    admission: SimulationAdmissionV1 | SimulationAdmissionV2
    session_id: Sha256Hex | None = None
    admission_id: Sha256Hex | None = None
    intent_id: Sha256Hex | None = None
    symbol: SimulationSymbol | None = None
    side: Side | None = None
    created_at_ms: NonNegativeInt
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_trade(self) -> Self:
        admission = self.admission
        admission_id = admission.admission_id
        session_id = admission.session_id
        intent_id = admission.intent_sha256
        intent = admission.intent
        if admission_id is None or session_id is None or intent_id is None or intent is None:
            raise ValueError("simulation trade requires canonical admission lineage")
        expected_values = {
            "session_id": session_id,
            "admission_id": admission_id,
            "intent_id": intent_id,
            "symbol": intent.symbol,
            "side": intent.side,
        }
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation admission")
            object.__setattr__(self, field_name, expected)
        if self.side is Side.FLAT:
            raise ValueError("a simulation trade must be directional")
        if self.created_at_ms < self.admission.admitted_at_ms:
            raise ValueError("a simulation trade cannot predate its admission")
        expected_id = canonical_sha256(self.identity_payload())
        if self.trade_id is not None and self.trade_id != expected_id:
            raise ValueError("trade_id does not match the canonical simulation trade")
        object.__setattr__(self, "trade_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.created_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "alpha_claim": self.alpha_claim,
            "contract_version": self.contract_version,
            "created_at_ms": self.created_at_ms,
            "execution_environment": self.execution_environment,
            "intent_id": self.intent_id,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "session_id": self.session_id,
            "side": None if self.side is None else self.side.value,
            "symbol": self.symbol,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationCommandV1(StrictKairosMessage):
    """One immutable input to the pure simulator IOC kernel, never a venue order."""

    contract_version: Literal["simulation-command.v1"] = "simulation-command.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    command_id: Sha256Hex | None = None
    trade: SimulationTradeV1
    session_id: Sha256Hex | None = None
    admission_id: Sha256Hex | None = None
    intent_id: Sha256Hex | None = None
    trade_id: Sha256Hex | None = None
    symbol: SimulationSymbol | None = None
    side: Side | None = None
    order_side: SimulationOrderSide | None = None
    command_kind: SimulationCommandKind
    quantity: PositiveFloat
    price_cap: PositiveFloat
    submitted_at_ms: NonNegativeInt
    persisted_at_ms: NonNegativeInt
    eligible_at_ms: NonNegativeInt
    expires_at_ms: NonNegativeInt
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        expected_values = {
            "session_id": self.trade.session_id,
            "admission_id": self.trade.admission_id,
            "intent_id": self.trade.intent_id,
            "trade_id": self.trade.trade_id,
            "symbol": self.trade.symbol,
            "side": self.trade.side,
        }
        if any(value is None for value in expected_values.values()):
            raise ValueError("simulation command requires canonical simulation trade lineage")
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation trade")
            object.__setattr__(self, field_name, expected)
        if self.side is None:
            raise ValueError("simulation command requires a directional trade side")
        is_entry = self.command_kind == "ENTRY_IOC"
        expected_order_side: SimulationOrderSide
        if self.side is Side.LONG:
            expected_order_side = "BUY" if is_entry else "SELL"
        elif self.side is Side.SHORT:
            expected_order_side = "SELL" if is_entry else "BUY"
        else:
            raise ValueError("simulation command cannot derive an order side from FLAT")
        if self.order_side is not None and self.order_side != expected_order_side:
            raise ValueError(
                "simulation command order_side does not match its immutable trade and command kind"
            )
        object.__setattr__(self, "order_side", expected_order_side)
        if self.persisted_at_ms < self.submitted_at_ms:
            raise ValueError("simulation command persistence cannot predate submission")
        if self.eligible_at_ms < self.trade.created_at_ms:
            raise ValueError("simulation command eligibility cannot predate its trade")
        if self.submitted_at_ms < self.eligible_at_ms:
            raise ValueError("simulation command submission cannot predate eligibility")
        if self.expires_at_ms < self.eligible_at_ms:
            raise ValueError("simulation command expiry cannot predate eligibility")
        expected_id = canonical_sha256(self.identity_payload())
        if self.command_id is not None and self.command_id != expected_id:
            raise ValueError("command_id does not match the canonical simulation command")
        object.__setattr__(self, "command_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.persisted_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "alpha_claim": self.alpha_claim,
            "command_kind": self.command_kind,
            "contract_version": self.contract_version,
            "eligible_at_ms": self.eligible_at_ms,
            "execution_environment": self.execution_environment,
            "expires_at_ms": self.expires_at_ms,
            "intent_id": self.intent_id,
            "order_side": self.order_side,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "persisted_at_ms": self.persisted_at_ms,
            "price_cap": self.price_cap,
            "quantity": self.quantity,
            "session_id": self.session_id,
            "side": None if self.side is None else self.side.value,
            "submitted_at_ms": self.submitted_at_ms,
            "symbol": self.symbol,
            "trade_id": self.trade_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationFillLevelV1(StrictValueModel):
    """One auditable simulated fill at a recorded book level."""

    book_price: PositiveFloat
    execution_price: PositiveFloat
    quantity: PositiveFloat
    fee_quote: NonNegativeFloat


class SimulationCommandReceiptV1(StrictKairosMessage):
    """Terminal, immutable outcome of one simulator command.

    A receipt records a model calculation, not exchange acknowledgement or a
    fill.  It is deliberately terminal: the pure kernel's ``WAIT`` outcome is
    not durable idempotency evidence and must be evaluated again later.
    """

    contract_version: Literal["simulation-command-receipt.v1"] = "simulation-command-receipt.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    receipt_id: Sha256Hex | None = None
    command: SimulationCommandV1
    command_id: Sha256Hex | None = None
    session_id: Sha256Hex | None = None
    admission_id: Sha256Hex | None = None
    intent_id: Sha256Hex | None = None
    trade_id: Sha256Hex | None = None
    assumptions_sha256: Sha256Hex | None = None
    model_frame_sha256: Sha256Hex | None = None
    status: SimulationReceiptStatus
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)
    arrival_at_ms: NonNegativeInt
    filled_quantity: NonNegativeFloat
    cancelled_quantity: NonNegativeFloat
    average_price: PositiveFloat | None = None
    notional_quote: NonNegativeFloat
    fee_quote: NonNegativeFloat
    arrival_mid_price: PositiveFloat | None = None
    implementation_shortfall_quote: NonNegativeFloat
    level_fills: tuple[SimulationFillLevelV1, ...] = Field(default_factory=tuple, max_length=100)
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        command_id = self.command.command_id
        session_id = self.command.session_id
        admission_id = self.command.admission_id
        intent_id = self.command.intent_id
        trade_id = self.command.trade_id
        session = self.command.trade.admission.session
        if session is None:
            raise ValueError("simulation receipt requires the admission session")
        assumptions_sha256 = session.assumptions.assumptions_sha256
        if any(
            value is None
            for value in (command_id, session_id, admission_id, intent_id, trade_id, assumptions_sha256)
        ):
            raise ValueError("simulation receipt requires canonical command and assumption lineage")
        expected_values = {
            "command_id": command_id,
            "session_id": session_id,
            "admission_id": admission_id,
            "intent_id": intent_id,
            "trade_id": trade_id,
            "assumptions_sha256": assumptions_sha256,
        }
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation command")
            object.__setattr__(self, field_name, expected)
        if self.arrival_at_ms < self.command.submitted_at_ms:
            raise ValueError("simulation receipt arrival cannot predate command submission")
        if self.arrival_at_ms > self.command.expires_at_ms and self.filled_quantity > 0:
            raise ValueError("a model fill cannot arrive after command expiry")
        if any(not code or code != code.strip() or len(code) > 100 for code in self.reason_codes):
            raise ValueError("simulation receipt reason codes must be normalized non-empty strings")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        level_quantity = sum(item.quantity for item in self.level_fills)
        level_notional = sum(item.quantity * item.execution_price for item in self.level_fills)
        level_fee = sum(item.fee_quote for item in self.level_fills)
        tolerance = 1e-12
        if (
            abs(level_quantity - self.filled_quantity) > tolerance
            or abs(level_notional - self.notional_quote) > tolerance
            or abs(level_fee - self.fee_quote) > tolerance
        ):
            raise ValueError("simulation receipt totals must equal its immutable level fills")
        if abs(self.filled_quantity + self.cancelled_quantity - self.command.quantity) > tolerance:
            raise ValueError("simulation receipt quantity must be filled or cancelled exactly once")
        if self.filled_quantity == 0:
            if (
                self.status not in {"NO_FILL", "BLOCKED"}
                or self.average_price is not None
                or self.arrival_mid_price is not None
                or self.model_frame_sha256 is not None
                or self.notional_quote != 0
                or self.fee_quote != 0
                or self.implementation_shortfall_quote != 0
                or self.level_fills
            ):
                raise ValueError("a non-fill receipt cannot invent a book frame or economic outcome")
        else:
            if (
                self.model_frame_sha256 is None
                or self.average_price is None
                or self.arrival_mid_price is None
            ):
                raise ValueError("a model fill requires its recorded frame and arrival reference")
            if abs(self.average_price - (self.notional_quote / self.filled_quantity)) > tolerance:
                raise ValueError(
                    "simulation receipt average price must equal model notional per filled quantity"
                )
            if self.status == "FILLED" and abs(self.filled_quantity - self.command.quantity) > tolerance:
                raise ValueError("a FILLED receipt must fill the entire command")
            if self.status == "PARTIAL" and not 0 < self.filled_quantity < self.command.quantity:
                raise ValueError("a PARTIAL receipt must have a strictly partial fill")
            if self.status in {"NO_FILL", "BLOCKED"}:
                raise ValueError("a non-fill status cannot carry model fills")
        expected_id = canonical_sha256(self.identity_payload())
        if self.receipt_id is not None and self.receipt_id != expected_id:
            raise ValueError("receipt_id does not match the canonical simulation command receipt")
        object.__setattr__(self, "receipt_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.arrival_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "alpha_claim": self.alpha_claim,
            "arrival_at_ms": self.arrival_at_ms,
            "arrival_mid_price": self.arrival_mid_price,
            "assumptions_sha256": self.assumptions_sha256,
            "cancelled_quantity": self.cancelled_quantity,
            "command_id": self.command_id,
            "contract_version": self.contract_version,
            "execution_environment": self.execution_environment,
            "fee_quote": self.fee_quote,
            "filled_quantity": self.filled_quantity,
            "implementation_shortfall_quote": self.implementation_shortfall_quote,
            "intent_id": self.intent_id,
            "level_fills": [item.model_dump(mode="json") for item in self.level_fills],
            "model_frame_sha256": self.model_frame_sha256,
            "notional_quote": self.notional_quote,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "reason_codes": self.reason_codes,
            "session_id": self.session_id,
            "status": self.status,
            "trade_id": self.trade_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationTradeEventV2(StrictKairosMessage):
    """Hash-chained simulator lifecycle fact with an explicit state transition."""

    contract_version: Literal["simulation-trade-event.v2"] = "simulation-trade-event.v2"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    event_id: Sha256Hex | None = None
    session_id: Sha256Hex
    admission_id: Sha256Hex
    intent_id: Sha256Hex
    trade_id: Sha256Hex
    event_seq: PositiveInt
    previous_event_sha256: Sha256Hex | None = None
    event_type: SimulationEventType
    from_state: SimulationTradeState | None = None
    to_state: SimulationTradeState
    occurred_at_ms: NonNegativeInt
    symbol: SimulationSymbol
    side: Literal["LONG", "SHORT"]
    command_id: Sha256Hex | None = None
    receipt_id: Sha256Hex | None = None
    filled_quantity: NonNegativeFloat = 0.0
    average_price: PositiveFloat | None = None
    model_frame_sha256: Sha256Hex | None = None
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if (self.event_seq == 1) != (self.previous_event_sha256 is None):
            raise ValueError("the first simulation event has no predecessor; every later event must name one")
        if (self.event_seq == 1) != (self.from_state is None):
            raise ValueError("only the first simulation event may omit a prior lifecycle state")
        root = (self.event_type, self.from_state, self.to_state)
        if self.event_seq == 1 and root != ("ADMITTED", None, "PENDING"):
            raise ValueError("the first simulation event must admit a PENDING trade")
        if self.event_seq > 1 and self.event_type == "ADMITTED":
            raise ValueError("a simulation trade may be admitted only once")
        if self.event_type in {"ENTRY_FILLED", "ENTRY_PARTIAL"} and (
            self.from_state != "PENDING" or self.to_state != "ACTIVE"
        ):
            raise ValueError("entry fills must transition a simulation trade from PENDING to ACTIVE")
        if self.event_type == "ENTRY_NO_FILL" and (self.from_state, self.to_state) != ("PENDING", "NO_FILL"):
            raise ValueError("an entry no-fill must terminate PENDING as NO_FILL")
        if self.event_type in {"STOP_TRIGGERED", "TARGET_TRIGGERED", "TIMEOUT_TRIGGERED", "FLAT"} and (
            self.from_state != "ACTIVE" or self.to_state not in {"FLAT", "UNRESOLVED"}
        ):
            raise ValueError("a simulated exit must transition ACTIVE to FLAT or honest unresolved exposure")
        if self.event_type == "RECOVERED" and self.from_state != self.to_state:
            raise ValueError("a recovery event cannot change simulated lifecycle state")
        if self.event_type in {"NO_ADMITTED_BOOK", "SOURCE_BARRIER", "UNRESOLVED"} and self.to_state not in {
            "BLOCKED",
            "UNRESOLVED",
        }:
            raise ValueError("a simulator source barrier must end BLOCKED or UNRESOLVED")
        if self.event_type == "UNRESOLVED" and self.from_state not in {"PENDING", "ACTIVE"}:
            raise ValueError(
                "an unresolved simulator event must preserve pending or active exposure evidence"
            )
        if any(not code or code != code.strip() or len(code) > 100 for code in self.reason_codes):
            raise ValueError("simulation event reason codes must be normalized non-empty strings")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        requires_fill = self.event_type in {
            "ENTRY_FILLED",
            "ENTRY_PARTIAL",
            "STOP_TRIGGERED",
            "TARGET_TRIGGERED",
            "TIMEOUT_TRIGGERED",
        }
        prohibits_fill = self.event_type in {
            "ADMITTED",
            "ENTRY_NO_FILL",
            "NO_ADMITTED_BOOK",
            "SOURCE_BARRIER",
            "RECOVERED",
            "UNRESOLVED",
        }
        if requires_fill and (
            self.filled_quantity <= 0
            or self.average_price is None
            or self.model_frame_sha256 is None
            or self.command_id is None
            or self.receipt_id is None
        ):
            raise ValueError("a simulated fill event requires a command, receipt, frame, quantity and price")
        if prohibits_fill and (self.filled_quantity != 0 or self.average_price is not None):
            raise ValueError("a non-fill simulation event cannot claim a model fill")
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
            "command_id": self.command_id,
            "contract_version": self.contract_version,
            "event_seq": self.event_seq,
            "event_type": self.event_type,
            "execution_environment": self.execution_environment,
            "filled_quantity": self.filled_quantity,
            "from_state": self.from_state,
            "intent_id": self.intent_id,
            "model_frame_sha256": self.model_frame_sha256,
            "occurred_at_ms": self.occurred_at_ms,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "previous_event_sha256": self.previous_event_sha256,
            "reason_codes": self.reason_codes,
            "receipt_id": self.receipt_id,
            "session_id": self.session_id,
            "side": self.side,
            "symbol": self.symbol,
            "to_state": self.to_state,
            "trade_id": self.trade_id,
            "trial15_eligible": self.trial15_eligible,
        }


class SimulationTradeJournalHeadV1(StrictValueModel):
    """One trade's terminal journal head as included in a session receipt."""

    trade_id: Sha256Hex
    state: SimulationTradeState
    event_count: NonNegativeInt
    journal_head_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_head(self) -> Self:
        if (self.event_count == 0) != (self.journal_head_sha256 is None):
            raise ValueError("an empty trade journal must not claim a head hash")
        return self


class SimulationSessionReceiptV1(StrictKairosMessage):
    """Terminal receipt for an isolated session; it deliberately contains no PnL claim."""

    contract_version: Literal["simulation-session-receipt.v1"] = "simulation-session-receipt.v1"
    execution_environment: Literal["SIMULATED"] = "SIMULATED"
    receipt_id: Sha256Hex | None = None
    session: SimulationSessionV1
    session_id: Sha256Hex | None = None
    tape_id: str | None = None
    tape_sha256: Sha256Hex | None = None
    receipt_state: SimulationSessionReceiptState
    completed_at_ms: NonNegativeInt
    command_count: NonNegativeInt
    trade_journals: tuple[SimulationTradeJournalHeadV1, ...] = Field(default_factory=tuple, max_length=1_024)
    paper_qualification_eligible: Literal[False] = False
    trial15_eligible: Literal[False] = False
    alpha_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_session_receipt(self) -> Self:
        expected_values = {
            "session_id": self.session.session_id,
            "tape_id": self.session.tape_id,
            "tape_sha256": self.session.tape_sha256,
        }
        if any(value is None for value in expected_values.values()):
            raise ValueError("simulation session receipt requires canonical session lineage")
        for field_name, expected in expected_values.items():
            supplied = getattr(self, field_name)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{field_name} does not match the immutable simulation session")
            object.__setattr__(self, field_name, expected)
        if self.completed_at_ms < self.session.started_at_ms:
            raise ValueError("simulation session receipt cannot predate its session")
        journals = tuple(sorted(self.trade_journals, key=lambda item: item.trade_id))
        if len({item.trade_id for item in journals}) != len(journals):
            raise ValueError("simulation session receipt cannot repeat a trade journal")
        if self.receipt_state == "COMPLETED" and any(
            item.state not in {"FLAT", "UNRESOLVED", "NO_FILL", "BLOCKED"} for item in journals
        ):
            raise ValueError("a completed simulation session requires terminal trade journals")
        object.__setattr__(self, "trade_journals", journals)
        expected_id = canonical_sha256(self.identity_payload())
        if self.receipt_id is not None and self.receipt_id != expected_id:
            raise ValueError("receipt_id does not match the canonical simulation session receipt")
        object.__setattr__(self, "receipt_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.completed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "alpha_claim": self.alpha_claim,
            "command_count": self.command_count,
            "completed_at_ms": self.completed_at_ms,
            "contract_version": self.contract_version,
            "execution_environment": self.execution_environment,
            "paper_qualification_eligible": self.paper_qualification_eligible,
            "receipt_state": self.receipt_state,
            "session_id": self.session_id,
            "tape_id": self.tape_id,
            "tape_sha256": self.tape_sha256,
            "trade_journals": [item.model_dump(mode="json") for item in self.trade_journals],
            "trial15_eligible": self.trial15_eligible,
        }

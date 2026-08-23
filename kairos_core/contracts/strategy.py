"""Strict contracts for strategy parity, candidate review, venue gating and risk.

These contracts form the PAPER-only route.  They intentionally do not extend
or reinterpret the legacy ``TacticalCommand -> ValidatedOrder`` route.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from ..enums import (
    CandidateReviewTier,
    EntryPolicy,
    EvedexProfile,
    ReasoningEffort,
    ReviewDecision,
    Side,
    TradingMode,
)
from .base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    canonical_sha256,
    datetime_from_unix_ms,
)

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


def _normalized_identifier(value: str, *, name: str, uppercase: bool = False) -> str:
    expected = value.strip().upper() if uppercase else value.strip()
    if not expected or value != expected:
        qualifier = " uppercase" if uppercase else ""
        raise ValueError(f"{name} must be a non-empty normalized{qualifier} string")
    return value


def _set_default_envelope(message: StrictKairosMessage, *, stable_id: str, timestamp_ms: int) -> None:
    """Make a strict message deterministic when callers omit envelope metadata."""

    if "message_id" not in message.model_fields_set:
        object.__setattr__(message, "message_id", stable_id)
    if "correlation_id" not in message.model_fields_set:
        object.__setattr__(message, "correlation_id", stable_id)
    if "produced_at" not in message.model_fields_set:
        object.__setattr__(message, "produced_at", datetime_from_unix_ms(timestamp_ms))


class ClosedBarEventV1(StrictKairosMessage):
    """One complete, final Binance USD-M one-minute candle."""

    contract_version: Literal["closed-bar.v1"] = "closed-bar.v1"
    venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    symbol: str = Field(..., min_length=2, max_length=32)
    timeframe: Literal["1m"] = "1m"
    open_time_ms: NonNegativeInt
    close_time_ms: PositiveInt
    open: PositiveFloat
    high: PositiveFloat
    low: PositiveFloat
    close: PositiveFloat
    base_volume: NonNegativeFloat
    quote_volume: NonNegativeFloat
    taker_buy_base_volume: NonNegativeFloat
    taker_buy_quote_volume: NonNegativeFloat
    is_closed: Literal[True] = True
    bar_sha256: Sha256Hex | None = None

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_bar(self) -> Self:
        if self.open_time_ms % 60_000 != 0 or self.close_time_ms != self.open_time_ms + 59_999:
            raise ValueError("1m bar timestamps must span exactly [open, open + 59_999ms]")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC geometry requires low <= open/close <= high")
        if self.high < self.low:
            raise ValueError("high cannot be below low")
        if self.taker_buy_base_volume > self.base_volume:
            raise ValueError("taker-buy base volume cannot exceed total base volume")
        if self.taker_buy_quote_volume > self.quote_volume:
            raise ValueError("taker-buy quote volume cannot exceed total quote volume")
        expected_hash = canonical_sha256(self.identity_payload())
        if self.bar_sha256 is not None and self.bar_sha256 != expected_hash:
            raise ValueError("bar_sha256 does not match the canonical closed-bar payload")
        object.__setattr__(self, "bar_sha256", expected_hash)
        _set_default_envelope(self, stable_id=expected_hash, timestamp_ms=self.close_time_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        """Fields covered by ``bar_sha256`` (envelope metadata is excluded)."""

        return {
            "base_volume": self.base_volume,
            "close": self.close,
            "close_time_ms": self.close_time_ms,
            "contract_version": self.contract_version,
            "high": self.high,
            "is_closed": self.is_closed,
            "low": self.low,
            "open": self.open,
            "open_time_ms": self.open_time_ms,
            "quote_volume": self.quote_volume,
            "symbol": self.symbol,
            "taker_buy_base_volume": self.taker_buy_base_volume,
            "taker_buy_quote_volume": self.taker_buy_quote_volume,
            "timeframe": self.timeframe,
            "venue": self.venue,
        }

    def canonical_bar_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())


class ExitPlanV1(StrictValueModel):
    """Immutable v1 lifecycle: one stop, one target and one timeout."""

    plan_version: Literal["stop-target-timeout.v1"] = "stop-target-timeout.v1"
    stop_price: PositiveFloat
    target_price: PositiveFloat
    max_holding_ms: PositiveInt

    @model_validator(mode="after")
    def validate_distinct_barriers(self) -> Self:
        if self.stop_price == self.target_price:
            raise ValueError("stop_price and target_price must differ")
        return self


class StrategyProvenanceV1(StrictValueModel):
    """Fingerprints required to reproduce an intent byte-for-byte."""

    strategy_code_sha256: Sha256Hex
    config_sha256: Sha256Hex
    input_window_sha256: Sha256Hex
    features_sha256: Sha256Hex
    input_bar_sha256s: tuple[Sha256Hex, ...] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_unique_ordered_bars(self) -> Self:
        if len(self.input_bar_sha256s) != len(set(self.input_bar_sha256s)):
            raise ValueError("input_bar_sha256s must not contain duplicates")
        return self


class EvidenceReferenceV1(StrictValueModel):
    """Auditable evidence referenced by a strategy or a review."""

    kind: str = Field(..., min_length=1, max_length=64)
    reference: str = Field(..., min_length=1, max_length=512)
    content_sha256: Sha256Hex | None = None
    observed_at_ms: NonNegativeInt | None = None

    @field_validator("kind", "reference")
    @classmethod
    def validate_normalized_text(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)


class StrategyIntentV1(StrictKairosMessage):
    """A deterministic candidate emitted by a pure strategy generator."""

    contract_version: Literal["strategy-intent.v1"] = "strategy-intent.v1"
    intent_id: Sha256Hex | None = None
    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    symbol: str = Field(..., min_length=2, max_length=32)
    timeframe: Literal["1m"] = "1m"
    venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    side: Side
    decision_ts_ms: NonNegativeInt
    entry_eligible_ts_ms: NonNegativeInt
    entry_expires_ts_ms: NonNegativeInt
    reference_price: PositiveFloat
    signal_strength: float = Field(..., ge=0, le=1)
    gross_reward_bps: PositiveFloat
    exit_plan: ExitPlanV1
    provenance: StrategyProvenanceV1
    evidence: tuple[EvidenceReferenceV1, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    @field_validator("strategy_id", "strategy_revision")
    @classmethod
    def validate_strategy_identifier(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        if self.side is Side.FLAT:
            raise ValueError("a StrategyIntent side must be LONG or SHORT")
        if self.entry_eligible_ts_ms < self.decision_ts_ms:
            raise ValueError("entry cannot become eligible before the decision")
        if self.entry_expires_ts_ms < self.entry_eligible_ts_ms:
            raise ValueError("entry cannot expire before it becomes eligible")
        if self.entry_eligible_ts_ms % 60_000 != 0:
            raise ValueError("NEXT_BAR_MARKET eligibility must start on a one-minute boundary")
        plan = self.exit_plan
        if self.side is Side.LONG and not plan.stop_price < self.reference_price < plan.target_price:
            raise ValueError("LONG exits must satisfy stop < reference < target")
        if self.side is Side.SHORT and not plan.target_price < self.reference_price < plan.stop_price:
            raise ValueError("SHORT exits must satisfy target < reference < stop")
        expected_reward_bps = abs(plan.target_price - self.reference_price) / self.reference_price * 10_000
        if not math.isclose(self.gross_reward_bps, expected_reward_bps, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("gross_reward_bps must equal the reference-to-target distance")
        canonical_metadata = self._canonical_metadata()
        object.__setattr__(self, "metadata", canonical_metadata)
        canonical_evidence = tuple(sorted(self.evidence, key=lambda item: canonical_json_bytes(item)))
        object.__setattr__(self, "evidence", canonical_evidence)
        expected_id = canonical_sha256(self.identity_payload())
        if self.intent_id is not None and self.intent_id != expected_id:
            raise ValueError("intent_id does not match the canonical strategy payload")
        object.__setattr__(self, "intent_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.decision_ts_ms)
        return self

    def _canonical_metadata(self) -> tuple[tuple[str, str], ...]:
        pairs: list[tuple[str, str]] = []
        for key, value in self.metadata:
            if not key or key != key.strip() or value != value.strip():
                raise ValueError("metadata keys and values must be normalized strings")
            pairs.append((key, value))
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("metadata keys must be unique")
        return tuple(sorted(pairs))

    def identity_payload(self) -> dict[str, object]:
        """Canonical identity, including all reproducibility fingerprints."""

        return {
            "contract_version": self.contract_version,
            "decision_ts_ms": self.decision_ts_ms,
            "entry_eligible_ts_ms": self.entry_eligible_ts_ms,
            "entry_expires_ts_ms": self.entry_expires_ts_ms,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "exit_plan": self.exit_plan.model_dump(mode="json"),
            "gross_reward_bps": self.gross_reward_bps,
            "metadata": self.metadata,
            "provenance": self.provenance.model_dump(mode="json"),
            "reference_price": self.reference_price,
            "side": self.side.value,
            "signal_strength": self.signal_strength,
            "strategy_id": self.strategy_id,
            "strategy_revision": self.strategy_revision,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "venue": self.venue,
        }

    def canonical_intent_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())


class ModelProvenanceV1(StrictValueModel):
    """Exact paid-model call that produced a candidate review."""

    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    request_id: str = Field(..., min_length=1, max_length=256)
    prompt_sha256: Sha256Hex
    response_sha256: Sha256Hex
    budget_reservation_id: str = Field(..., min_length=1, max_length=128)
    latency_ms: NonNegativeInt
    cost_usd: NonNegativeFloat

    @field_validator("provider", "model", "request_id", "budget_reservation_id")
    @classmethod
    def validate_identifiers(cls, value: str, info) -> str:
        return _normalized_identifier(value, name=info.field_name)


class CandidateRouteV1(StrictKairosMessage):
    """Candidate-specific Router output; it never invents a trading direction."""

    contract_version: Literal["candidate-route.v1"] = "candidate-route.v1"
    route_id: Sha256Hex | None = None
    intent: StrategyIntentV1
    intent_sha256: Sha256Hex | None = None
    review_tier: CandidateReviewTier
    requested_reasoning_effort: ReasoningEffort
    routed_at_ms: NonNegativeInt
    review_deadline_ms: NonNegativeInt
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    conflict_rationale: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        intent_hash = self.intent.intent_id
        if intent_hash is None:  # impossible after StrategyIntent validation
            raise ValueError("route intent has no canonical identity")
        if self.intent_sha256 is not None and self.intent_sha256 != intent_hash:
            raise ValueError("intent_sha256 does not match the immutable route intent")
        object.__setattr__(self, "intent_sha256", intent_hash)
        if self.routed_at_ms < self.intent.decision_ts_ms:
            raise ValueError("route cannot predate its intent")
        if not self.routed_at_ms <= self.review_deadline_ms <= self.intent.entry_expires_ts_ms:
            raise ValueError("review deadline must lie between routing and entry expiry")
        if any(not item or item != item.strip() or len(item) > 128 for item in self.evidence_ids):
            raise ValueError("evidence_ids must be normalized strings no longer than 128 characters")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        if self.review_tier is CandidateReviewTier.NORMAL:
            if self.requested_reasoning_effort is not ReasoningEffort.MEDIUM:
                raise ValueError("NORMAL candidates require medium reasoning effort")
            if self.conflict_rationale is not None:
                raise ValueError("NORMAL candidates cannot contain a conflict rationale")
        else:
            if self.requested_reasoning_effort is not ReasoningEffort.HIGH:
                raise ValueError("CONFLICT candidates require high reasoning effort")
            if (
                self.conflict_rationale is None
                or not self.conflict_rationale.strip()
                or self.conflict_rationale != self.conflict_rationale.strip()
            ):
                raise ValueError("CONFLICT candidates require a normalized conflict rationale")
        expected_route_id = canonical_sha256(self.identity_payload())
        if self.route_id is not None and self.route_id != expected_route_id:
            raise ValueError("route_id does not match the canonical candidate route")
        object.__setattr__(self, "route_id", expected_route_id)
        _set_default_envelope(self, stable_id=expected_route_id, timestamp_ms=self.routed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "conflict_rationale": self.conflict_rationale,
            "contract_version": self.contract_version,
            "evidence_ids": self.evidence_ids,
            "intent_id": self.intent.intent_id,
            "requested_reasoning_effort": self.requested_reasoning_effort.value,
            "review_deadline_ms": self.review_deadline_ms,
            "review_tier": self.review_tier.value,
            "routed_at_ms": self.routed_at_ms,
        }


class CandidateReviewV1(StrictKairosMessage):
    """ALLOW/VETO/DEFER overlay that cannot mutate the candidate."""

    contract_version: Literal["candidate-review.v1"] = "candidate-review.v1"
    review_id: Sha256Hex | None = None
    route: CandidateRouteV1
    intent: StrategyIntentV1
    intent_sha256: Sha256Hex | None = None
    decision: ReviewDecision
    priority: int = Field(default=0, ge=0, le=100)
    reviewed_at_ms: NonNegativeInt
    reviewer: Literal["LLM", "DETERMINISTIC"]
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, min_length=1)
    evidence: tuple[EvidenceReferenceV1, ...] = ()
    model_provenance: ModelProvenanceV1 | None = None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.route.intent.intent_id != self.intent.intent_id:
            raise ValueError("review route and intent must carry the same immutable candidate")
        if self.reviewer == "LLM" and self.model_provenance is None:
            raise ValueError("LLM reviews require model_provenance")
        if self.reviewer == "DETERMINISTIC" and self.model_provenance is not None:
            raise ValueError("deterministic reviews cannot claim model_provenance")
        if self.reviewed_at_ms < self.intent.decision_ts_ms:
            raise ValueError("review cannot predate its intent")
        if not self.route.routed_at_ms <= self.reviewed_at_ms <= self.route.review_deadline_ms:
            raise ValueError("review must complete between routing and the route deadline")
        if any(not code or code != code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain normalized non-empty strings")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: canonical_json_bytes(item))),
        )
        expected_intent_hash = self.intent.intent_id
        if expected_intent_hash is None:  # impossible after StrategyIntent validation
            raise ValueError("review intent has no canonical identity")
        if self.intent_sha256 is not None and self.intent_sha256 != expected_intent_hash:
            raise ValueError("intent_sha256 does not match the immutable intent")
        object.__setattr__(self, "intent_sha256", expected_intent_hash)
        expected_review_id = canonical_sha256(self.identity_payload())
        if self.review_id is not None and self.review_id != expected_review_id:
            raise ValueError("review_id does not match the canonical review payload")
        object.__setattr__(self, "review_id", expected_review_id)
        _set_default_envelope(self, stable_id=expected_review_id, timestamp_ms=self.reviewed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "decision": self.decision.value,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "intent_id": self.intent.intent_id,
            "model_provenance": (
                self.model_provenance.model_dump(mode="json") if self.model_provenance else None
            ),
            "priority": self.priority,
            "reason_codes": self.reason_codes,
            "route_id": self.route.route_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "reviewer": self.reviewer,
        }


class VenueQualityV1(StrictKairosMessage):
    """Fresh EVEDEX executable-quality comparison against the Binance signal."""

    contract_version: Literal["venue-quality.v1"] = "venue-quality.v1"
    measurement_id: Sha256Hex | None = None
    reference_venue: Literal["BINANCE_UM"] = "BINANCE_UM"
    venue: Literal["EVEDEX"] = "EVEDEX"
    profile: EvedexProfile
    symbol: str = Field(..., min_length=2, max_length=64)
    observed_at_ms: NonNegativeInt
    expires_at_ms: NonNegativeInt
    reference_timestamp_ms: NonNegativeInt
    book_timestamp_ms: NonNegativeInt
    reference_mid_price: PositiveFloat
    best_bid: PositiveFloat
    best_ask: PositiveFloat
    venue_mid_price: PositiveFloat
    basis_bps: float
    spread_bps: NonNegativeFloat
    assessed_notional_usd: PositiveFloat
    depth_usd: NonNegativeFloat
    buy_slippage_bps: NonNegativeFloat
    sell_slippage_bps: NonNegativeFloat
    taker_fee_bps: NonNegativeFloat
    reference_age_ms: NonNegativeInt
    book_age_ms: NonNegativeInt
    latency_ms: NonNegativeInt
    timestamp_skew_ms: NonNegativeInt
    entry_allowed: bool
    reason_codes: tuple[str, ...] = ()

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_measurement(self) -> Self:
        if self.expires_at_ms < self.observed_at_ms:
            raise ValueError("venue quality cannot expire before it is observed")
        if self.reference_timestamp_ms > self.observed_at_ms or self.book_timestamp_ms > self.observed_at_ms:
            raise ValueError("venue/reference timestamps cannot be later than observation time")
        if self.reference_age_ms != self.observed_at_ms - self.reference_timestamp_ms:
            raise ValueError("reference_age_ms must match the observation/reference timestamps")
        if self.book_age_ms != self.observed_at_ms - self.book_timestamp_ms:
            raise ValueError("book_age_ms must match the observation/book timestamps")
        if self.timestamp_skew_ms != abs(self.reference_timestamp_ms - self.book_timestamp_ms):
            raise ValueError("timestamp_skew_ms must match reference/book timestamps")
        if self.best_ask <= self.best_bid:
            raise ValueError("EVEDEX best_ask must be above best_bid")
        calculated_mid = (self.best_bid + self.best_ask) / 2
        if not math.isclose(self.venue_mid_price, calculated_mid, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("venue_mid_price must be the midpoint of best bid and ask")
        calculated_basis = (
            (self.venue_mid_price - self.reference_mid_price) / self.reference_mid_price * 10_000
        )
        if not math.isclose(self.basis_bps, calculated_basis, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("basis_bps must match reference and venue mid prices")
        calculated_spread = (self.best_ask - self.best_bid) / self.venue_mid_price * 10_000
        if not math.isclose(self.spread_bps, calculated_spread, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("spread_bps must match EVEDEX best bid and ask")
        if any(not code or code != code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain normalized non-empty strings")
        canonical_reasons = tuple(sorted(set(self.reason_codes)))
        if not self.entry_allowed and not canonical_reasons:
            raise ValueError("a blocked venue measurement requires at least one reason code")
        if self.entry_allowed and self.depth_usd < self.assessed_notional_usd:
            raise ValueError("entry cannot be allowed when executable depth is below assessed notional")
        object.__setattr__(self, "reason_codes", canonical_reasons)
        expected_id = canonical_sha256(self.identity_payload())
        if self.measurement_id is not None and self.measurement_id != expected_id:
            raise ValueError("measurement_id does not match canonical venue data")
        object.__setattr__(self, "measurement_id", expected_id)
        _set_default_envelope(self, stable_id=expected_id, timestamp_ms=self.observed_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "basis_bps": self.basis_bps,
            "best_ask": self.best_ask,
            "best_bid": self.best_bid,
            "book_age_ms": self.book_age_ms,
            "book_timestamp_ms": self.book_timestamp_ms,
            "buy_slippage_bps": self.buy_slippage_bps,
            "contract_version": self.contract_version,
            "depth_usd": self.depth_usd,
            "entry_allowed": self.entry_allowed,
            "expires_at_ms": self.expires_at_ms,
            "latency_ms": self.latency_ms,
            "observed_at_ms": self.observed_at_ms,
            "profile": self.profile.value,
            "reference_age_ms": self.reference_age_ms,
            "reason_codes": self.reason_codes,
            "reference_mid_price": self.reference_mid_price,
            "reference_timestamp_ms": self.reference_timestamp_ms,
            "reference_venue": self.reference_venue,
            "assessed_notional_usd": self.assessed_notional_usd,
            "sell_slippage_bps": self.sell_slippage_bps,
            "spread_bps": self.spread_bps,
            "symbol": self.symbol,
            "taker_fee_bps": self.taker_fee_bps,
            "timestamp_skew_ms": self.timestamp_skew_ms,
            "venue": self.venue,
            "venue_mid_price": self.venue_mid_price,
        }


class RiskTradeDecisionV1(StrictKairosMessage):
    """Final deterministic sizing decision consumed by the PAPER execution FSM."""

    contract_version: Literal["risk-trade-decision.v1"] = "risk-trade-decision.v1"
    decision_id: Sha256Hex | None = None
    trade_id: Sha256Hex | None = None
    intent: StrategyIntentV1
    review: CandidateReviewV1
    venue_quality: VenueQualityV1
    approved: bool
    rejection_reasons: tuple[str, ...] = ()
    decided_at_ms: NonNegativeInt
    entry_policy: Literal[EntryPolicy.NEXT_BAR_MARKET] = EntryPolicy.NEXT_BAR_MARKET
    trading_mode: TradingMode
    evedex_profile: EvedexProfile
    account_id: str = Field(..., min_length=1, max_length=128)
    venue_symbol: str = Field(..., min_length=2, max_length=64)
    quantity: NonNegativeFloat
    leverage: float = Field(..., ge=1, le=125)
    notional_usd: NonNegativeFloat
    loss_budget_usd: NonNegativeFloat
    worst_case_loss_usd: NonNegativeFloat
    worst_entry_price: PositiveFloat
    estimated_fees_usd: NonNegativeFloat
    estimated_slippage_usd: NonNegativeFloat
    exit_plan: ExitPlanV1

    @field_validator("account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        return _normalized_identifier(value, name="account_id")

    @field_validator("venue_symbol")
    @classmethod
    def validate_venue_symbol(cls, value: str) -> str:
        return _normalized_identifier(value, name="venue_symbol", uppercase=True)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.review.intent.intent_id != self.intent.intent_id:
            raise ValueError("review and risk decision must reference the same immutable intent")
        if self.exit_plan != self.intent.exit_plan:
            raise ValueError("RiskTradeDecision exit_plan must be unchanged from StrategyIntent")
        if self.venue_quality.profile is not self.evedex_profile:
            raise ValueError("venue profile does not match the risk decision environment")
        if self.venue_quality.symbol != self.venue_symbol:
            raise ValueError("venue quality symbol does not match the risk decision")
        if self.decided_at_ms < self.review.reviewed_at_ms:
            raise ValueError("risk decision cannot predate candidate review")
        if self.decided_at_ms > self.venue_quality.expires_at_ms and self.approved:
            raise ValueError("stale venue quality cannot support an approved decision")
        if self.decided_at_ms > self.intent.entry_expires_ts_ms and self.approved:
            raise ValueError("an expired candidate cannot be approved")
        if self.trading_mode is TradingMode.PAPER:
            if self.evedex_profile is not EvedexProfile.DEV or not self.venue_symbol.endswith(":DEV"):
                raise ValueError("PAPER decisions require the exact EVEDEX DEV profile and :DEV symbol")
        if self.trading_mode is TradingMode.LIVE and self.evedex_profile is not EvedexProfile.PROD:
            raise ValueError("LIVE decisions require the EVEDEX PROD profile")
        canonical_reasons = tuple(sorted(set(self.rejection_reasons)))
        if any(not reason or reason != reason.strip() for reason in canonical_reasons):
            raise ValueError("rejection_reasons must contain normalized non-empty strings")
        object.__setattr__(self, "rejection_reasons", canonical_reasons)
        if self.approved:
            if self.review.decision is not ReviewDecision.ALLOW:
                raise ValueError("only an ALLOW review can be risk-approved")
            if not self.venue_quality.entry_allowed:
                raise ValueError("risk cannot approve a blocked venue")
            if canonical_reasons:
                raise ValueError("approved decisions cannot contain rejection reasons")
            if self.quantity <= 0 or self.loss_budget_usd <= 0 or self.worst_case_loss_usd <= 0:
                raise ValueError("approved decisions require positive quantity and loss economics")
        elif not canonical_reasons:
            raise ValueError("rejected decisions require at least one rejection reason")
        expected_notional = self.quantity * self.worst_entry_price
        if not math.isclose(self.notional_usd, expected_notional, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("notional_usd must equal quantity * worst_entry_price")
        expected_worst_entry = (
            self.venue_quality.best_ask if self.intent.side is Side.LONG else self.venue_quality.best_bid
        )
        if not math.isclose(self.worst_entry_price, expected_worst_entry, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("worst_entry_price must use the executable EVEDEX top of book")
        side_slippage_bps = (
            self.venue_quality.buy_slippage_bps
            if self.intent.side is Side.LONG
            else self.venue_quality.sell_slippage_bps
        )
        expected_slippage = self.quantity * self.venue_quality.venue_mid_price * side_slippage_bps / 10_000
        if not math.isclose(
            self.estimated_slippage_usd,
            expected_slippage,
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            raise ValueError("estimated_slippage_usd must use the measured side-specific slippage")
        expected_fees = (
            self.quantity
            * (self.worst_entry_price + self.exit_plan.stop_price)
            * self.venue_quality.taker_fee_bps
            / 10_000
        )
        if not math.isclose(self.estimated_fees_usd, expected_fees, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("estimated_fees_usd must conservatively fee entry and stop exit")
        if self.approved and self.notional_usd > self.venue_quality.assessed_notional_usd + 1e-6:
            raise ValueError("approved notional cannot exceed the venue-assessed notional")
        expected_loss = (
            self.quantity * abs(self.worst_entry_price - self.exit_plan.stop_price)
            + self.estimated_fees_usd
            + self.estimated_slippage_usd
        )
        if not math.isclose(self.worst_case_loss_usd, expected_loss, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("worst_case_loss_usd must include stop distance, fees and slippage")
        if self.worst_case_loss_usd > self.loss_budget_usd + 1e-6:
            raise ValueError("worst_case_loss_usd cannot exceed loss_budget_usd")
        if (
            self.approved
            and self.intent.side is Side.LONG
            and not (self.exit_plan.stop_price < self.worst_entry_price < self.exit_plan.target_price)
        ):
            raise ValueError("LONG worst entry must remain between immutable stop and target")
        if (
            self.approved
            and self.intent.side is Side.SHORT
            and not (self.exit_plan.target_price < self.worst_entry_price < self.exit_plan.stop_price)
        ):
            raise ValueError("SHORT worst entry must remain between immutable target and stop")
        trade_payload = {
            "account_id": self.account_id,
            "evedex_profile": self.evedex_profile.value,
            "intent_id": self.intent.intent_id,
            "trading_mode": self.trading_mode.value,
            "venue_symbol": self.venue_symbol,
        }
        expected_trade_id = canonical_sha256(trade_payload)
        if self.trade_id is not None and self.trade_id != expected_trade_id:
            raise ValueError("trade_id does not match intent/environment/account lineage")
        object.__setattr__(self, "trade_id", expected_trade_id)
        expected_decision_id = canonical_sha256(self.identity_payload())
        if self.decision_id is not None and self.decision_id != expected_decision_id:
            raise ValueError("decision_id does not match the canonical risk decision")
        object.__setattr__(self, "decision_id", expected_decision_id)
        _set_default_envelope(self, stable_id=expected_decision_id, timestamp_ms=self.decided_at_ms)
        return self

    def identity_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "approved": self.approved,
            "contract_version": self.contract_version,
            "decided_at_ms": self.decided_at_ms,
            "entry_policy": self.entry_policy.value,
            "estimated_fees_usd": self.estimated_fees_usd,
            "estimated_slippage_usd": self.estimated_slippage_usd,
            "evedex_profile": self.evedex_profile.value,
            "exit_plan": self.exit_plan.model_dump(mode="json"),
            "intent_id": self.intent.intent_id,
            "leverage": self.leverage,
            "loss_budget_usd": self.loss_budget_usd,
            "notional_usd": self.notional_usd,
            "quantity": self.quantity,
            "rejection_reasons": self.rejection_reasons,
            "review_id": self.review.review_id,
            "trade_id": self.trade_id,
            "trading_mode": self.trading_mode.value,
            "venue_measurement_id": self.venue_quality.measurement_id,
            "venue_symbol": self.venue_symbol,
            "worst_case_loss_usd": self.worst_case_loss_usd,
            "worst_entry_price": self.worst_entry_price,
        }

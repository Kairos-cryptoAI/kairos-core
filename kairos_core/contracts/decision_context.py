"""Receive-time causal context for candidate review, not trading authority.

Legacy source contracts contain mutable dicts/lists. Their exact canonical JSON
is stored as a string here, so a frozen context is deeply immutable as well as
content-addressed. Decoding returns fresh objects, never references to a cache.
Availability is a local receiver observation, not an archive/PIT attestation.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from ..topics import Topics
from .base import (
    KairosMessage,
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    canonical_sha256,
    datetime_from_unix_ms,
)
from .market import MarketSnapshot
from .sentiment import SentimentSignal
from .strategic import StrategicAllocation
from .strategy import CandidateRouteV1, ClosedBarEventV1, EvidenceReferenceV1, StrategyIntentV1

ContextSourceKind = Literal["market", "closed_bars", "text", "macro"]
ContextAvailability = Literal["AVAILABLE", "UNAVAILABLE"]
_Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_Clock = Annotated[StrictInt, Field(ge=0)]
_SOURCE_MODELS: dict[ContextSourceKind, type[KairosMessage]] = {
    "market": MarketSnapshot,
    "closed_bars": ClosedBarEventV1,
    "text": SentimentSignal,
    "macro": StrategicAllocation,
}


class DecisionContextReceiptV1(StrictValueModel):
    """Exact source message and the first trusted local receipt clock."""

    message_id: StrictStr = Field(min_length=1, max_length=128)
    source: StrictStr = Field(min_length=1)
    topic: StrictStr = Field(min_length=1)
    content_sha256: _Sha256
    event_at_ms: _Clock
    produced_at_ms: _Clock
    received_at_ms: _Clock
    ttl_ms: Annotated[StrictInt, Field(gt=0)]

    @field_validator("message_id", "source", "topic")
    @classmethod
    def normalized_strings(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("receipt identifiers must be non-empty normalized strings")
        return value


class DecisionContextSourceV1(StrictValueModel):
    """Explicit availability plus exact, canonical, typed source payloads."""

    kind: ContextSourceKind
    availability: ContextAvailability
    reason_code: StrictStr | None = None
    receipts: tuple[DecisionContextReceiptV1, ...] = ()
    payloads_json: StrictStr | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.availability == "UNAVAILABLE":
            if not self.reason_code or self.receipts or self.payloads_json is not None:
                raise ValueError("UNAVAILABLE source needs a reason and cannot carry invented evidence")
            return self
        if self.reason_code is not None or not self.receipts or self.payloads_json is None:
            raise ValueError("AVAILABLE source requires exact payloads and receipts, not a reason")
        data = json.loads(self.payloads_json)
        if not isinstance(data, dict) or set(data) != {"items"} or not isinstance(data["items"], list):
            raise ValueError("context payload must contain exactly one items array")
        if canonical_json_bytes(data).decode("utf-8") != self.payloads_json:
            raise ValueError("source payloads must use canonical JSON")
        if len(data["items"]) != len(self.receipts):
            raise ValueError("every source payload requires its exact receipt")
        if self.kind in {"market", "macro"} and len(self.receipts) != 1:
            raise ValueError("market and macro slots contain exactly one snapshot")
        model = _SOURCE_MODELS[self.kind]
        seen: set[str] = set()
        for raw, receipt in zip(data["items"], self.receipts, strict=True):
            message = model.model_validate(raw)
            # Legacy models ignore extras; they must not be silently discarded.
            if canonical_json_bytes(message) != canonical_json_bytes(raw):
                raise ValueError("context cannot reinterpret unknown or noncanonical source fields")
            if message.produced_at.utcoffset() is None:
                raise ValueError("context source requires an aware producer timestamp")
            produced = int(message.produced_at.timestamp() * 1_000)
            event = message.close_time_ms if isinstance(message, ClosedBarEventV1) else produced
            expected_topic = {
                "market": Topics.MARKET_SNAPSHOT,
                "closed_bars": Topics.CLOSED_BAR,
                "text": Topics.SENTIMENT_SIGNAL,
                "macro": Topics.STRATEGIC_ALLOCATION,
            }[self.kind]
            if (
                receipt.message_id != message.message_id
                or receipt.source != message.source
                or receipt.topic != expected_topic
                or receipt.content_sha256 != canonical_sha256(raw)
                or receipt.produced_at_ms != produced
                or receipt.event_at_ms != event
            ):
                raise ValueError("source receipt does not match its exact payload")
            if (
                isinstance(message, MarketSnapshot)
                and message.order_book.best_ask < message.order_book.best_bid
            ):
                raise ValueError("context market book is crossed")
            if isinstance(message, StrategicAllocation) and any(
                weight < 0 for weight in message.strategy_weights.values()
            ):
                raise ValueError("context allocation contains negative weights")
            if event > produced:
                raise ValueError("a closed event cannot be produced before it exists")
            if receipt.message_id in seen:
                raise ValueError("context cannot repeat a source identity")
            seen.add(receipt.message_id)
        return self

    def payloads(self) -> tuple[dict, ...]:
        """Decode new objects; mutation cannot change the frozen stored bytes."""
        return tuple(json.loads(self.payloads_json)["items"]) if self.payloads_json is not None else ()


class DecisionContextV1(StrictKairosMessage):
    """One fixed route/source cut; UNKNOWN is never represented as neutral.

    Closed bars are a bounded exact tail of the intent's declared input hashes.
    Neither market features nor that tail claim to reconstruct the full window.
    """

    contract_version: Literal["decision-context.v1"] = "decision-context.v1"
    context_id: _Sha256 | None = None
    authority: Literal["review_only"] = "review_only"
    route_id: _Sha256
    intent_id: _Sha256
    route_identity_json: StrictStr
    intent_identity_json: StrictStr
    symbol: StrictStr
    event_as_of_ms: _Clock
    knowledge_cutoff_ms: _Clock
    captured_at_ms: _Clock
    review_deadline_ms: _Clock
    closed_bar_scope: Literal["DECLARED_INPUT_TAIL"] = "DECLARED_INPUT_TAIL"
    maximum_closed_bars: Annotated[StrictInt, Field(ge=1, le=1_440)]
    required_sources: tuple[ContextSourceKind, ...]
    sources: tuple[DecisionContextSourceV1, ...]

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        for payload, expected in (
            (self.route_identity_json, self.route_id),
            (self.intent_identity_json, self.intent_id),
        ):
            data = json.loads(payload)
            if canonical_json_bytes(data).decode("utf-8") != payload or canonical_sha256(data) != expected:
                raise ValueError("context intent/route identity must be exact canonical JSON")
        intent = json.loads(self.intent_identity_json)
        route = json.loads(self.route_identity_json)
        if not isinstance(intent, dict) or not isinstance(route, dict):
            raise ValueError("context identity payloads must be objects")
        parsed_intent = StrategyIntentV1.model_validate({"source": "context-validation", **intent})
        route_fields = {key: value for key, value in route.items() if key != "intent_id"}
        parsed_route = CandidateRouteV1.model_validate(
            {"source": "context-validation", "intent": parsed_intent, **route_fields}
        )
        if parsed_intent.intent_id != self.intent_id or parsed_route.route_id != self.route_id:
            raise ValueError("context identity payloads must be complete valid intent/route contracts")
        if (
            intent["symbol"] != self.symbol
            or route["intent_id"] != self.intent_id
            or route["routed_at_ms"] != self.event_as_of_ms
            or route["review_deadline_ms"] != self.review_deadline_ms
        ):
            raise ValueError("context scope differs from its immutable intent/route")
        if not self.event_as_of_ms <= self.knowledge_cutoff_ms <= self.captured_at_ms:
            raise ValueError("context cannot anticipate routing or source receipt")
        if self.captured_at_ms > self.review_deadline_ms:
            raise ValueError("context capture exceeded the fixed review deadline")
        if "produced_at" not in self.model_fields_set:
            object.__setattr__(self, "produced_at", datetime_from_unix_ms(self.captured_at_ms))
        if (
            self.produced_at.utcoffset() is None
            or int(self.produced_at.timestamp() * 1_000) != self.captured_at_ms
        ):
            raise ValueError("context producer timestamp must be its exact local capture clock")
        kinds = tuple(source.kind for source in self.sources)
        if len(set(kinds)) != 4 or set(kinds) != {"market", "closed_bars", "text", "macro"}:
            raise ValueError("context must explicitly account for all four source slots")
        if len(set(self.required_sources)) != len(self.required_sources) or not {
            "market",
            "closed_bars",
        }.issubset(self.required_sources):
            raise ValueError("market and exact closed-bar evidence are always mandatory")
        text = next(source for source in self.sources if source.kind == "text")
        if route["evidence_ids"]:
            if "text" not in self.required_sources:
                raise ValueError("exact routed text is mandatory when the route references it")
            if text.availability == "AVAILABLE" and sorted(x.message_id for x in text.receipts) != sorted(
                route["evidence_ids"]
            ):
                raise ValueError("context text must exactly match the route evidence IDs")
        elif text.availability == "AVAILABLE":
            raise ValueError("context cannot add unreferenced text to an immutable route")
        for source in self.sources:
            for receipt in source.receipts:
                if (
                    receipt.event_at_ms > self.event_as_of_ms
                    or receipt.produced_at_ms > self.knowledge_cutoff_ms
                ):
                    raise ValueError("source event/production postdates the fixed context cut")
                if receipt.received_at_ms > self.knowledge_cutoff_ms:
                    raise ValueError("backdated source was not available at the fixed receipt cut")
                if receipt.produced_at_ms > receipt.received_at_ms:
                    raise ValueError("source producer timestamp was in the future when received")
                if receipt.event_at_ms > receipt.received_at_ms:
                    raise ValueError("source event was in the future when received")
                if self.captured_at_ms - receipt.event_at_ms > receipt.ttl_ms:
                    raise ValueError("source is stale at context capture")
            payloads = source.payloads()
            if source.kind == "market" and payloads:
                if payloads[0]["symbol"] != self.symbol:
                    raise ValueError("market source symbol differs from the candidate")
            if source.kind == "text" and payloads:
                for text_payload in payloads:
                    topic = text_payload["topic"].strip().upper()
                    if topic.isalnum() and topic.endswith("USDT") and text_payload["topic"] != self.symbol:
                        raise ValueError("explicit text pair topic differs from the candidate symbol")
            if source.kind == "closed_bars" and payloads:
                expected = intent["provenance"]["input_bar_sha256s"][-self.maximum_closed_bars :]
                if [bar["bar_sha256"] for bar in payloads] != expected:
                    raise ValueError("closed bars are not the exact declared input tail")
                if any(bar["symbol"] != self.symbol or bar["venue"] != intent["venue"] for bar in payloads):
                    raise ValueError("closed bar scope differs from the candidate")
                if intent["contract_version"] == "strategy-intent.observed-sim.v2":
                    confirmation_close = int(dict(intent["metadata"])["confirmation_bar_close_ms"])
                    if payloads[-1]["close_time_ms"] != confirmation_close:
                        raise ValueError(
                            "observed SIM closed bars must end at the immutable confirmation bar"
                        )
                elif payloads[-1]["close_time_ms"] != intent["decision_ts_ms"]:
                    raise ValueError("closed-bar evidence must end at the exact strategy decision bar")
                if any(
                    b["open_time_ms"] != a["open_time_ms"] + 60_000
                    for a, b in zip(payloads, payloads[1:], strict=False)
                ):
                    raise ValueError("closed-bar evidence tail contains a gap/reorder")
        identity = self.identity_payload()
        expected_context = canonical_sha256(identity)
        if self.context_id is not None and self.context_id != expected_context:
            raise ValueError("decision context content identity was reused")
        object.__setattr__(self, "context_id", expected_context)
        if "message_id" not in self.model_fields_set:
            object.__setattr__(self, "message_id", expected_context)
        return self

    def identity_payload(self) -> dict:
        excluded = {"context_id", "message_id", "correlation_id", "causation_id", "produced_at", "source"}
        return self.model_dump(mode="json", exclude=excluded)

    def validate_for_route(self, route: CandidateRouteV1) -> None:
        if (
            self.route_id != route.route_id
            or self.intent_id != route.intent.intent_id
            or self.route_identity_json != canonical_json_bytes(route.identity_payload()).decode("utf-8")
            or self.intent_identity_json != route.intent.canonical_intent_bytes().decode("utf-8")
        ):
            raise ValueError("decision context does not belong to this exact route and intent")

    def missing_required_sources(self) -> tuple[DecisionContextSourceV1, ...]:
        return tuple(
            source
            for source in self.sources
            if source.kind in self.required_sources and source.availability != "AVAILABLE"
        )

    def evidence_references(self) -> tuple[EvidenceReferenceV1, ...]:
        if self.context_id is None:  # impossible for a validated context
            raise ValueError("decision context has no canonical identity")
        return (
            EvidenceReferenceV1(
                kind="decision_context",
                reference=self.context_id,
                content_sha256=canonical_sha256(self),
                observed_at_ms=self.captured_at_ms,
            ),
        )


__all__ = [
    "ContextSourceKind",
    "ContextAvailability",
    "DecisionContextReceiptV1",
    "DecisionContextSourceV1",
    "DecisionContextV1",
]

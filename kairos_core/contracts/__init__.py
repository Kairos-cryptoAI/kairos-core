"""Typed, versioned messages exchanged on the Kairos bus."""

from __future__ import annotations

from .account import AccountSnapshot, PositionSnapshot
from .base import SCHEMA_VERSION, KairosMessage, canonical_json_bytes, canonical_sha256
from .execution import ExecutionReport, OrderIntent, ValidatedOrder
from .health import LLMHealthEvent
from .market import (
    DerivativesMetrics,
    MarketSnapshot,
    OrderBookSummary,
    TechnicalIndicators,
)
from .paper import AccountSnapshotV2, OpenOrderSnapshotV2, PositionSnapshotV2, TradeExecutionEventV1
from .routing import RouterDecision
from .sentiment import SentimentSignal
from .simulation import (
    RecordedBookLevelV1,
    RecordedTopNBookFrameV1,
    SimulationAdmissionV1,
    SimulationAssumptionsV1,
    SimulationResultV1,
    SimulationSessionV1,
    SimulationStrategyRefV1,
    SimulationTradeEventV1,
)
from .strategic import StrategicAllocation
from .strategy import (
    CandidateReviewV1,
    CandidateRouteV1,
    ClosedBarEventV1,
    EvidenceReferenceV1,
    ExitPlanV1,
    ModelProvenanceV1,
    RiskTradeDecisionV1,
    StrategyIntentV1,
    StrategyProvenanceV1,
    VenueQualityV1,
)
from .tactical import GridAdjustment, TacticalCommand

__all__ = [
    "AccountSnapshot",
    "PositionSnapshot",
    "KairosMessage",
    "SCHEMA_VERSION",
    "canonical_json_bytes",
    "canonical_sha256",
    "MarketSnapshot",
    "OrderBookSummary",
    "DerivativesMetrics",
    "TechnicalIndicators",
    "SentimentSignal",
    "RouterDecision",
    "TacticalCommand",
    "GridAdjustment",
    "StrategicAllocation",
    "OrderIntent",
    "ValidatedOrder",
    "ExecutionReport",
    "LLMHealthEvent",
    "ClosedBarEventV1",
    "ExitPlanV1",
    "StrategyProvenanceV1",
    "EvidenceReferenceV1",
    "StrategyIntentV1",
    "CandidateRouteV1",
    "ModelProvenanceV1",
    "CandidateReviewV1",
    "VenueQualityV1",
    "RiskTradeDecisionV1",
    "TradeExecutionEventV1",
    "PositionSnapshotV2",
    "OpenOrderSnapshotV2",
    "AccountSnapshotV2",
    "RecordedBookLevelV1",
    "RecordedTopNBookFrameV1",
    "SimulationAssumptionsV1",
    "SimulationStrategyRefV1",
    "SimulationSessionV1",
    "SimulationAdmissionV1",
    "SimulationTradeEventV1",
    "SimulationResultV1",
]

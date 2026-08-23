# kairos-core

> Shared contracts, message bus, config and structured logging for the **Kairos** AI
> futures trader.

`kairos-core` is the keystone library that every Kairos service depends on. It defines
the *only* vocabulary the layers use to talk to each other, so that the "compact JSON"
flowing across the system is strongly typed, versioned and validated.

```
Scouts ─▶ Router ─▶ Aggregator ─▶ Macro-Strategist ─▶ Risk Manager ─▶ Execution Engine
   │         │           │               │                  │                 │
   └─────────┴───────────┴── kairos-core contracts on the message bus ────────┘
```

## What lives here

| Module | Purpose |
| --- | --- |
| `kairos_core.enums` | `ReasoningEffort`, `RouterMode`, `SystemMode`, `ReasonCode`, ... |
| `kairos_core.contracts` | Legacy DRY_RUN messages plus strict Strategy Parity / PAPER contracts |
| `kairos_core.bus` | Transport-agnostic `MessageBus` with `RedisStreamsBus` (prod) and `InMemoryBus` (tests) backends |
| `kairos_core.topics` | Canonical bus topic names (`kairos.<layer>.<event>`) |
| `kairos_core.config` | `CoreSettings` (env-driven, `KAIROS_` prefix) |
| `kairos_core.logging` | Structured JSON / console logging |

The production Redis backend requires Redis 8.2 or newer. Stream trimming uses
consumer-group-aware `ACKED` retention so pending messages are never evicted
before every group has acknowledged them.

## Design rules

1. **The LLM never sees raw streams.** It receives only compact typed strategy,
   market and evidence fields; exchange credentials and unbounded feeds stay outside
   the analytical context.
2. **Messages are versioned.** Legacy messages carry `schema_version` and ignore unknown
   minor fields. Safety-critical Strategy Parity / PAPER contracts also carry a concrete
   `contract_version`, reject unknown fields, reject non-finite numbers and are immutable.
3. **The bus is dumb.** It moves JSON between topics; services validate payloads back into
   the right contract. No per-message coupling in the transport.

## Strategy Parity and PAPER contracts

The new route is deliberately separate from the legacy
`TacticalCommand -> ValidatedOrder` DRY_RUN route:

```text
ClosedBarEventV1 -> StrategyIntentV1 -> CandidateRouteV1
    -> CandidateReviewV1 -> VenueQualityV1 + RiskTradeDecisionV1
    -> TradeExecutionEventV1 -> AccountSnapshotV2
```

- `ClosedBarEventV1` hashes the complete final Binance USD-M 1m OHLCV payload,
  including quote and taker-buy volumes.
- `StrategyIntentV1` owns side, eligibility/expiry and the immutable
  `ExitPlanV1` (`stop-target-timeout.v1`). Its ID covers code, configuration,
  input-window and feature fingerprints.
- `CandidateRouteV1` requests only the normal (`medium`) or conflict (`high`)
  review tier. `CandidateReviewV1` can only return `ALLOW`, `VETO` or `DEFER`.
- `VenueQualityV1` records the executable EVEDEX book, basis, spread, depth,
  side-specific slippage, fee and freshness inputs used by risk.
- `RiskTradeDecisionV1` proves loss-at-stop sizing and rejects mismatched
  intent, exit plan, account, profile, symbol or stale venue data. PAPER is
  valid only on EVEDEX DEV instruments ending in `:DEV`.
- `TradeExecutionEventV1` and `AccountSnapshotV2` preserve strategy, intent,
  risk decision, trade, effect and order-role lineage for recovery and audit.

`canonical_json_bytes()` uses sorted compact UTF-8 JSON and normalises negative
zero. Producers can use `canonical_sha256()` for auxiliary configuration and
feature fingerprints. With deterministic inputs, the default message envelope,
wire bytes and identity are identical across Windows research and Linux runtime.

## Local development

Install [uv](https://docs.astral.sh/uv/) once, then let the checked-in lockfile
create the Python 3.11 environment:

```powershell
winget install --id astral-sh.uv --exact
uv sync --locked
```

## Quick start

```python
from kairos_core import MarketSnapshot, OrderBookSummary, DerivativesMetrics, TechnicalIndicators
from kairos_core.enums import Side
from kairos_core.bus import InMemoryBus
from kairos_core.topics import Topics

bus = InMemoryBus()
snap = MarketSnapshot(
    source="quant-scouts", symbol="BTCUSD", mid_price=65_000, volume_usd=1e6,
    order_book=OrderBookSummary(best_bid=64999.5, best_ask=65000.5, spread_bps=0.15, imbalance=0.1, depth_usd=5e5),
    derivatives=DerivativesMetrics(funding_rate=1e-4, open_interest=1.2e9),
    indicators=TechnicalIndicators(rsi_14=58.4, macd=12, macd_signal=9.5, macd_hist=2.5),
    quant_bias=Side.LONG,
)
await bus.publish(Topics.MARKET_SNAPSHOT, snap)
```

## Tests

```powershell
uv run --locked ruff check kairos_core tests
uv run --locked ruff format --check kairos_core tests
uv run --locked mypy kairos_core
uv run --locked bandit -q -r kairos_core -x tests
uv run --locked pytest -q --tb=short
uv build --no-sources
```

---
Part of the [Kairos](https://github.com/Kairos-cryptoAI/kairos) system. MIT licensed.

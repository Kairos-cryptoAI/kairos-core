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
| `kairos_core.contracts` | Pydantic v2 messages: `MarketSnapshot`, `SentimentSignal`, `RouterDecision`, `TacticalCommand`, `StrategicAllocation`, `OrderIntent`, `ValidatedOrder`, `ExecutionReport` |
| `kairos_core.bus` | Transport-agnostic `MessageBus` with `RedisStreamsBus` (prod) and `InMemoryBus` (tests) backends |
| `kairos_core.topics` | Canonical bus topic names (`kairos.<layer>.<event>`) |
| `kairos_core.config` | `CoreSettings` (env-driven, `KAIROS_` prefix) |
| `kairos_core.logging` | Structured JSON / console logging |

## Design rules

1. **The LLM never sees raw numbers.** Layer 1 digests the market into a `MarketSnapshot`
   before anything else reads it.
2. **Messages are versioned.** Every message carries `schema_version`; consumers ignore
   unknown fields so services can be deployed independently.
3. **The bus is dumb.** It moves JSON between topics; services validate payloads back into
   the right contract. No per-message coupling in the transport.

## Install

```bash
pip install -e ".[dev]"
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

```bash
make test
```

---
Part of the [Kairos](https://github.com/Kairos-cryptoAI/kairos) system. MIT licensed.

# Thetes

Algorithmic day-trading bot with incremental indicators, event-driven data ingestion, and a Flask dashboard.

## Quick start

```bash
cp .env.example .env   # edit with your Alpaca credentials (optional)
pip install numpy pandas flask
python main.py          # CLI mode
python app.py           # web dashboard at http://localhost:5000
```

In mock mode (no valid Alpaca credentials) the bot uses in-memory broker and data providers — ready to run out of the box.

## Architecture

```
thetes/
  engine.py          — TradingEngine lifecycle, event loop, order execution
  strategy.py        — signal generation (multi-filter: EMA crossover, RSI, ADX, volume, trend)
  indicators.py      — incremental EMA/RSI/ATR/ADX (O(1) per bar) + pandas fallback
  risk_manager.py    — ATR-based position sizing, stop-loss, take-profit
  broker.py          — abstract Broker interface
  mock_broker.py     — in-memory broker for testing
  config.py          — env-based configuration
  models.py          — dataclasses for state, indicators, trade log
  data_provider.py   — abstract MarketDataProvider interface
  mock_data.py       — timer-based mock data generator
  alpaca_broker.py   — Alpaca Markets REST broker
  alpaca_data.py     — Alpaca WebSocket data stream
app.py               — Flask web dashboard
main.py              — CLI entry point
```

## Engine modes

| Mode | Data | Broker | Use case |
|---|---|---|---|
| **Mock** (default) | `MockDataProvider` | `MockBroker` | Testing, dev |
| **Alpaca paper** | `AlpacaDataProvider` (WebSocket) | `AlpacaBroker` (REST) | Paper trading |

## Strategy

8-filter signal: EMA9/21 crossover + RSI band + ADX ≥ 25 + volume ratio ≥ 1.0 + close vs EMA50 + cooldown.

## Performance

Incremental indicators avoid pandas EWM on every bar — ~10-30 µs per bar vs ~1-30 ms for full recompute (100× speedup on ADX).
[`tests/benchmarks/profile_performance.py`](tests/benchmarks/profile_performance.py) for detailed CPU/memory/lock profiling.

## Tests

```bash
pytest tests/        # 83 tests
```

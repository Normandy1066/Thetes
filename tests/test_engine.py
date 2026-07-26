import time

import pandas as pd
import pytest

from thetes.config import Config
from thetes.enums import BotStatus
from thetes.mock_broker import MockBroker
from thetes.mock_data import MockDataProvider
from thetes.engine import TradingEngine
from thetes.models import SymbolContext


def test_engine_lifecycle():
    config = Config(trading_symbol="AAPL", trade_qty=1.0, loop_delay_seconds=1, max_iterations=2)
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    assert state.status == BotStatus.STOPPED

    engine.start()
    time.sleep(0.5)

    state = engine.get_state()
    assert state.status in {BotStatus.RUNNING, BotStatus.STOPPED}

    engine.stop()
    state = engine.get_state()
    assert state.status == BotStatus.STOPPED


def test_engine_run_once():
    config = Config(trading_symbol="AAPL", trade_qty=1.0, loop_delay_seconds=1)
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    assert state.iteration == 0
    assert len(state.trade_log) == 0

    engine.run_once()

    state = engine.get_state()
    assert len(state.trade_log) >= 1
    assert state.market.last_close > 0.0
    assert len(state.price_history) >= 1


def test_multi_symbol_run_once():
    config = Config(
        trading_symbol="AAPL",
        trading_symbols=("AAPL", "MSFT", "GOOG"),
        trade_qty=1.0,
    )
    broker = MockBroker(initial_cash=100_000.0)
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    # Initialise symbol contexts
    state.symbols = {
        s: SymbolContext(symbol=s, trade_qty=1.0)
        for s in config.trading_symbols
    }

    engine.run_once()

    state = engine.get_state()
    assert len(state.trade_log) == 3  # one entry per symbol
    for sym in ("AAPL", "MSFT", "GOOG"):
        ctx = engine._symbol_ctx(sym)
        assert ctx is not None
        assert ctx.last_close > 0.0
        assert ctx.candle_buffer is not None


def test_multi_symbol_independent_indicators():
    """Each symbol should have its own indicator cache and cooldown state."""
    config = Config(
        trading_symbol="AAPL",
        trading_symbols=("AAPL", "MSFT"),
        trade_qty=1.0,
    )
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    state.symbols = {
        "AAPL": SymbolContext(symbol="AAPL", trade_qty=1.0),
        "MSFT": SymbolContext(symbol="MSFT", trade_qty=1.0),
    }

    ctx_aapl = engine._symbol_ctx("AAPL")
    ctx_msft = engine._symbol_ctx("MSFT")

    # Run once to build caches and let signals fire
    engine.run_once()

    # Set cooldown via the indicator cache (which is the real cooldown store)
    ctx_aapl = engine._symbol_ctx("AAPL")
    ctx_msft = engine._symbol_ctx("MSFT")
    if ctx_aapl.indicator_cache is not None:
        ctx_aapl.indicator_cache.cooldown_buy = 5
    if ctx_msft.indicator_cache is not None:
        ctx_msft.indicator_cache.cooldown_sell = 3

    # Run again — cooldowns should have been consumed
    engine.run_once()

    if ctx_aapl.indicator_cache is not None:
        assert ctx_aapl.indicator_cache.cooldown_buy == 4  # decremented by 1
    if ctx_msft.indicator_cache is not None:
        assert ctx_msft.indicator_cache.cooldown_sell == 2  # decremented by 1


def test_multi_symbol_simultaneous_positions():
    """Buy AAPL and MSFT; both positions should appear in the portfolio."""
    config = Config(
        trading_symbol="AAPL",
        trading_symbols=("AAPL", "MSFT"),
        trade_qty=100.0,
        risk_per_trade_pct=100.0,
        max_position_size_pct=100.0,
    )
    broker = MockBroker(initial_cash=100_000.0)

    # Use PortfolioManager directly to set up two buys (same path as engine)
    pm = broker._portfolio
    pm.execute_buy("AAPL", 10, 150.0)
    pm.execute_buy("MSFT", 5, 200.0)

    acct = broker.get_account()
    assert len(acct.positions) == 2
    symbols_in_positions = {p.symbol for p in acct.positions}
    assert symbols_in_positions == {"AAPL", "MSFT"}
    # cash = 100000 - 10*150 - 5*200 = 100000 - 1500 - 1000 = 97500
    assert acct.cash == 97500.0


def test_multi_symbol_mixed_signals():
    """One symbol buys, another sells; portfolio reflects both."""
    pm = MockBroker(initial_cash=200_000.0)._portfolio
    pm.execute_buy("AAPL", 10, 100.0)
    pm.execute_buy("SPY", 5, 200.0)
    pm.execute_sell("SPY", 3, 210.0)  # realised profit

    acct = pm.get_account_snapshot()
    assert len(acct.positions) == 2
    assert pm.realized_pnl == 30.0  # (210 - 200) * 3
    assert acct.cash == 200_000.0 - 10*100 - 5*200 + 3*210


def test_multi_symbol_portfolio_accounting():
    """PortfolioManager aggregates positions across symbols correctly."""
    config = Config(trading_symbol="AAPL", trading_symbols=("AAPL", "MSFT"))
    broker = MockBroker(initial_cash=100_000.0)
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    pm = broker._portfolio

    # Simulate buys via PortfolioManager (same path the engine uses)
    pm.execute_buy("AAPL", 10, 150.0)
    pm.execute_buy("MSFT", 5, 200.0)

    snap = pm.get_account_snapshot({"AAPL": 160.0, "MSFT": 210.0})
    assert snap.equity == pytest.approx(
        (100_000.0 - 10 * 150.0 - 5 * 200.0) + (10 * 160.0 + 5 * 210.0)
    )
    assert snap.unrealized_pnl == pytest.approx(10 * 10.0 + 5 * 10.0)  # $150 total

    # Sell AAPL at profit
    pm.execute_sell("AAPL", 10, 170.0)
    assert pm.realized_pnl == pytest.approx(10 * 20.0)  # (170 - 150) * 10


def test_multi_symbol_initialization():
    """Engine initializes with multiple symbols and they're accessible via state."""
    config = Config(
        trading_symbol="AAPL",
        trading_symbols=("AAPL", "GOOG", "MSFT"),
        trade_qty=5.0,
    )
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    assert state.trading_symbols == ("AAPL", "GOOG", "MSFT")
    assert state.primary_symbol == "AAPL"
    # Symbols are initialised at construction time
    for sym in ("AAPL", "GOOG", "MSFT"):
        assert sym in state.symbols
        ctx = state.symbols[sym]
        assert ctx.symbol == sym
        assert ctx.trade_qty == 5.0

    engine.start()
    time.sleep(0.3)
    engine.stop()

    state = engine.get_state()
    for sym in ("AAPL", "GOOG", "MSFT"):
        assert sym in state.symbols
        ctx = state.symbols[sym]
        assert ctx.candle_buffer is not None  # populated during _loop


def test_backward_compat_single_symbol():
    """Engine with default single symbol behaves like the original."""
    config = Config(trading_symbol="AAPL", trade_qty=1.0)
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    assert state.trading_symbols == ("AAPL",)
    assert state.symbol == "AAPL"

    engine.run_once()
    state = engine.get_state()
    assert len(state.trade_log) == 1
    assert state.market.last_close > 0.0

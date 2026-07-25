import time
from thetes.config import Config
from thetes.enums import BotStatus
from thetes.mock_broker import MockBroker
from thetes.mock_data import MockDataProvider
from thetes.engine import TradingEngine


def test_engine_lifecycle():
    config = Config(trading_symbol="AAPL", trade_qty=1.0, loop_delay_seconds=1, max_iterations=2)
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    state = engine.get_state()
    assert state.status == BotStatus.STOPPED

    # Start the engine
    engine.start()
    
    # Allow some time for background thread to run and stop after max_iterations
    time.sleep(0.5)
    
    state = engine.get_state()
    # It might be stopped because it reached max_iterations (2) or still running
    assert state.status in {BotStatus.RUNNING, BotStatus.STOPPED}
    
    engine.stop()
    state = engine.get_state()
    assert state.status == BotStatus.STOPPED


def test_engine_run_once():
    config = Config(trading_symbol="AAPL", trade_qty=1.0, loop_delay_seconds=1)
    broker = MockBroker()
    data_provider = MockDataProvider()
    engine = TradingEngine(config, broker, data_provider)

    # Initially 0 iterations, empty log
    state = engine.get_state()
    assert state.iteration == 0
    assert len(state.trade_log) == 0

    # Run once manually
    engine.run_once()
    
    state = engine.get_state()
    assert len(state.trade_log) == 1
    assert state.market.last_close > 0.0
    assert len(state.price_history) == 1

"""Tests for TickerManager, TradingEngine.replace_symbols, and the ticker API."""

import pytest
from flask import Flask

from thetes.config import Config
from thetes.engine import TradingEngine
from thetes.mock_broker import MockBroker
from thetes.mock_data import MockDataProvider
from thetes.ticker_manager import TickerManager

CFG = Config(trading_symbol="AAPL", trading_symbols=("AAPL", "GOOGL"), trade_qty=1.0)


@pytest.fixture
def engine():
    broker = MockBroker()
    dp = MockDataProvider()
    eng = TradingEngine(CFG, broker, dp)
    return eng


@pytest.fixture
def ticker_mgr(engine):
    return TickerManager(engine, CFG, engine.data_provider)


# ---------------------------------------------------------------------------
# TickerManager — validation
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_symbol(self):
        assert TickerManager.validate_symbol("aapl") == "AAPL"
        assert TickerManager.validate_symbol("GOOGL") == "GOOGL"
        assert TickerManager.validate_symbol("  msft  ") == "MSFT"

    def test_empty_symbol(self):
        with pytest.raises(ValueError, match="non-empty"):
            TickerManager.validate_symbol("")
        with pytest.raises(ValueError, match="non-empty"):
            TickerManager.validate_symbol(None)  # type: ignore[arg-type]

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid symbol"):
            TickerManager.validate_symbol("TOOLONGSYMX")
        with pytest.raises(ValueError, match="Invalid symbol"):
            TickerManager.validate_symbol("12345")
        with pytest.raises(ValueError, match="Invalid symbol"):
            TickerManager.validate_symbol("A-B")


# ---------------------------------------------------------------------------
# TickerManager — operations
# ---------------------------------------------------------------------------


class TestGetTickers:
    def test_returns_config_symbols(self, ticker_mgr):
        tickers = ticker_mgr.get_tickers()
        assert "AAPL" in tickers
        assert "GOOGL" in tickers

    def test_returns_list(self, ticker_mgr):
        assert isinstance(ticker_mgr.get_tickers(), list)


class TestReplaceTickers:
    def test_basic_replace(self, ticker_mgr):
        result = ticker_mgr.replace_tickers(["MSFT", "SPY"])
        assert result == ["MSFT", "SPY"]
        assert ticker_mgr.get_tickers() == ["MSFT", "SPY"]

    def test_deduplicates(self, ticker_mgr):
        result = ticker_mgr.replace_tickers(["AAPL", "AAPL", "GOOGL"])
        assert result == ["AAPL", "GOOGL"]

    def test_validates(self, ticker_mgr):
        with pytest.raises(ValueError, match="non-empty"):
            ticker_mgr.replace_tickers(["AAPL", ""])

    def test_rejects_empty(self, ticker_mgr):
        with pytest.raises(ValueError, match="At least one"):
            ticker_mgr.replace_tickers([])

    def test_preserves_existing_ctx(self, ticker_mgr, engine):
        ctx = engine._symbol_ctx("AAPL")
        ctx.last_close = 155.0
        ticker_mgr.replace_tickers(["AAPL", "MSFT"])
        new_ctx = engine._symbol_ctx("AAPL")
        assert new_ctx is ctx
        assert new_ctx.last_close == 155.0

    def test_creates_new_ctx(self, ticker_mgr, engine):
        ticker_mgr.replace_tickers(["AAPL", "MSFT"])
        assert engine._symbol_ctx("MSFT") is not None
        assert engine._symbol_ctx("MSFT").symbol == "MSFT"

    def test_removes_old_ctx(self, ticker_mgr, engine):
        ticker_mgr.replace_tickers(["AAPL"])
        assert engine._symbol_ctx("GOOGL") is None

    def test_updates_engine_symbol_field(self, ticker_mgr, engine):
        ticker_mgr.replace_tickers(["MSFT", "SPY"])
        state = engine.get_state()
        assert state.symbol == "MSFT"
        assert state.trading_symbols == ("MSFT", "SPY")


class TestAddTicker:
    def test_add_new(self, ticker_mgr):
        result = ticker_mgr.add_ticker("MSFT")
        assert "MSFT" in result

    def test_duplicate_raises(self, ticker_mgr):
        with pytest.raises(ValueError, match="already tracked"):
            ticker_mgr.add_ticker("AAPL")

    def test_updates_engine(self, ticker_mgr, engine):
        ticker_mgr.add_ticker("MSFT")
        assert engine._symbol_ctx("MSFT") is not None


class TestRemoveTicker:
    def test_remove_existing(self, ticker_mgr):
        result = ticker_mgr.remove_ticker("GOOGL")
        assert "GOOGL" not in result

    def test_unknown_raises(self, ticker_mgr):
        with pytest.raises(ValueError, match="not tracked"):
            ticker_mgr.remove_ticker("MSFT")

    def test_last_ticker_raises(self, ticker_mgr):
        ticker_mgr.replace_tickers(["AAPL"])
        with pytest.raises(ValueError, match="last remaining"):
            ticker_mgr.remove_ticker("AAPL")


# ---------------------------------------------------------------------------
# TradingEngine.replace_symbols — direct unit tests
# ---------------------------------------------------------------------------


class TestEngineReplaceSymbols:
    def test_thread_safe(self, engine):
        import threading
        errors = []

        def writer():
            try:
                engine.replace_symbols(["MSFT", "SPY"])
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=writer)
        t.start()
        t.join()
        assert not errors
        state = engine.get_state()
        assert state.trading_symbols == ("MSFT", "SPY")

    def test_symbols_property_reflects_change(self, engine):
        engine.replace_symbols(["MSFT", "SPY"])
        state = engine.get_state()
        assert state.trading_symbols == ("MSFT", "SPY")


# ---------------------------------------------------------------------------
# DataProvider update_subscription
# ---------------------------------------------------------------------------


class TestUpdateSubscription:
    def test_mock_data_provider(self, engine):
        dp = engine.data_provider
        assert hasattr(dp, "update_subscription")
        dp.subscribe_bars(["AAPL", "GOOGL"], lambda x: None)
        assert set(dp._callbacks.keys()) == {"AAPL", "GOOGL"}
        dp.update_subscription(["MSFT"])
        assert set(dp._callbacks.keys()) == {"MSFT"}

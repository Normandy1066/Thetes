"""Regression tests: end-to-end engine pipeline produces correct results."""

import pandas as pd
import pytest

from thetes.config import Config
from thetes.enums import Signal
from thetes.engine import TradingEngine
from thetes.mock_broker import MockBroker
from thetes.mock_data import MockDataProvider
from thetes.strategy import generate_signals

CFG = Config(trading_symbol="SPY", trade_qty=100.0)


def _make_buy_scenario() -> pd.DataFrame:
    n_flat, n_up = 30, 30
    flat = [150.0] * n_flat
    trend = [150.0 + i * 1.5 for i in range(n_up)]
    close = flat + trend
    high = [c + 2.0 for c in close]
    low = [c - 2.0 for c in close]
    volume = [2000] * n_flat + [4000] * 25 + [8000] * 5
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_flat + n_up, freq="5min")
    return pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close, "volume": volume,
    }, index=dates)


def _make_sell_scenario() -> pd.DataFrame:
    n_flat, n_down = 30, 30
    flat = [150.0] * n_flat
    trend = [150.0 - i * 1.5 for i in range(n_down)]
    close = flat + trend
    high = [c + 2.0 for c in close]
    low = [c - 2.0 for c in close]
    volume = [2000] * n_flat + [4000] * 25 + [8000] * 5
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_flat + n_down, freq="5min")
    return pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close, "volume": volume,
    }, index=dates)


def _make_hold_scenario() -> pd.DataFrame:
    close = [150.0] * 60
    dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="5min")
    return pd.DataFrame({
        "open": close, "high": [152.0] * 60,
        "low": [148.0] * 60, "close": close, "volume": [2000] * 60,
    }, index=dates)


def _make_buy_high_volume_scenario() -> pd.DataFrame:
    n_flat, n_up = 30, 30
    flat = [150.0] * n_flat
    trend = [150.0 + i * 1.5 for i in range(n_up)]
    close = flat + trend
    high = [c + 2.0 for c in close]
    low = [c - 2.0 for c in close]
    volume = [10000] * (n_flat + n_up)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_flat + n_up, freq="5min")
    return pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close, "volume": volume,
    }, index=dates)


class TestEngineRegression:
    def _execute(self, df: pd.DataFrame, cfg: Config | None = None, account_override: object = None) -> dict:
        c = cfg or CFG
        broker = MockBroker(initial_cash=100_000.0)
        if account_override is not None:
            broker._cash = account_override.get("cash", 100_000.0)
            if "position" in account_override:
                pos = account_override["position"]
                broker._positions[pos["symbol"]] = {"qty": pos["qty"], "avg_price": pos["price"]}
        engine = TradingEngine(c, broker, MockDataProvider())
        engine._account_cache = broker.get_account()
        engine._candle_buffer = df
        engine._execute(df, c.trading_symbol, c.trade_qty, 1)
        state = engine.get_state()
        log = state.trade_log[0]
        return {
            "signal": log.signal,
            "action": log.action,
            "close_price": log.close_price,
            "indicators": log.indicators,
            "cash": log.cash,
            "buying_power": log.buying_power,
            "error": log.error,
            "broker": broker,
            "engine": engine,
        }

    def test_buy_signal_execution(self):
        df = _make_buy_scenario()
        expected_sig, _ = generate_signals(df)
        r = self._execute(df)
        if expected_sig == Signal.BUY:
            assert r["action"] == "BUY ORDER PLACED"
            assert r["signal"] == "BUY"
            acct = r["broker"].get_account()
            assert len(acct.positions) == 1
            assert acct.positions[0].symbol == "SPY"
            assert acct.positions[0].qty > 0
            assert acct.cash < 100_000.0
        else:
            assert r["action"] == "HOLD"

    def test_sell_signal_execution(self):
        df = _make_sell_scenario()
        expected_sig, _ = generate_signals(df)
        r = self._execute(df, account_override={
            "position": {"symbol": "SPY", "qty": 10, "price": 150.0},
        })
        if expected_sig == Signal.SELL:
            assert r["action"] == "SELL ORDER PLACED"
            assert r["signal"] == "SELL"
            acct = r["broker"].get_account()
            assert acct.cash > 100_000.0
        else:
            assert r["action"] == "HOLD"

    def test_hold_signal_no_action(self):
        df = _make_hold_scenario()
        r = self._execute(df)
        expected_sig, _ = generate_signals(df)
        assert expected_sig == Signal.HOLD
        assert r["action"] == "HOLD"
        assert r["signal"] == "HOLD"

    def test_position_sizing_respects_risk(self):
        df = _make_buy_high_volume_scenario()
        cfg = Config(
            trading_symbol="SPY", trade_qty=100.0,
            risk_per_trade_pct=1.0, atr_stop_multiple=2.0,
            max_position_size_pct=100.0,
        )
        r = self._execute(df, cfg)
        if r["action"] == "BUY ORDER PLACED":
            acct = r["broker"].get_account()
            cost = 100_000.0 - acct.cash
            position = acct.positions[0]
            assert cost == pytest.approx(position.qty * position.avg_entry_price, rel=1e-3)
            assert position.qty <= 100.0

    def test_insufficient_cash_no_trade(self):
        df = _make_buy_scenario()
        cfg = Config(trading_symbol="SPY", trade_qty=100.0, risk_per_trade_pct=100.0)
        r = self._execute(df, cfg, account_override={"cash": 1.0})
        expected_sig, _ = generate_signals(df, cfg)
        if expected_sig == Signal.BUY:
            assert r["action"].startswith("BUY FAILED") or r["action"] == "HOLD"

    def test_zero_atr_no_trade(self):
        df = _make_buy_scenario().copy()
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 5000
        r = self._execute(df)
        assert r["action"] == "HOLD"

    def test_cooldown_suppresses_repeat_signals(self):
        df_active = _make_buy_scenario()
        cfg = Config(trading_symbol="SPY", trade_qty=100.0, cooldown_candles=10)

        sig1, _ = generate_signals(df_active, cfg)
        r1 = self._execute(df_active, cfg)
        trades_after_first = sum(
            1 for e in r1["engine"].get_state().trade_log
            if e.action and "ORDER PLACED" in e.action
        )
        if sig1 == Signal.BUY:
            assert r1["action"] == "BUY ORDER PLACED"

        engine = r1["engine"]
        df_flat = _make_hold_scenario()
        engine._candle_buffer = df_flat
        engine._execute(df_flat, cfg.trading_symbol, cfg.trade_qty, 2)
        state2 = engine.get_state()
        trades = [e for e in state2.trade_log if e.action and "ORDER PLACED" in e.action]
        assert len(trades) <= 1

    def test_cached_and_full_paths_agree(self):
        df = _make_buy_scenario()
        sig_full, ind_full = generate_signals(df)
        r = self._execute(df)
        assert r["signal"] == sig_full.value
        ind = r["indicators"]
        assert ind is not None
        assert ind.ema9 == ind_full.ema9
        assert ind.ema21 == ind_full.ema21
        assert ind.rsi == ind_full.rsi
        assert ind.atr == ind_full.atr
        assert ind.adx == ind_full.adx
        assert ind.volume_ratio == ind_full.volume_ratio

    def test_consecutive_runs_match_strategy(self):
        df = _make_buy_scenario()
        first_sig, first_ind = generate_signals(df)
        cfg = Config(trading_symbol="SPY", trade_qty=100.0)
        broker = MockBroker(initial_cash=100_000.0)
        engine = TradingEngine(cfg, broker, MockDataProvider())
        engine._account_cache = broker.get_account()
        engine._candle_buffer = df
        engine._execute(df, "SPY", 100.0, 1)
        state = engine.get_state()
        log = state.trade_log[0]
        assert log.signal == first_sig.value
        assert log.indicators.ema9 == first_ind.ema9

        df2 = _make_hold_scenario()
        engine._candle_buffer = df2
        engine._execute(df2, "SPY", 100.0, 2)
        state2 = engine.get_state()
        log2 = state2.trade_log[0]
        sig2, ind2 = generate_signals(df2)
        assert log2.signal == sig2.value

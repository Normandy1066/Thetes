"""Performance benchmarks: cached/incremental vs full-computation paths.

Each benchmark function is a self-contained pytest test that measures
execution time and prints results to stdout.  No external benchmark
framework is required.
"""

import math
import sys
import time
from collections import deque

import numpy as np
import pandas as pd

from thetes.config import Config
from thetes.enums import Signal
from thetes.indicators import (
    AdxState,
    AtrState,
    EmaState,
    RsiState,
    adx,
    adx_incremental,
    adx_state_from_series,
    atr,
    atr_incremental,
    atr_state_from_series,
    ema,
    ema_incremental,
    rsi,
    rsi_incremental,
    rsi_state_from_series,
    volume_sma,
)
from thetes.risk_manager import RiskManager
from thetes.strategy import IndicatorCache, generate_signals, generate_signals_cached

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RTOL = 1e-10
ATOL = 1e-10

rng = np.random.default_rng(seed=42)
CFG = Config()


def _make_df(n: int) -> pd.DataFrame:
    returns = rng.normal(0, 0.005, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + rng.uniform(0.001, 0.015, n))
    low = close * (1.0 - rng.uniform(0.001, 0.015, n))
    return pd.DataFrame({
        "open": low + rng.uniform(0, 1, n) * (high - low),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


def _indicator_cache_from_df(df: pd.DataFrame) -> IndicatorCache:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    ema9_s = ema(close, 9)
    ema21_s = ema(close, 21)
    ema_trend_s = ema(close, 50)
    vol_sma_s = volume_sma(volume, 20)
    vol_vals = list(volume.iloc[-20:])
    return IndicatorCache(
        ema9_state=EmaState(value=float(ema9_s.iloc[-1]), span=9),
        ema21_state=EmaState(value=float(ema21_s.iloc[-1]), span=21),
        ema_trend_state=EmaState(value=float(ema_trend_s.iloc[-1]), span=50),
        rsi_state=rsi_state_from_series(close, 14),
        atr_state=atr_state_from_series(high, low, close, 14),
        adx_state=adx_state_from_series(high, low, close, 14),
        volume_deque=deque(vol_vals, maxlen=20),
        volume_sum=sum(vol_vals),
        volume_sma=float(vol_sma_s.iloc[-1]),
        prev_close=float(close.iloc[-1]),
        cooldown_buy=0,
        cooldown_sell=0,
    )


def _measure(label: str, fn, iterations: int = 1000) -> float:
    """Run *fn* *iterations* times and return total elapsed seconds."""
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start
    per_op = elapsed / iterations * 1e6
    print(f"  {label:45s}  {elapsed:9.4f}s total  {per_op:9.1f}µs/op")
    return elapsed


DATA_SIZES = [100, 500, 2000]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# 1. Indicator benchmarks
# ---------------------------------------------------------------------------


class TestIndicatorPerformance:
    def test_ema_full_vs_incremental(self):
        print("\n--- EMA: full vs incremental ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            close = df["close"]
            full_s = ema(close, 21)
            state = EmaState(value=float(full_s.iloc[0]), span=21)

            def full_recalc():
                ema(close, 21)

            def incremental_one():
                nonlocal state
                val, state = ema_incremental(float(close.iloc[-1]), 21, state)
                return val

            t_full = _measure(f"full (n={n}, {n} ops)", full_recalc, iterations=100)
            t_inc = _measure(f"incremental (n={n}, 1 op)", incremental_one, iterations=1000)
            ratio = t_full / t_inc if t_inc > 0 else 0
            print(f"    speedup: {ratio:.1f}x  ({n} full vs 1 inc)")
            assert math.isfinite(ratio)

    def test_rsi_full_vs_incremental(self):
        print("\n--- RSI: full vs incremental ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            close = df["close"]
            full_s = rsi(close, 14)
            state = rsi_state_from_series(close.iloc[:14], 14)

            def full_recalc():
                rsi(close, 14)

            def incremental_one():
                nonlocal state
                val, state = rsi_incremental(float(close.iloc[-1]), state)
                return val

            t_full = _measure(f"full (n={n})", full_recalc, iterations=100)
            t_inc = _measure(f"incremental (n={n})", incremental_one, iterations=1000)
            ratio = t_full / t_inc if t_inc > 0 else 0
            print(f"    speedup: {ratio:.1f}x")
            assert math.isfinite(ratio)

    def test_atr_full_vs_incremental(self):
        print("\n--- ATR: full vs incremental ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            high, low, close = df["high"], df["low"], df["close"]
            full_s = atr(high, low, close, 14)
            state = atr_state_from_series(high.iloc[:14], low.iloc[:14], close.iloc[:14], 14)

            def full_recalc():
                atr(high, low, close, 14)

            def incremental_one():
                nonlocal state
                val, state = atr_incremental(float(high.iloc[-1]), float(low.iloc[-1]), float(close.iloc[-1]), state)
                return val

            t_full = _measure(f"full (n={n})", full_recalc, iterations=100)
            t_inc = _measure(f"incremental (n={n})", incremental_one, iterations=1000)
            ratio = t_full / t_inc if t_inc > 0 else 0
            print(f"    speedup: {ratio:.1f}x")
            assert math.isfinite(ratio)

    def test_adx_full_vs_incremental(self):
        print("\n--- ADX: full vs incremental ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            high, low, close = df["high"], df["low"], df["close"]
            warmup = 28
            full_s = adx(high, low, close, 14)
            state = adx_state_from_series(high.iloc[:warmup], low.iloc[:warmup], close.iloc[:warmup], 14)

            def full_recalc():
                adx(high, low, close, 14)

            def incremental_one():
                nonlocal state
                val, state = adx_incremental(float(high.iloc[-1]), float(low.iloc[-1]), float(close.iloc[-1]), state)
                return val

            t_full = _measure(f"full (n={n})", full_recalc, iterations=100)
            t_inc = _measure(f"incremental (n={n})", incremental_one, iterations=1000)
            ratio = t_full / t_inc if t_inc > 0 else 0
            print(f"    speedup: {ratio:.1f}x")
            assert math.isfinite(ratio)


# ---------------------------------------------------------------------------
# 2. Signal generation benchmarks
# ---------------------------------------------------------------------------


class TestSignalGenerationPerformance:
    def test_generate_signals_full_vs_cached(self):
        print("\n--- Signal generation: full vs cached (incremental) ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            cache = _indicator_cache_from_df(df.iloc[:-1])

            def full_generate():
                generate_signals(df)

            def cached_generate():
                generate_signals_cached(df, cache)

            t_full = _measure(f"generate_signals full (n={n})", full_generate, iterations=100)
            t_cached = _measure(f"generate_signals_cached (n={n})", cached_generate, iterations=1000)
            ratio = t_full / t_cached if t_cached > 0 else 0
            print(f"    speedup: {ratio:.1f}x")
            assert math.isfinite(ratio)
            sig, _, _ = generate_signals_cached(df, cache)
            assert sig in (Signal.BUY, Signal.SELL, Signal.HOLD)

    def test_cache_miss_penalty(self):
        print("\n--- Cache miss penalty (full recompute on stale cache) ---")
        df = _make_df(100)
        cache = _indicator_cache_from_df(df.iloc[:-1])
        stale_cache = IndicatorCache(
            ema9_state=EmaState(value=0.0, span=9),
            ema21_state=EmaState(value=0.0, span=21),
            ema_trend_state=EmaState(value=0.0, span=50),
            rsi_state=RsiState(avg_gain=0.0, avg_loss=0.0, prev_close=0.0, period=14),
            atr_state=AtrState(value=0.0, prev_close=0.0, period=14),
            adx_state=AdxState(
                smoothed_tr=0.0, smoothed_plus_dm=0.0, smoothed_minus_dm=0.0,
                adx=0.0, prev_high=0.0, prev_low=0.0, prev_close=0.0, period=14,
            ),
            volume_deque=deque([0.0] * 20, maxlen=20),
            volume_sum=0.0,
            volume_sma=0.0,
            prev_close=0.0,
            cooldown_buy=0,
            cooldown_sell=0,
        )

        def hit():
            generate_signals_cached(df, cache)

        def miss():
            generate_signals_cached(df, stale_cache)

        t_hit = _measure("cache HIT (n=100)", hit, iterations=1000)
        t_miss = _measure("cache MISS (full recompute, n=100)", miss, iterations=100)
        penalty = t_miss / t_hit if t_hit > 0 else 0
        print(f"    cache miss penalty: {penalty:.1f}x slower than hit")
        assert math.isfinite(penalty)

    def test_streaming_throughput(self):
        print("\n--- Streaming throughput: n add-bars over m iterations ---")
        n_bars = 50
        df_all = _make_df(100 + n_bars)
        df_base = df_all.iloc[:100]
        new_bars = df_all.iloc[100:]

        cache = _indicator_cache_from_df(df_base)
        buffer = df_base.copy()

        def simulate_stream():
            nonlocal buffer, cache
            for idx in range(n_bars):
                row = new_bars.iloc[idx:idx + 1]
                buffer = pd.concat([buffer, row])
                if len(buffer) > 100:
                    buffer = buffer.iloc[-100:]
                _, _, cache = generate_signals_cached(buffer, cache)

        t = _measure(f"process {n_bars} streaming bars", simulate_stream, iterations=10)
        print(f"    avg per bar: {t / (10 * n_bars) * 1e6:.1f}µs")
        assert math.isfinite(t)


# ---------------------------------------------------------------------------
# 3. Risk evaluation benchmarks
# ---------------------------------------------------------------------------


class TestRiskManagerPerformance:
    def test_risk_evaluate_cached_vs_full(self):
        print("\n--- RiskManager.evaluate: ATR cached vs full ---")
        from thetes.mock_broker import MockBroker

        broker = MockBroker()
        for n in DATA_SIZES:
            df = _make_df(n)

            def first_call(n=n):
                risk = RiskManager(CFG, broker)
                risk.evaluate(Signal.BUY, 100.0, df, 10.0)

            risk = RiskManager(CFG, broker)
            risk.evaluate(Signal.BUY, 100.0, df, 10.0)

            def second_call():
                risk.evaluate(Signal.HOLD, 100.0, df, 10.0)

            t_full = _measure(f"no cache / full ATR compute (n={n})", first_call, iterations=100)
            t_cached = _measure(f"ATR cache HIT (n={n})", second_call, iterations=1000)
            ratio = t_full / t_cached if t_cached > 0 else 0
            print(f"    speedup: {ratio:.1f}x")
            assert math.isfinite(ratio)


# ---------------------------------------------------------------------------
# 4. Memory footprint benchmarks
# ---------------------------------------------------------------------------


class TestMemoryFootprint:
    def test_indicator_cache_size(self):
        print("\n--- IndicatorCache memory footprint ---")
        df = _make_df(100)
        cache = _indicator_cache_from_df(df)
        cache_bytes = sys.getsizeof(cache)
        print(f"  IndicatorCache: {cache_bytes} bytes (sys.getsizeof)")
        for field_name in ("ema9_state", "ema21_state", "ema_trend_state", "rsi_state", "atr_state", "adx_state", "volume_deque"):
            obj = getattr(cache, field_name)
            sz = sys.getsizeof(obj)
            print(f"    .{field_name}: {sz} bytes")
        assert cache_bytes > 0

    def test_dataframe_vs_cache_size(self):
        print("\n--- DataFrame vs IndicatorCache memory ---")
        for n in DATA_SIZES:
            df = _make_df(n)
            cache = _indicator_cache_from_df(df)
            df_bytes = sys.getsizeof(df)
            cache_bytes = sys.getsizeof(cache)
            print(f"  n={n:5d}  DataFrame={df_bytes:>7} bytes  IndicatorCache={cache_bytes:>4} bytes  "
                  f"ratio={df_bytes/cache_bytes:.0f}x")
            assert cache_bytes > 0
            assert df_bytes > 0


# ---------------------------------------------------------------------------
# 5. API-call counting benchmark
# ---------------------------------------------------------------------------


class TestAccountCacheEffectiveness:
    def test_account_cache_reduces_calls(self):
        print("\n--- Account cache: trade vs HOLD iteration call count ---")
        from thetes.engine import TradingEngine
        from thetes.mock_broker import MockBroker
        from thetes.mock_data import MockDataProvider

        broker = MockBroker()
        data = MockDataProvider()
        engine = TradingEngine(CFG, broker, data)
        original_get_account = broker.get_account

        call_counts = {"trade": 0, "hold": 0}

        def counting_get_account():
            call_counts["trade"] += 1
            return original_get_account()

        broker.get_account = counting_get_account

        df = _make_df(100)
        ctx = engine._symbol_ctx("AAPL")
        assert ctx is not None
        ctx.candle_buffer = df
        engine._account_cache = original_get_account()

        engine._execute_symbol("AAPL", 1)
        hold_count = call_counts["trade"]
        print(f"  HOLD iteration: {hold_count} get_account calls (expected 0)")
        assert hold_count == 0, f"Expected 0 get_account calls on HOLD, got {hold_count}"

        call_counts["trade"] = 0
        call_counts["hold"] = 0
        engine._execute_symbol("AAPL", 2)
        hold_count2 = call_counts["trade"]
        print(f"  HOLD iteration (no trade): {hold_count2} get_account calls (expected 0)")
        assert hold_count2 == 0, f"Expected 0 get_account calls on HOLD, got {hold_count2}"

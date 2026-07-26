import math
from collections import deque

import numpy as np
import pandas as pd
import pytest

from thetes.indicators import (
    AdxState,
    AtrState,
    EmaState,
    RsiState,
    _adx_full,
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

RTOL = 1e-10
ATOL = 1e-10


def _prices(rng: np.random.Generator, n: int, base: float = 100.0, sigma: float = 0.5) -> pd.Series:
    returns = rng.normal(0, sigma, n)
    close = base * np.exp(np.cumsum(returns))
    return pd.Series(close)


def _ohlcv(rng: np.random.Generator, n: int) -> pd.DataFrame:
    close = _prices(rng, n)
    high = close * (1.0 + rng.uniform(0.001, 0.02, n))
    low = close * (1.0 - rng.uniform(0.001, 0.02, n))
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(1000, 10000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _scenario_flat(rng: np.random.Generator, n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "open": [100.0] * n,
        "high": [100.5] * n,
        "low": [99.5] * n,
        "close": [100.0] * n,
        "volume": [5000] * n,
    })


def _scenario_trending(rng: np.random.Generator, n: int) -> pd.DataFrame:
    close = 100.0 * np.exp(np.linspace(0, 0.5, n))
    high = close * 1.01
    low = close * 0.99
    return pd.DataFrame({
        "open": low + (high - low) * 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


def _scenario_volatile(rng: np.random.Generator, n: int) -> pd.DataFrame:
    returns = rng.normal(0, 0.03, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    half_spread = rng.uniform(0.005, 0.04, n)
    high = close * (1.0 + half_spread)
    low = close * (1.0 - half_spread)
    return pd.DataFrame({
        "open": low + rng.uniform(0, 1, n) * (high - low),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


def _scenario_gaps(rng: np.random.Generator, n: int) -> pd.DataFrame:
    close = np.empty(n)
    gap_indices = set(rng.integers(10, n - 1, size=n // 20))
    prev = 100.0
    for i in range(n):
        if i in gap_indices:
            gap = rng.uniform(-5, 5)
            prev = prev + gap
        else:
            prev = prev + rng.normal(0, 0.3)
        close[i] = prev
    close = np.maximum(close, 1.0)
    high = close * (1.0 + rng.uniform(0.001, 0.025, n))
    low = close * (1.0 - rng.uniform(0.001, 0.025, n))
    return pd.DataFrame({
        "open": low + rng.uniform(0, 1, n) * (high - low),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


SCENARIOS = [
    ("flat", _scenario_flat),
    ("trending", _scenario_trending),
    ("volatile", _scenario_volatile),
    ("gaps", _scenario_gaps),
]


def _assert_close(name: str, step: int, got: float, expected: float, tol: float = 1e-10):
    if math.isnan(expected):
        return
    assert math.isfinite(got), f"{name} step {step}: got {got} (expected {expected})"
    if not math.isclose(got, expected, rel_tol=tol, abs_tol=tol):
        raise AssertionError(
            f"{name} step {step}: got {got}, expected {expected}, "
            f"diff {abs(got - expected)}"
        )


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("span", [9, 21, 50])
@pytest.mark.parametrize("scenario_name,scenario_fn", SCENARIOS)
def test_ema_incremental(span: int, scenario_name: str, scenario_fn):
    rng = np.random.default_rng(seed=42)
    n = 2000
    df = scenario_fn(rng, n)
    close = df["close"]
    full = ema(close, span)
    state = EmaState(value=float(full.iloc[0]), span=span)
    for i in range(1, n):
        inc_val, state = ema_incremental(float(close.iloc[i]), span, state)
        _assert_close(f"ema_{span}_{scenario_name}", i, inc_val, float(full.iloc[i]))


def test_ema_warmup():
    rng = np.random.default_rng(seed=99)
    n = 100
    df = _scenario_volatile(rng, n)
    close = df["close"]
    full = ema(close, 21)
    state = EmaState(value=float(full.iloc[0]), span=21)
    for i in range(1, n):
        inc_val, state = ema_incremental(float(close.iloc[i]), 21, state)
        _assert_close("ema_warmup_21", i, inc_val, float(full.iloc[i]))


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("period", [7, 14, 21])
@pytest.mark.parametrize("scenario_name,scenario_fn", SCENARIOS)
def test_rsi_incremental(period: int, scenario_name: str, scenario_fn):
    rng = np.random.default_rng(seed=42)
    n = 2000
    df = scenario_fn(rng, n)
    close = df["close"]
    full = rsi(close, period)
    state = rsi_state_from_series(close.iloc[:period], period)
    for i in range(period, n):
        inc_val, state = rsi_incremental(float(close.iloc[i]), state)
        _assert_close(f"rsi_{period}_{scenario_name}", i, inc_val, float(full.iloc[i]))


def test_rsi_constant_series():
    close = pd.Series([50.0] * 200)
    full = rsi(close, 14)
    state = rsi_state_from_series(close.iloc[:14], 14)
    for i in range(14, 200):
        inc_val, state = rsi_incremental(float(close.iloc[i]), state)
        if math.isnan(float(full.iloc[i])):
            continue
        assert inc_val == 100.0 or math.isclose(inc_val, 100.0), f"step {i}: {inc_val}"


def test_rsi_state_init():
    series = pd.Series(range(100, 200))
    state = rsi_state_from_series(series, 14)
    assert state.period == 14
    assert state.prev_close == 199.0
    assert state.avg_gain > 0.0
    assert state.avg_loss >= 0.0


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("period", [7, 14, 21])
@pytest.mark.parametrize("scenario_name,scenario_fn", SCENARIOS)
def test_atr_incremental(period: int, scenario_name: str, scenario_fn):
    rng = np.random.default_rng(seed=42)
    n = 2000
    df = scenario_fn(rng, n)
    high, low, close = df["high"], df["low"], df["close"]
    full = atr(high, low, close, period)
    state = atr_state_from_series(high.iloc[:period], low.iloc[:period], close.iloc[:period], period)
    for i in range(period, n):
        inc_val, state = atr_incremental(
            float(high.iloc[i]), float(low.iloc[i]), float(close.iloc[i]), state
        )
        _assert_close(f"atr_{period}_{scenario_name}", i, inc_val, float(full.iloc[i]))


def test_atr_constant():
    n = 200
    high = pd.Series([101.0] * n)
    low = pd.Series([99.0] * n)
    close = pd.Series([100.0] * n)
    full = atr(high, low, close, 14)
    state = atr_state_from_series(high.iloc[:14], low.iloc[:14], close.iloc[:14], 14)
    for i in range(14, n):
        inc_val, state = atr_incremental(
            float(high.iloc[i]), float(low.iloc[i]), float(close.iloc[i]), state
        )
        if math.isnan(float(full.iloc[i])):
            continue
        _assert_close("atr_const", i, inc_val, float(full.iloc[i]))


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("period", [7, 14])
@pytest.mark.parametrize("scenario_name,scenario_fn", SCENARIOS)
def test_adx_incremental(period: int, scenario_name: str, scenario_fn):
    rng = np.random.default_rng(seed=42)
    n = 2000
    df = scenario_fn(rng, n)
    high, low, close = df["high"], df["low"], df["close"]
    full = adx(high, low, close, period)
    warmup = 2 * period
    state = adx_state_from_series(high.iloc[:warmup], low.iloc[:warmup], close.iloc[:warmup], period)
    for i in range(warmup, n):
        inc_val, state = adx_incremental(
            float(high.iloc[i]), float(low.iloc[i]), float(close.iloc[i]), state
        )
        _assert_close(f"adx_{period}_{scenario_name}", i, inc_val, float(full.iloc[i]))


def test_adx_state_key_fields():
    rng = np.random.default_rng(seed=7)
    n = 500
    df = _scenario_trending(rng, n)
    high, low, close = df["high"], df["low"], df["close"]
    state = adx_state_from_series(high, low, close, 14)
    assert state.period == 14
    assert state.prev_high == float(high.iloc[-1])
    assert state.prev_low == float(low.iloc[-1])
    assert state.prev_close == float(close.iloc[-1])
    assert state.smoothed_tr > 0


# ---------------------------------------------------------------------------
# Cross-indicator consistency: ATR appears in both indicators & risk_manager
# ---------------------------------------------------------------------------

def test_atr_incremental_matches_adx_tr_component():
    rng = np.random.default_rng(seed=123)
    n = 500
    df = _scenario_volatile(rng, n)
    high, low, close = df["high"], df["low"], df["close"]
    full_atr = atr(high, low, close, 14)
    state = atr_state_from_series(high.iloc[:14], low.iloc[:14], close.iloc[:14], 14)
    for i in range(14, n):
        inc_val, state = atr_incremental(
            float(high.iloc[i]), float(low.iloc[i]), float(close.iloc[i]), state
        )
        _assert_close("atr_adx_consistency", i, inc_val, float(full_atr.iloc[i]))


# ---------------------------------------------------------------------------
# Volume SMA (stateless wrapper)
# ---------------------------------------------------------------------------

def test_volume_sma():
    rng = np.random.default_rng(seed=42)
    v = pd.Series(rng.integers(1000, 10000, 200))
    sma = volume_sma(v, 20)
    assert pd.isna(sma.iloc[18])
    assert not pd.isna(sma.iloc[19])
    assert math.isclose(float(sma.iloc[-1]), float(v.iloc[-20:].mean()), rel_tol=1e-12)


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


def test_ema():
    prices = pd.Series([10.0, 10.0, 10.0, 20.0, 20.0])
    ema_result = ema(prices, span=3)
    assert ema_result.iloc[0] == 10.0
    assert ema_result.iloc[3] == 15.0
    assert ema_result.iloc[4] == 17.5


def test_rsi():
    prices = pd.Series([10.0] * 20)
    rsi_result = rsi(prices, period=14)
    assert pd.isna(rsi_result.iloc[12])
    assert pd.isna(rsi_result.iloc[19]) or np.isnan(rsi_result.iloc[19])
    upward_prices = pd.Series(range(100, 125))
    upward_rsi = rsi(upward_prices, period=14)
    assert upward_rsi.iloc[-1] > 90.0


def test_rsi_edge_all_gains():
    rng = np.random.default_rng(seed=1)
    close = pd.Series(100.0 * np.exp(np.cumsum(np.abs(rng.normal(0, 0.01, 200)))))
    full = rsi(close, 14)
    state = rsi_state_from_series(close.iloc[:14], 14)
    for i in range(14, 200):
        inc_val, state = rsi_incremental(float(close.iloc[i]), state)
        if not math.isnan(float(full.iloc[i])):
            _assert_close("rsi_all_gains", i, inc_val, float(full.iloc[i]))

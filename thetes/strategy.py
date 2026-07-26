"""strategy.py

Algorithmic day-trading signal generator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import pandas as pd

from thetes.enums import Signal
from thetes.indicators import (
    EmaState,
    RsiState,
    ema,
    ema_incremental,
    rsi,
    rsi_incremental,
    rsi_state_from_series,
)
from thetes.models import IndicatorValues


@dataclass
class IndicatorCache:
    ema9_state: EmaState
    ema21_state: EmaState
    rsi_state: RsiState
    prev_close: float


def _validate_dataframe(df: pd.DataFrame) -> None:
    """Validate input DataFrame.

    Raises
    ------
    ValueError
        If ``df`` is empty, missing required columns, or lacks enough rows
        for the 21-period EMA.
    """
    required_cols = {"open", "high", "low", "close", "volume"}
    if df.empty:
        raise ValueError("Input DataFrame is empty.")
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")
    if len(df) < 21:
        raise ValueError("DataFrame must contain at least 21 rows for EMA calculation.")


def generate_signals(df: pd.DataFrame) -> Tuple[Signal, IndicatorValues]:
    """Generate a trading signal from 5-minute candlestick data.

    Parameters
    ----------
    df : pandas.DataFrame
        Historical candlestick data with columns: ``open``, ``high``,
        ``low``, ``close``, and ``volume``.  Ordered chronologically,
        newest row last.

    Returns
    -------
    Tuple[Signal, IndicatorValues]
        A tuple of (signal, indicators) where signal is one of the Signal enum values
        and indicators is an IndicatorValues object.
    """
    return _generate_impl(df, None)[:2]


def generate_signals_cached(
    df: pd.DataFrame, cache: IndicatorCache | None
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    """Generate a trading signal, optionally using cached indicator state.

    When *cache* is provided and the second-to-last close matches the cached
    previous close, only the latest candle is used to update EMA / RSI
    incrementally instead of recomputing over the full history.

    Returns
    -------
    Tuple[Signal, IndicatorValues, IndicatorCache]
        Signal, current indicator values, and updated cache for the next call.
    """
    return _generate_impl(df, cache)


def _generate_impl(
    df: pd.DataFrame, cache: IndicatorCache | None
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    _validate_dataframe(df)
    close = df["close"]

    if cache is not None and _can_use_cache(close, cache):
        return _compute_from_cache(close, cache)

    return _compute_full(df, close)


def _can_use_cache(close: pd.Series, cache: IndicatorCache) -> bool:
    if len(close) < 2:
        return False
    return float(close.iloc[-2]) == cache.prev_close


def _compute_from_cache(
    close: pd.Series, cache: IndicatorCache
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    new_close = float(close.iloc[-1])

    ema9_val, ema9_state = ema_incremental(new_close, 9, cache.ema9_state)
    ema21_val, ema21_state = ema_incremental(new_close, 21, cache.ema21_state)
    rsi_val, rsi_state = rsi_incremental(new_close, cache.rsi_state)

    ema9_prev = cache.ema9_state.value
    ema21_prev = cache.ema21_state.value

    signal = Signal.HOLD
    if ema9_prev <= ema21_prev and ema9_val > ema21_val and 40 <= rsi_val <= 70:
        signal = Signal.BUY
    elif ema9_prev >= ema21_prev and ema9_val < ema21_val:
        signal = Signal.SELL

    indicators = IndicatorValues(
        ema9=round(ema9_val, 4),
        ema21=round(ema21_val, 4),
        rsi=round(rsi_val, 2),
    )

    new_cache = IndicatorCache(
        ema9_state=ema9_state,
        ema21_state=ema21_state,
        rsi_state=rsi_state,
        prev_close=new_close,
    )

    return signal, indicators, new_cache


def _compute_full(
    df: pd.DataFrame, close: pd.Series
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    ema9_series = ema(close, 9)
    ema21_series = ema(close, 21)
    rsi14_series = rsi(close, 14)

    ema9_val = float(ema9_series.iloc[-1])
    ema21_val = float(ema21_series.iloc[-1])
    rsi_val = float(rsi14_series.iloc[-1])
    ema9_prev = float(ema9_series.iloc[-2])
    ema21_prev = float(ema21_series.iloc[-2])

    signal = Signal.HOLD
    if ema9_prev <= ema21_prev and ema9_val > ema21_val and 40 <= rsi_val <= 70:
        signal = Signal.BUY
    elif ema9_prev >= ema21_prev and ema9_val < ema21_val:
        signal = Signal.SELL

    indicators = IndicatorValues(
        ema9=round(ema9_val, 4),
        ema21=round(ema21_val, 4),
        rsi=round(rsi_val, 2),
    )

    cache = IndicatorCache(
        ema9_state=EmaState(value=ema9_val, span=9),
        ema21_state=EmaState(value=ema21_val, span=21),
        rsi_state=rsi_state_from_series(close, 14),
        prev_close=float(close.iloc[-1]),
    )

    return signal, indicators, cache

"""strategy.py

Algorithmic day-trading signal generator.

Provides a single public function ``generate_signals(df)`` that calculates a
fast (9-period) EMA, slow (21-period) EMA, and a 14-period RSI.  The most
recent candle is examined for a bullish EMA crossover combined with an RSI
filter (40-70) to emit a **BUY** signal, a bearish EMA crossover to emit a
**SELL** signal, otherwise **HOLD**.

The function returns a tuple of (signal_string, indicator_dict).
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Tuple, Dict


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


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Compute Exponential Moving Average manually."""
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index manually."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def generate_signals(df: pd.DataFrame) -> Tuple[str, Dict[str, float]]:
    """Generate a trading signal from 5-minute candlestick data.

    Parameters
    ----------
    df : pandas.DataFrame
        Historical candlestick data with columns: ``open``, ``high``,
        ``low``, ``close``, and ``volume``.  Ordered chronologically,
        newest row last.

    Returns
    -------
    tuple[str, dict]
        A tuple of (signal, indicators) where signal is one of
        ``'BUY'``, ``'SELL'``, or ``'HOLD'`` and indicators is
        ``{'ema9': float, 'ema21': float, 'rsi': float}``.
    """
    _validate_dataframe(df)

    # Compute indicators
    close = df["close"]
    ema9  = _ema(close, 9)
    ema21 = _ema(close, 21)
    rsi14 = _rsi(close, 14)

    # Latest & previous values for crossover detection
    ema9_latest  = float(ema9.iloc[-1])
    ema21_latest = float(ema21.iloc[-1])
    rsi_latest   = float(rsi14.iloc[-1])

    ema9_prev  = float(ema9.iloc[-2])
    ema21_prev = float(ema21.iloc[-2])

    # Decision logic
    signal = "HOLD"
    if ema9_prev <= ema21_prev and ema9_latest > ema21_latest and 40 <= rsi_latest <= 70:
        signal = "BUY"
    elif ema9_prev >= ema21_prev and ema9_latest < ema21_latest:
        signal = "SELL"

    indicators = {
        "ema9":  round(ema9_latest, 4),
        "ema21": round(ema21_latest, 4),
        "rsi":   round(rsi_latest, 2),
    }

    return signal, indicators

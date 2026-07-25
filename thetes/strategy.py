"""strategy.py

Algorithmic day-trading signal generator.
"""

from __future__ import annotations

from typing import Tuple
import pandas as pd

from thetes.enums import Signal
from thetes.models import IndicatorValues
from thetes.indicators import ema, rsi


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
    _validate_dataframe(df)

    # Compute indicators
    close = df["close"]
    ema9_series = ema(close, 9)
    ema21_series = ema(close, 21)
    rsi14_series = rsi(close, 14)

    # Latest & previous values for crossover detection
    ema9_latest  = float(ema9_series.iloc[-1])
    ema21_latest = float(ema21_series.iloc[-1])
    rsi_latest   = float(rsi14_series.iloc[-1])

    ema9_prev  = float(ema9_series.iloc[-2])
    ema21_prev = float(ema21_series.iloc[-2])

    # Decision logic
    signal = Signal.HOLD
    if ema9_prev <= ema21_prev and ema9_latest > ema21_latest and 40 <= rsi_latest <= 70:
        signal = Signal.BUY
    elif ema9_prev >= ema21_prev and ema9_latest < ema21_latest:
        signal = Signal.SELL

    indicators = IndicatorValues(
        ema9=round(ema9_latest, 4),
        ema21=round(ema21_latest, 4),
        rsi=round(rsi_latest, 2),
    )

    return signal, indicators

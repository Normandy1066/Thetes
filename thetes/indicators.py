"""Pure technical-indicator calculations.

These are stateless helper functions with no trading-decision logic.
The strategy module consumes their output to generate signals.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class EmaState:
    value: float
    span: int


@dataclass
class RsiState:
    avg_gain: float
    avg_loss: float
    prev_close: float
    period: int


@dataclass
class AtrState:
    value: float
    prev_close: float
    period: int


def ema_incremental(price: float, span: int, state: EmaState) -> tuple[float, EmaState]:
    alpha = 2.0 / (span + 1.0)
    value = alpha * price + (1.0 - alpha) * state.value
    return value, EmaState(value=value, span=span)


def rsi_incremental(price: float, state: RsiState) -> tuple[float, RsiState]:
    gain = max(price - state.prev_close, 0.0)
    loss = max(state.prev_close - price, 0.0)
    avg_gain = (state.avg_gain * (state.period - 1) + gain) / state.period
    avg_loss = (state.avg_loss * (state.period - 1) + loss) / state.period
    if avg_loss == 0.0:
        rsi_val = 100.0
    else:
        rsi_val = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi_val, RsiState(avg_gain=avg_gain, avg_loss=avg_loss, prev_close=price, period=state.period)


def rsi_state_from_series(series: pd.Series, period: int = 14) -> RsiState:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return RsiState(
        avg_gain=float(avg_gain.iloc[-1]),
        avg_loss=float(avg_loss.iloc[-1]),
        prev_close=float(series.iloc[-1]),
        period=period,
    )


def atr_incremental(high: float, low: float, close: float, state: AtrState) -> tuple[float, AtrState]:
    tr = max(high - low, abs(high - state.prev_close), abs(low - state.prev_close))
    value = ((state.period - 1) * state.value + tr) / state.period
    return value, AtrState(value=value, prev_close=close, period=state.period)


def atr_state_from_series(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> AtrState:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return AtrState(value=float(atr_series.iloc[-1]), prev_close=float(close.iloc[-1]), period=period)


def ema(series: pd.Series, span: int) -> pd.Series:
    """Compute Exponential Moving Average.

    Parameters
    ----------
    series : pd.Series
        Price series (typically close prices).
    span : int
        Look-back window (e.g. 9, 21).

    Returns
    -------
    pd.Series
        EMA values aligned with the input index.
    """
    return series.ewm(span=span, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index.

    Parameters
    ----------
    series : pd.Series
        Price series (typically close prices).
    period : int
        Look-back period (default 14).

    Returns
    -------
    pd.Series
        RSI values in the range ``[0, 100]``.
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

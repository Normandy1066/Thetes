"""Pure technical-indicator calculations.

These are stateless helper functions with no trading-decision logic.
The strategy module consumes their output to generate signals.
"""

from __future__ import annotations

import pandas as pd


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

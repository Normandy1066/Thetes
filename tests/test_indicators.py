import pandas as pd
import numpy as np
from thetes.indicators import ema, rsi


def test_ema():
    # Construct basic series
    prices = pd.Series([10.0, 10.0, 10.0, 20.0, 20.0])
    ema_result = ema(prices, span=3)
    
    # First value should be equal to first price if adjust=False (default behavior)
    assert ema_result.iloc[0] == 10.0
    
    # Subsequent values should match the EMA formula:
    # multiplier = 2 / (span + 1) = 2 / 4 = 0.5
    # ema_t = price_t * multiplier + ema_t-1 * (1 - multiplier)
    # t=1: 10 * 0.5 + 10 * 0.5 = 10.0
    # t=2: 10 * 0.5 + 10 * 0.5 = 10.0
    # t=3: 20 * 0.5 + 10 * 0.5 = 15.0
    # t=4: 20 * 0.5 + 15 * 0.5 = 17.5
    assert ema_result.iloc[3] == 15.0
    assert ema_result.iloc[4] == 17.5


def test_rsi():
    # Constant series should have NaN or handle division by zero
    prices = pd.Series([10.0] * 20)
    rsi_result = rsi(prices, period=14)
    # The first 13 elements (since min_periods=14) should be NaN
    assert pd.isna(rsi_result.iloc[12])
    # The 14th element might be NaN or constant depending on gain/loss calculation
    # In pandas_ta/manual RSI, division by zero yields NaN
    assert pd.isna(rsi_result.iloc[19]) or np.isnan(rsi_result.iloc[19])

    # Upward trending series should have high RSI (close to 100)
    upward_prices = pd.Series(range(100, 125))
    upward_rsi = rsi(upward_prices, period=14)
    assert upward_rsi.iloc[-1] > 90.0

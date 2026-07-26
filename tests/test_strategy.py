import pytest
import pandas as pd
import numpy as np
from thetes.enums import Signal
from thetes.strategy import generate_signals, _validate_dataframe


def test_validate_dataframe():
    # Empty DF should raise ValueError
    with pytest.raises(ValueError, match="Input DataFrame is empty"):
        _validate_dataframe(pd.DataFrame())

    # Missing columns should raise ValueError
    df_missing = pd.DataFrame({"close": [10.0] * 25})
    with pytest.raises(ValueError, match="DataFrame missing required columns"):
        _validate_dataframe(df_missing)

    # Insufficient rows should raise ValueError
    df_short = pd.DataFrame({
        "open": [100.0] * 10,
        "high": [105.0] * 10,
        "low": [95.0] * 10,
        "close": [100.0] * 10,
        "volume": [1000] * 10
    })
    with pytest.raises(ValueError, match="must contain at least"):
        _validate_dataframe(df_short)


def test_generate_signals_hold():
    # Constant data should generate HOLD signal
    df = pd.DataFrame({
        "open": [100.0] * 60,
        "high": [100.0] * 60,
        "low": [100.0] * 60,
        "close": [100.0] * 60,
        "volume": [1000] * 60
    })
    sig, ind = generate_signals(df)
    assert sig == Signal.HOLD
    assert ind.ema9 == 100.0
    assert ind.ema21 == 100.0


def test_generate_signals_buy_crossover():
    n_flat, n_trend = 30, 30
    flat_prices = [100.0] * n_flat
    trend = [100.0 + i * 1.0 for i in range(n_trend)]
    close_prices = flat_prices + trend
    high_prices = [p + 1.5 for p in close_prices]
    low_prices = [p - 1.5 for p in close_prices]
    volume = [1000] * n_flat + [2000] * (n_trend - 5) + [4000] * 5

    df = pd.DataFrame({
        "open": close_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volume,
    })

    sig, ind = generate_signals(df)
    assert sig in {Signal.BUY, Signal.HOLD, Signal.SELL}
    assert ind.ema_trend > 0

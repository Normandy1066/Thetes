"""data.py
Utility module for fetching recent candle data. For this stress test we generate synthetic data.
"""

from __future__ import annotations
import os
import logging
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


def get_latest_candles(symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
    """Generate mock candle data for the given symbol.

    Parameters
    ----------
    symbol: str
        Ticker symbol (unused in mock).
    timeframe: str, optional
        Timeframe string (must be '5Min' for this mock).
    limit: int, optional
        Number of rows to generate.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ['open','high','low','close','volume'] sorted by timestamp ascending.
    """
    logging.info("Generating mock candle data for %s", symbol)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq='5min')
    data = {
        "open": np.random.uniform(100, 200, size=limit),
        "high": np.random.uniform(200, 300, size=limit),
        "low": np.random.uniform(50, 100, size=limit),
        "close": np.random.uniform(100, 200, size=limit),
        "volume": np.random.randint(1000, 10000, size=limit),
    }
    df = pd.DataFrame(data, index=dates)
    df.sort_index(inplace=True)
    return df[["open", "high", "low", "close", "volume"]]

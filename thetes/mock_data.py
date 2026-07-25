"""mock_data.py

Mock candlestick data generator implementation of MarketDataProvider.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from thetes.data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MockDataProvider(MarketDataProvider):
    """Generates synthetic candlestick data for testing/development."""

    def get_candles(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
        """Generate mock candle data for the given symbol."""
        logger.info("Generating mock candle data for %s", symbol)
        
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

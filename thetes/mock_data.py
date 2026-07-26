"""mock_data.py

Mock candlestick data generator implementation of MarketDataProvider.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np
import pandas as pd

from thetes.data_provider import BarUpdate, MarketDataProvider

logger = logging.getLogger(__name__)


class MockDataProvider(MarketDataProvider):
    """Generates synthetic candlestick data for testing/development."""

    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._callback: Callable[[BarUpdate], None] | None = None

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

    def subscribe_bars(self, symbol: str, callback: Callable[[BarUpdate], None], timeframe: str = "5Min") -> None:
        """Simulate bar updates with a periodic timer."""
        self._callback = callback
        self._schedule_next_bar()

    def _schedule_next_bar(self) -> None:
        minutes = 5
        self._timer = threading.Timer(minutes * 60, self._emit_bar)
        self._timer.daemon = True
        self._timer.start()

    def _emit_bar(self) -> None:
        if self._callback is None:
            return
        bar = BarUpdate(
            timestamp=pd.Timestamp.now(),
            open=float(np.random.uniform(100, 200)),
            high=float(np.random.uniform(200, 300)),
            low=float(np.random.uniform(50, 100)),
            close=float(np.random.uniform(100, 200)),
            volume=float(np.random.randint(1000, 10000)),
        )
        self._callback(bar)
        self._schedule_next_bar()

    def unsubscribe(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._callback = None

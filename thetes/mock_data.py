"""mock_data.py

Mock candlestick data generator implementation of MarketDataProvider.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict

import numpy as np
import pandas as pd

from thetes.data_provider import BarUpdate, MarketDataProvider

logger = logging.getLogger(__name__)

_PER_SYMBOL_SEEDS: Dict[str, int] = {}


class MockDataProvider(MarketDataProvider):
    """Generates synthetic candlestick data for testing/development."""

    def __init__(self) -> None:
        self._callbacks: Dict[str, Callable[[BarUpdate], None]] = {}
        self._timer: threading.Timer | None = None
        self._timeframe_minutes: int = 5

    def get_candles(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
        """Generate mock candle data for the given symbol."""
        logger.info("Generating mock candle data for %s", symbol)
        rng = np.random.default_rng(_PER_SYMBOL_SEEDS.setdefault(symbol, hash(symbol) % (2**31)))

        dates = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq="5min")
        data = {
            "open": rng.uniform(100, 200, size=limit),
            "high": rng.uniform(200, 300, size=limit),
            "low": rng.uniform(50, 100, size=limit),
            "close": rng.uniform(100, 200, size=limit),
            "volume": rng.integers(1000, 10000, size=limit),
        }
        df = pd.DataFrame(data, index=dates)
        df.sort_index(inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    def subscribe_bars(self, symbols: list[str], callback: Callable[[BarUpdate], None], timeframe: str = "5Min") -> None:
        """Simulate bar updates with a periodic timer for all *symbols*."""
        for symbol in symbols:
            self._callbacks[symbol] = callback
        # Parse timeframe minutes (e.g. "5Min" -> 5)
        tf = timeframe.lower().replace("min", "").replace("minute", "")
        self._timeframe_minutes = max(1, int(tf) if tf.isdigit() else 5)
        if self._timer is None:
            self._schedule_next_bar()

    def _schedule_next_bar(self) -> None:
        self._timer = threading.Timer(self._timeframe_minutes * 60, self._emit_bars)
        self._timer.daemon = True
        self._timer.start()

    def _emit_bars(self) -> None:
        for symbol, callback in list(self._callbacks.items()):
            rng = np.random.default_rng()
            bar = BarUpdate(
                symbol=symbol,
                timestamp=pd.Timestamp.now(),
                open=float(rng.uniform(100, 200)),
                high=float(rng.uniform(200, 300)),
                low=float(rng.uniform(50, 100)),
                close=float(rng.uniform(100, 200)),
                volume=float(rng.integers(1000, 10000)),
            )
            callback(bar)
        self._schedule_next_bar()

    def unsubscribe(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._callbacks.clear()

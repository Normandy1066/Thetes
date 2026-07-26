"""data_provider.py

Abstract interface for market data ingestion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd


@dataclass
class BarUpdate:
    symbol: str
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataProvider(ABC):
    """Abstract base class representing a market data provider interface."""

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
        """Fetch historical candlestick data.

        Parameters
        ----------
        symbol : str
            Ticker symbol to fetch data for.
        timeframe : str, optional
            Timeframe interval (e.g. "5Min").
        limit : int, optional
            Maximum number of candle bars to fetch.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
            indexed/sorted by timestamp ascending.
        """
        pass

    def subscribe_bars(self, symbols: list[str], callback: Callable[[BarUpdate], None], timeframe: str = "5Min") -> None:
        """Subscribe to real-time bar (candle) updates for one or more symbols.

        The *callback* is invoked on a background thread each time a new
        candle closes.  Default implementation is a no-op.
        """
        pass

    def update_subscription(self, symbols: list[str]) -> None:
        """Replace the set of subscribed symbols at runtime.

        Providers override this to re-subscribe without restarting the
        entire application.  Default is a no-op.
        """

    def unsubscribe(self) -> None:
        """Unsubscribe from all real-time streams.  Default is a no-op."""
        pass

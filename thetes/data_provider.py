"""data_provider.py

Abstract interface for market data ingestion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import pandas as pd


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

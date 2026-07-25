"""alpaca_data.py

Real candlestick data provider using Alpaca API.
"""

from __future__ import annotations

import logging
import pandas as pd
from datetime import datetime, timedelta

from thetes.data_provider import MarketDataProvider
from thetes.config import Config

logger = logging.getLogger(__name__)

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
except ImportError:
    StockHistoricalDataClient = None


class AlpacaDataProvider(MarketDataProvider):
    """Fetches real historical candlestick data from Alpaca."""

    def __init__(self, config: Config) -> None:
        if StockHistoricalDataClient is None:
            raise RuntimeError("Alpaca SDK is not installed. Run `pip install alpaca-py`.")
            
        if not config.alpaca_api_key or not config.alpaca_secret_key or config.alpaca_api_key.startswith("YOUR_"):
            raise RuntimeError("Valid Alpaca API credentials are required to fetch real data.")
            
        self._client = StockHistoricalDataClient(
            config.alpaca_api_key,
            config.alpaca_secret_key
        )

    def get_candles(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
        """Fetch historical 5-minute candles using Alpaca API."""
        logger.info("Fetching real candle data for %s", symbol)
        
        # Pull data from the last few days to ensure we have enough bars even over weekends
        start_time = datetime.utcnow() - timedelta(days=7)
        
        # We assume 5Min timeframe by default based on the architecture
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start_time,
            limit=limit
        )
        
        bars = self._client.get_stock_bars(request_params)
        if not bars or symbol not in bars.data:
            return pd.DataFrame()
            
        df = bars.df.loc[symbol].copy()
        
        # CRUCIAL: Sort chronologically (oldest to newest) to prevent indicator lag
        df.sort_index(ascending=True, inplace=True)
        
        return df[["open", "high", "low", "close", "volume"]]

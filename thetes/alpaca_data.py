"""alpaca_data.py

Real candlestick data provider using Alpaca API.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd

from thetes.data_provider import BarUpdate, MarketDataProvider
from thetes.config import Config

logger = logging.getLogger(__name__)

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.live import StockDataStream
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
except ImportError:
    StockHistoricalDataClient = None
    StockDataStream = None


class AlpacaDataProvider(MarketDataProvider):
    """Fetches real historical candlestick data from Alpaca."""

    def __init__(self, config: Config) -> None:
        if StockHistoricalDataClient is None:
            raise RuntimeError("Alpaca SDK is not installed. Run `pip install alpaca-py`.")
            
        if not config.alpaca_api_key or not config.alpaca_secret_key or config.alpaca_api_key.startswith("YOUR_"):
            raise RuntimeError("Valid Alpaca API credentials are required to fetch real data.")
            
        self._api_key = config.alpaca_api_key
        self._secret_key = config.alpaca_secret_key
        self._client = StockHistoricalDataClient(
            config.alpaca_api_key,
            config.alpaca_secret_key
        )
        self._stream: StockDataStream | None = None
        self._stream_thread: threading.Thread | None = None
        self._callback: Callable[[BarUpdate], None] | None = None

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

    def subscribe_bars(self, symbol: str, callback: Callable[[BarUpdate], None], timeframe: str = "5Min") -> None:
        """Subscribe to real-time bar updates via Alpaca WebSocket."""
        if StockDataStream is None:
            logger.warning("Alpaca WebSocket not available, falling back to polling")
            return

        self._callback = callback
        self._stream = StockDataStream(self._api_key, self._secret_key)
        self._stream.subscribe_bars(self._on_bar_async, symbol)

        def _run_stream() -> None:
            try:
                asyncio.run(self._stream.run())
            except Exception as exc:
                logger.error("Alpaca WebSocket stream stopped: %s", exc)

        self._stream_thread = threading.Thread(target=_run_stream, daemon=True)
        self._stream_thread.start()
        logger.info("Subscribed to real-time bars for %s", symbol)

    async def _on_bar_async(self, bar: object) -> None:
        if self._callback is None:
            return
        try:
            update = BarUpdate(
                timestamp=pd.Timestamp(bar.timestamp),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            self._callback(update)
        except Exception as exc:
            logger.error("Error processing bar update: %s", exc)

    def unsubscribe(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                logger.debug("Error stopping stream: %s", exc)
            self._stream = None
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=3.0)
            self._stream_thread = None
        self._callback = None
        logger.info("Unsubscribed from real-time bars")

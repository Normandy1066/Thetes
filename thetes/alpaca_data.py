"""alpaca_data.py

Real candlestick data provider using Alpaca API.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict

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
        self._callbacks: Dict[str, Callable[[BarUpdate], None]] = {}
        self._stream: StockDataStream | None = None
        self._stream_thread: threading.Thread | None = None

    def get_candles(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> pd.DataFrame:
        """Fetch historical 5-minute candles using Alpaca API."""
        logger.info("Fetching real candle data for %s", symbol)

        start_time = datetime.utcnow() - timedelta(days=7)

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
        df.sort_index(ascending=True, inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    def update_subscription(self, symbols: list[str]) -> None:
        """Replace the Alpaca WebSocket subscription (full stop + restart)."""
        cb = next(iter(self._callbacks.values())) if self._callbacks else None
        self.unsubscribe()
        if cb is not None:
            self.subscribe_bars(symbols, cb)

    def subscribe_bars(self, symbols: list[str], callback: Callable[[BarUpdate], None], timeframe: str = "5Min") -> None:
        """Subscribe to real-time bar updates via Alpaca WebSocket.

        Issues a single ``subscribe_bars`` call for all *symbols* to avoid
        duplicate websocket subscriptions.
        """
        if StockDataStream is None:
            logger.warning("Alpaca WebSocket not available, falling back to polling")
            return

        for symbol in symbols:
            self._callbacks[symbol] = callback
        if self._stream is None:
            self._stream = StockDataStream(self._api_key, self._secret_key)

        self._stream.subscribe_bars(self._on_bar_async, *symbols)

        def _run_stream() -> None:
            if self._stream is not None:
                try:
                    asyncio.run(self._stream.run())
                except Exception as exc:
                    logger.error("Alpaca WebSocket stream stopped: %s", exc)

        if self._stream_thread is None:
            self._stream_thread = threading.Thread(target=_run_stream, daemon=True)
            self._stream_thread.start()

        logger.info("Subscribed to real-time bars for %s", symbol)

    async def _on_bar_async(self, bar: object) -> None:
        symbol = getattr(bar, "symbol", "")
        callback = self._callbacks.get(symbol)
        if callback is None:
            return
        try:
            update = BarUpdate(
                symbol=symbol,
                timestamp=pd.Timestamp(bar.timestamp),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            callback(update)
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
        self._callbacks.clear()
        logger.info("Unsubscribed from real-time bars")

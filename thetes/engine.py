"""engine.py

Core trading engine coordinating data ingestion, signal generation, and order execution.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Dict, Any

import pandas as pd

from thetes.broker import Broker
from thetes.config import Config
from thetes.data_provider import BarUpdate, MarketDataProvider
from thetes.enums import BotStatus, Signal
from thetes.models import AccountSnapshot, BotState, MarketState, TradeLogEntry, IndicatorValues
from thetes.risk_manager import RiskManager
from thetes.strategy import IndicatorCache, generate_signals_cached

logger = logging.getLogger(__name__)


class TradingEngine:
    """Manages the lifecycle, background thread, and state of the trading bot."""

    def __init__(self, config: Config, broker: Broker, data_provider: MarketDataProvider, risk_manager: RiskManager | None = None) -> None:
        self.config = config
        self.broker = broker
        self.data_provider = data_provider
        self.risk_manager = risk_manager or RiskManager(config, broker)

        # Thread synchronization
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._indicator_cache: IndicatorCache | None = None
        self._candle_buffer: pd.DataFrame | None = None
        self._pending_bars: list[BarUpdate] = []
        self._bar_event = threading.Event()
        self._account_cache: AccountSnapshot | None = None

        # Setup initial state
        with self._state_lock:
            self._state = BotState(
                status=BotStatus.STOPPED,
                symbol=config.trading_symbol,
                trade_qty=config.trade_qty,
                loop_delay=config.loop_delay_seconds,
            )

    def start(self, symbol: str | None = None, trade_qty: float | None = None, loop_delay: int | None = None) -> None:
        """Start the background bot thread.

        Optionally override the target symbol, trade quantity, or loop delay on start.
        """
        # Fetch account snapshot outside the lock to prevent deadlocks during network latency
        initial_account = None
        try:
            initial_account = self.broker.get_account()
        except Exception as exc:
            logger.error("Failed to retrieve initial account balance: %s", exc)

        with self._state_lock:
            if self._state.status == BotStatus.RUNNING:
                logger.warning("Attempted to start engine, but it is already running.")
                return

            # Apply overrides or default to current settings
            if symbol is not None:
                self._state.symbol = symbol
            if trade_qty is not None:
                self._state.trade_qty = trade_qty
            if loop_delay is not None:
                self._state.loop_delay = loop_delay

            # Reset dynamic state
            self._state.status = BotStatus.RUNNING
            self._state.iteration = 0
            self._state.total_trades = 0
            self._state.buy_count = 0
            self._state.sell_count = 0
            self._state.started_at = datetime.datetime.now().isoformat()
            self._state.trade_log.clear()
            self._state.price_history.clear()
            self._state.signal_history.clear()
            self._indicator_cache = None
            self._candle_buffer = None
            self._pending_bars.clear()
            self._bar_event.clear()
            self.risk_manager.reset()

            if initial_account:
                self._state.account = initial_account

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info("Trading engine started. Thread spawned successfully.")

    def stop(self) -> None:
        """Stop the background bot thread."""
        with self._state_lock:
            if self._state.status == BotStatus.STOPPED:
                logger.warning("Attempted to stop engine, but it is already stopped.")
                return

            self._state.status = BotStatus.STOPPED
            self._stop_event.set()
            self._bar_event.set()

        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("Trading engine stopped.")

    def get_state(self) -> BotState:
        """Return a snapshot of the current state under lock."""
        with self._state_lock:
            return self._state

    def get_state_dict(self) -> dict:
        """Return a JSON-serializable dictionary representation of the bot state."""
        with self._state_lock:
            return self._state.to_api_dict()

    def run_once(self) -> None:
        """Execute a single iteration of the trading logic (legacy polling path).

        Fetches candle data from the provider, then runs the strategy,
        risk check, and order execution.  Kept for backward compatibility;
        the background loop uses the event-driven path instead.
        """
        with self._state_lock:
            symbol = self._state.symbol
            qty = self._state.trade_qty
            iteration = self._state.iteration

        df: pd.DataFrame | None = None
        try:
            if self._candle_buffer is None:
                df = self.data_provider.get_candles(symbol, timeframe="5Min", limit=100)
                if df.empty:
                    logger.warning("Data fetch returned empty DataFrame for %s", symbol)
                    return
                self._candle_buffer = df
                try:
                    self._account_cache = self.broker.get_account()
                except Exception:
                    pass
            else:
                new_rows = self.data_provider.get_candles(symbol, timeframe="5Min", limit=2)
                if not new_rows.empty:
                    last_ts = self._candle_buffer.index[-1]
                    fresh = new_rows[new_rows.index > last_ts]
                    if not fresh.empty:
                        self._candle_buffer = pd.concat([self._candle_buffer, fresh])
                        if len(self._candle_buffer) > 100:
                            self._candle_buffer = self._candle_buffer.iloc[-100:]
                df = self._candle_buffer
        except Exception as exc:
            logger.error("Error fetching candle data: %s", exc)
            return

        self._execute(df, symbol, qty, iteration)

    def _execute(self, df: pd.DataFrame, symbol: str, qty: float, iteration: int) -> None:
        """Core strategy execution on a prepared DataFrame."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = TradeLogEntry(timestamp=ts, iteration=iteration)

        last_close = float(df["close"].iloc[-1])
        entry.close_price = round(last_close, 2)

        # Signal
        signal_val = Signal.HOLD
        indicators_val = IndicatorValues()
        try:
            signal_val, indicators_val, self._indicator_cache = generate_signals_cached(
                df, self._indicator_cache
            )
            entry.signal = signal_val.value
            entry.indicators = indicators_val
        except Exception as exc:
            entry.error = f"Signal error: {exc}"
            logger.error("Error generating signal: %s", exc)

        # Risk check
        risk_decision = None
        if last_close > 0:
            risk_decision = self.risk_manager.evaluate(signal_val, last_close, df, qty)

        # Order execution
        action = "HOLD"
        if signal_val == Signal.BUY and risk_decision is not None and risk_decision.is_allowed:
            try:
                self.broker.buy(symbol, risk_decision.position_size, price=last_close)
                action = "BUY ORDER PLACED"
            except Exception as exc:
                action = f"BUY FAILED: {exc}"
                logger.error("Buy order failed for %s: %s", symbol, exc)
        elif signal_val == Signal.SELL and risk_decision is not None and risk_decision.is_allowed:
            try:
                self.broker.sell(symbol, risk_decision.position_size, price=last_close)
                action = "SELL ORDER PLACED"
            except Exception as exc:
                action = f"SELL FAILED: {exc}"
                logger.error("Sell order failed for %s: %s", symbol, exc)

        entry.action = action

        # Account snapshot (only fetch on trade, use cache otherwise)
        placed_trade = action in ("BUY ORDER PLACED", "SELL ORDER PLACED")
        if placed_trade:
            try:
                self._account_cache = self.broker.get_account()
            except Exception as exc:
                logger.error("Failed to retrieve account snapshot: %s", exc)
        if self._account_cache is not None:
            entry.cash = self._account_cache.cash
            entry.buying_power = self._account_cache.buying_power

        with self._state_lock:
            self._state.market.last_close = last_close
            self._state.market.last_signal = signal_val
            self._state.market.indicators = indicators_val
            self._state.price_history.append({"t": ts, "price": round(last_close, 2)})
            self._state.signal_history.append({"t": ts, "signal": signal_val.value})
            if placed_trade:
                if action == "BUY ORDER PLACED":
                    self._state.buy_count += 1
                else:
                    self._state.sell_count += 1
                self._state.total_trades += 1
                if self._account_cache is not None:
                    self._state.account = self._account_cache
            self._state.trade_log.appendleft(entry)

    def _on_bar(self, bar: BarUpdate) -> None:
        """Thread-safe callback invoked by the data provider on candle close."""
        with self._state_lock:
            self._pending_bars.append(bar)
        self._bar_event.set()

    def _loop(self) -> None:
        """Event-driven background loop.  Waits for bar updates instead of polling."""
        logger.info("Starting event-driven trading loop.")
        max_iters = self.config.max_iterations

        with self._state_lock:
            symbol = self._state.symbol

        # Initialise the candle buffer with historical data
        try:
            df = self.data_provider.get_candles(symbol, timeframe="5Min", limit=100)
            if df.empty:
                logger.error("Failed to fetch initial candle data for %s", symbol)
                with self._state_lock:
                    self._state.status = BotStatus.STOPPED
                return
            self._candle_buffer = df
            self._account_cache = self.broker.get_account()
            with self._state_lock:
                self._state.market.last_close = float(df["close"].iloc[-1])
                self._state.account = self._account_cache
        except Exception as exc:
            logger.error("Failed to fetch initial candle data: %s", exc)
            with self._state_lock:
                self._state.status = BotStatus.STOPPED
            return

        # Subscribe to real-time bar updates
        self.data_provider.subscribe_bars(symbol, self._on_bar, "5Min")

        while not self._stop_event.is_set():
            self._bar_event.wait(timeout=5.0)
            self._bar_event.clear()
            if self._stop_event.is_set():
                break

            # Drain pending bars under lock
            with self._state_lock:
                bars = list(self._pending_bars)
                self._pending_bars.clear()
                self._state.iteration += 1
                iteration = self._state.iteration
                qty = self._state.trade_qty

            if not bars:
                continue

            new_rows = pd.DataFrame(
                [(b.open, b.high, b.low, b.close, b.volume) for b in bars],
                columns=["open", "high", "low", "close", "volume"],
                index=[b.timestamp for b in bars],
            )
            self._candle_buffer = pd.concat([self._candle_buffer, new_rows])
            if len(self._candle_buffer) > 100:
                self._candle_buffer = self._candle_buffer.iloc[-100:]

            logger.info("Processing %d new candle(s) [iteration #%d]", len(bars), iteration)
            self._execute(self._candle_buffer, symbol, qty, iteration)

            if max_iters is not None and iteration >= max_iters:
                logger.info("Reached maximum configured iterations (%d). Stopping engine.", max_iters)
                with self._state_lock:
                    self._state.status = BotStatus.STOPPED
                break

        self.data_provider.unsubscribe()
        logger.info("Event-driven trading loop terminated.")

"""engine.py

Core trading engine coordinating data ingestion, signal generation, and order execution.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Dict, Any

from thetes.config import Config
from thetes.broker import Broker
from thetes.data_provider import MarketDataProvider
from thetes.enums import BotStatus, Signal
from thetes.models import BotState, MarketState, TradeLogEntry, IndicatorValues
from thetes.risk_manager import RiskManager
from thetes.strategy import generate_signals

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

        Optionally overrides the current symbol, trade quantity, or loop delay.
        """
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

            # Refresh account snapshot at start
            try:
                self._state.account = self.broker.get_account()
            except Exception as exc:
                logger.error("Failed to retrieve initial account balance: %s", exc)

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

        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("Trading engine stopped.")

    def get_state(self) -> BotState:
        """Return a snapshot of the current state under lock."""
        with self._state_lock:
            # We copy/clone fields as appropriate to avoid thread conflicts if needed,
            # but returning self._state is typically sufficient if fields are accessed carefully.
            return self._state

    def get_state_dict(self) -> dict:
        """Return a JSON-serializable dictionary representation of the bot state."""
        with self._state_lock:
            return self._state.to_api_dict()

    def run_once(self) -> None:
        """Execute a single iteration of the trading logic.

        This contains granular exception boundaries to catch failures at individual steps
        without crashing the bot.
        """
        # Fetch configurations under lock
        with self._state_lock:
            symbol = self._state.symbol
            qty = self._state.trade_qty
            iteration = self._state.iteration

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = TradeLogEntry(timestamp=ts, iteration=iteration)

        # Step 1: Fetch candle data
        df = None
        last_close = 0.0
        try:
            df = self.data_provider.get_candles(symbol, timeframe="5Min", limit=100)
            if df.empty:
                entry.error = "No candle data retrieved"
                logger.warning("Data fetch returned empty DataFrame for %s", symbol)
            else:
                last_close = float(df["close"].iloc[-1])
                with self._state_lock:
                    self._state.market.last_close = last_close
                    self._state.price_history.append({"t": ts, "price": round(last_close, 2)})
                entry.close_price = round(last_close, 2)
        except Exception as exc:
            entry.error = f"Data fetch error: {exc}"
            logger.error("Error fetching candle data: %s", exc)

        # Step 2: Generate signal
        signal_val = Signal.HOLD
        indicators_val = IndicatorValues()
        if df is not None and not df.empty:
            try:
                signal_val, indicators_val = generate_signals(df)
                with self._state_lock:
                    self._state.market.last_signal = signal_val
                    self._state.market.indicators = indicators_val
                    self._state.signal_history.append({"t": ts, "signal": signal_val.value})
                entry.signal = signal_val.value
                entry.indicators = indicators_val
            except Exception as exc:
                entry.error = f"Signal error: {exc}"
                logger.error("Error generating signal: %s", exc)

        # Step 3: Risk check
        risk_decision = None
        if df is not None and not df.empty and last_close > 0:
            risk_decision = self.risk_manager.evaluate(signal_val, last_close, df, qty)

        # Step 4: Order Execution
        action = "HOLD"
        if signal_val == Signal.BUY and df is not None and not df.empty and risk_decision and risk_decision.is_allowed:
            try:
                self.broker.buy(symbol, risk_decision.position_size, price=last_close)
                action = "BUY ORDER PLACED"
                with self._state_lock:
                    self._state.buy_count += 1
                    self._state.total_trades += 1
            except Exception as exc:
                action = f"BUY FAILED: {exc}"
                logger.error("Buy order failed for %s: %s", symbol, exc)
        elif signal_val == Signal.SELL and df is not None and not df.empty and risk_decision and risk_decision.is_allowed:
            try:
                self.broker.sell(symbol, risk_decision.position_size, price=last_close)
                action = "SELL ORDER PLACED"
                with self._state_lock:
                    self._state.sell_count += 1
                    self._state.total_trades += 1
            except Exception as exc:
                action = f"SELL FAILED: {exc}"
                logger.error("Sell order failed for %s: %s", symbol, exc)

        entry.action = action

        # Step 5: Account Snapshot
        try:
            acct = self.broker.get_account()
            with self._state_lock:
                self._state.account = acct
            entry.cash = acct.cash
            entry.buying_power = acct.buying_power
        except Exception as exc:
            logger.error("Failed to retrieve account snapshot: %s", exc)

        # Append entry to log history
        with self._state_lock:
            self._state.trade_log.appendleft(entry)

    def _loop(self) -> None:
        """Background thread target that runs the trading loop."""
        logger.info("Starting background trading loop.")
        
        # Check iteration boundaries if set
        max_iters = self.config.max_iterations

        while not self._stop_event.is_set():
            # Update iteration count under lock
            with self._state_lock:
                self._state.iteration += 1
                current_iter = self._state.iteration
                delay = self._state.loop_delay

            logger.info("Executing loop iteration #%d", current_iter)
            self.run_once()

            if max_iters is not None and current_iter >= max_iters:
                logger.info("Reached maximum configured iterations (%d). Stopping engine.", max_iters)
                with self._state_lock:
                    self._state.status = BotStatus.STOPPED
                break

            # Sleep or handle stop event
            # Sleep in short increments of 100ms so stopping is responsive
            for _ in range(delay * 10):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

        logger.info("Background trading loop terminated.")

"""engine.py

Core trading engine coordinating data ingestion, signal generation, and order execution.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Dict, Any, Optional

import pandas as pd

from thetes.broker import Broker
from thetes.config import Config
from thetes.data_provider import BarUpdate, MarketDataProvider
from thetes.enums import BotStatus, Signal
from thetes.models import (
    AccountSnapshot,
    BotState,
    IndicatorValues,
    SymbolContext,
    TradeLogEntry,
)
from thetes.risk_manager import RiskManager
from thetes.strategy import generate_signals_cached

logger = logging.getLogger(__name__)


class TradingEngine:
    """Manages the lifecycle, background thread, and state of the trading bot."""

    def __init__(
        self,
        config: Config,
        broker: Broker,
        data_provider: MarketDataProvider,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        self.config = config
        self.broker = broker
        self.data_provider = data_provider
        self.risk_manager = risk_manager or RiskManager(config, broker)

        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_bars: list[BarUpdate] = []
        self._bar_event = threading.Event()
        self._account_cache: AccountSnapshot | None = None

        symbols = config.trading_symbols or (config.trading_symbol,)
        with self._state_lock:
            self._state = BotState(
                status=BotStatus.STOPPED,
                symbol=symbols[0],
                trading_symbols=symbols,
                trade_qty=config.trade_qty,
                loop_delay=config.loop_delay_seconds,
                symbols={
                    s: SymbolContext(symbol=s, trade_qty=config.trade_qty)
                    for s in symbols
                },
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        symbol: Optional[str] = None,
        trade_qty: Optional[float] = None,
        loop_delay: Optional[int] = None,
    ) -> None:
        """Start the background bot thread."""
        initial_account = None
        try:
            initial_account = self.broker.get_account()
        except Exception as exc:
            logger.error("Failed to retrieve initial account balance: %s", exc)

        with self._state_lock:
            if self._state.status == BotStatus.RUNNING:
                logger.warning("Attempted to start engine, but it is already running.")
                return

            if symbol is not None:
                if symbol in self._state.trading_symbols:
                    self._state.symbol = symbol
                else:
                    logger.warning(
                        "Symbol %r is not in the tracked list %s; ignoring start override.",
                        symbol, self._state.trading_symbols,
                    )
            if trade_qty is not None:
                self._state.trade_qty = trade_qty
            if loop_delay is not None:
                self._state.loop_delay = loop_delay

            self._state.status = BotStatus.RUNNING
            self._state.iteration = 0
            self._state.total_trades = 0
            self._state.buy_count = 0
            self._state.sell_count = 0
            self._state.started_at = datetime.datetime.now().isoformat()
            self._state.trade_log.clear()
            self._state.price_history.clear()
            self._state.signal_history.clear()
            self._pending_bars.clear()
            self._bar_event.clear()
            self.risk_manager.reset()

            symbols = self._state.trading_symbols
            self._state.symbols = {
                s: SymbolContext(symbol=s, trade_qty=self._state.trade_qty)
                for s in symbols
            }

            if initial_account:
                self._state.account = initial_account

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info("Trading engine started with symbols=%s", symbols)

    def stop(self) -> None:
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

    # ------------------------------------------------------------------
    # Runtime symbol management
    # ------------------------------------------------------------------

    def replace_symbols(self, symbols: list[str]) -> None:
        """Replace the active symbol list at runtime.

        Existing ``SymbolContext`` objects are preserved when the symbol
        is in both the old and new list; new ones are created with an
        empty candle buffer.  Removed entries are discarded.

        Thread-safe: acquires ``_state_lock``.
        """
        with self._state_lock:
            old = self._state.symbols
            new: dict[str, SymbolContext] = {}
            for s in symbols:
                if s in old:
                    new[s] = old[s]
                else:
                    new[s] = SymbolContext(symbol=s, trade_qty=self._state.trade_qty)
            self._state.symbols = new
            self._state.trading_symbols = tuple(symbols)
            self._state.symbol = symbols[0]

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    def get_state(self) -> BotState:
        with self._state_lock:
            self._sync_primary_state()
            return self._state

    def get_state_dict(self) -> dict:
        with self._state_lock:
            self._sync_primary_state()
            return self._state.to_api_dict()

    def _sync_primary_state(self) -> None:
        """Mirror the primary symbol into the single-symbol fields for backward compat."""
        symbols = self._state.symbols
        prim = self._state.primary_symbol
        ctx = symbols.get(prim)
        if ctx is not None:
            self._state.market.last_close = ctx.last_close
            self._state.market.last_signal = ctx.last_signal
            if ctx.last_indicators is not None:
                self._state.market.indicators = ctx.last_indicators

    # ------------------------------------------------------------------
    # Polling path (legacy / manual)
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """Execute a single iteration for all active symbols."""
        with self._state_lock:
            self._state.iteration += 1
            iteration = self._state.iteration
            symbols = list(self._state.symbols.keys())

        for symbol in symbols:
            ctx = self._symbol_ctx(symbol)
            if ctx is None:
                continue

            try:
                if ctx.candle_buffer is None:
                    df = self.data_provider.get_candles(
                        symbol, timeframe="5Min", limit=100
                    )
                    if df.empty:
                        logger.warning("Data fetch returned empty DataFrame for %s", symbol)
                        continue
                    ctx.candle_buffer = df
                else:
                    new_rows = self.data_provider.get_candles(
                        symbol, timeframe="5Min", limit=2
                    )
                    if not new_rows.empty:
                        last_ts = ctx.candle_buffer.index[-1]
                        fresh = new_rows[new_rows.index > last_ts]
                        if not fresh.empty:
                            ctx.candle_buffer = pd.concat(
                                [ctx.candle_buffer, fresh]
                            )
                            if len(ctx.candle_buffer) > 100:
                                ctx.candle_buffer = ctx.candle_buffer.iloc[-100:]
            except Exception as exc:
                logger.error("Error fetching candle data for %s: %s", symbol, exc)
                continue

            self._execute_symbol(symbol, iteration)

    # ------------------------------------------------------------------
    # Per-symbol execution
    # ------------------------------------------------------------------

    def _symbol_ctx(self, symbol: str) -> Optional[SymbolContext]:
        return self._state.symbols.get(symbol)

    def _execute_symbol(self, symbol: str, iteration: int) -> None:
        """Run strategy, risk check, and order execution for one symbol."""
        ctx = self._symbol_ctx(symbol)
        if ctx is None or ctx.candle_buffer is None:
            return

        df = ctx.candle_buffer
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = TradeLogEntry(timestamp=ts, iteration=iteration, symbol=symbol)

        last_close = float(df["close"].iloc[-1])
        entry.close_price = round(last_close, 2)

        # --- Signal ---
        signal_val = Signal.HOLD
        indicators_val = IndicatorValues()
        try:
            signal_val, indicators_val, ctx.indicator_cache = generate_signals_cached(
                df, ctx.indicator_cache
            )
            entry.signal = signal_val.value
            entry.indicators = indicators_val
        except Exception as exc:
            entry.error = f"Signal error: {exc}"
            logger.error("Error generating signal for %s: %s", symbol, exc)

        # --- Risk check ---
        risk_decision = None
        if last_close > 0:
            risk_decision = self.risk_manager.evaluate(
                signal_val,
                last_close,
                df,
                ctx.trade_qty,
                symbol=symbol,
                account=self._account_cache,
                atr_val=indicators_val.atr,
            )

        # --- Order execution ---
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

        # --- Account snapshot after trade ---
        placed_trade = "ORDER PLACED" in action
        if placed_trade:
            try:
                self._account_cache = self.broker.get_account()
            except Exception as exc:
                logger.error("Failed to retrieve account snapshot: %s", exc)

        # --- Portfolio PnL with current prices for all symbols ---
        pm = self.broker.portfolio_manager
        if pm is not None and last_close > 0:
            try:
                prices: Dict[str, float] = {}
                for sym, c in self._state.symbols.items():
                    if c.last_close > 0:
                        prices[sym] = c.last_close
                prices[symbol] = last_close
                self._account_cache = pm.get_account_snapshot(prices)
            except Exception as exc:
                logger.error("Failed to compute portfolio snapshot: %s", exc)

        if self._account_cache is not None:
            entry.cash = self._account_cache.cash
            entry.buying_power = self._account_cache.buying_power
            entry.equity = self._account_cache.equity
            entry.realized_pnl = self._account_cache.realized_pnl

        # --- Update per-symbol context ---
        ctx.last_close = last_close
        ctx.last_signal = signal_val
        ctx.last_indicators = indicators_val

        with self._state_lock:
            self._state.price_history.append(
                {"t": ts, "price": round(last_close, 2), "symbol": symbol}
            )
            self._state.signal_history.append(
                {"t": ts, "signal": signal_val.value, "symbol": symbol}
            )
            if placed_trade:
                if action == "BUY ORDER PLACED":
                    self._state.buy_count += 1
                else:
                    self._state.sell_count += 1
                self._state.total_trades += 1
                if self._account_cache is not None:
                    self._state.account = self._account_cache
            self._state.trade_log.appendleft(entry)

    # ------------------------------------------------------------------
    # Event-driven path (background loop)
    # ------------------------------------------------------------------

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
            symbols = list(self._state.symbols.keys())

        # Initialise candle buffers for all symbols
        for symbol in symbols:
            try:
                df = self.data_provider.get_candles(
                    symbol, timeframe="5Min", limit=100
                )
                if df.empty:
                    logger.error("Failed to fetch initial candle data for %s", symbol)
                    with self._state_lock:
                        self._state.status = BotStatus.STOPPED
                    return
                ctx = self._symbol_ctx(symbol)
                if ctx is not None:
                    ctx.candle_buffer = df
                    ctx.last_close = float(df["close"].iloc[-1])
            except Exception as exc:
                logger.error(
                    "Failed to fetch initial candle data for %s: %s", symbol, exc
                )
                with self._state_lock:
                    self._state.status = BotStatus.STOPPED
                return

        self._account_cache = self.broker.get_account()
        with self._state_lock:
            self._state.account = self._account_cache

        # Subscribe to real-time bar updates for all symbols (single call)
        self.data_provider.subscribe_bars(symbols, self._on_bar, "5Min")

        with self._state_lock:
            iteration = self._state.iteration

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

            if not bars:
                continue

            # Group bars by symbol and append to respective candle buffers
            by_symbol: Dict[str, list[BarUpdate]] = {}
            for b in bars:
                by_symbol.setdefault(b.symbol, []).append(b)

            for sym, sym_bars in by_symbol.items():
                ctx = self._symbol_ctx(sym)
                if ctx is None or ctx.candle_buffer is None:
                    continue

                new_rows = pd.DataFrame(
                    [
                        (b.open, b.high, b.low, b.close, b.volume)
                        for b in sym_bars
                    ],
                    columns=["open", "high", "low", "close", "volume"],
                    index=[b.timestamp for b in sym_bars],
                )
                ctx.candle_buffer = pd.concat([ctx.candle_buffer, new_rows])
                if len(ctx.candle_buffer) > 100:
                    ctx.candle_buffer = ctx.candle_buffer.iloc[-100:]

                logger.info(
                    "Processing %d new candle(s) for %s [iteration #%d]",
                    len(sym_bars),
                    sym,
                    iteration,
                )
                self._execute_symbol(sym, iteration)

            if max_iters is not None and iteration >= max_iters:
                logger.info(
                    "Reached maximum configured iterations (%d). Stopping engine.",
                    max_iters,
                )
                with self._state_lock:
                    self._state.status = BotStatus.STOPPED
                break

        self.data_provider.unsubscribe()
        logger.info("Event-driven trading loop terminated.")

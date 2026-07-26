"""Typed data models for the Thetes trading bot.

All shared state is represented by dataclasses instead of loose dictionaries,
providing type safety, readability, and IDE support.
"""

from __future__ import annotations

import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from thetes.enums import BotStatus, Signal


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """A single open position held in the brokerage account."""

    symbol: str
    qty: float
    avg_entry_price: float
    side: str = "long"
    market_value: float = 0.0
    unrealized_pl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_entry_price": self.avg_entry_price,
            "side": self.side,
            "market_value": self.market_value,
            "unrealized_pl": self.unrealized_pl,
        }


@dataclass
class SymbolContext:
    """Per-symbol runtime state owned by the TradingEngine."""

    symbol: str
    trade_qty: float = 1.0
    candle_buffer: Optional[pd.DataFrame] = None
    indicator_cache: Any = None
    last_signal: Signal = Signal.HOLD
    last_close: float = 0.0
    last_indicators: Optional[IndicatorValues] = None


@dataclass
class AccountSnapshot:
    """Point-in-time snapshot of the brokerage account."""

    cash: float
    buying_power: float
    positions: list[Position] = field(default_factory=list)
    equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "buying_power": self.buying_power,
            "positions": [p.to_dict() for p in self.positions],
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
        }


@dataclass
class IndicatorValues:
    """Computed technical indicator values for a single candle."""

    ema9: float = 0.0
    ema21: float = 0.0
    rsi: float = 0.0
    ema_trend: float = 0.0
    atr: float = 0.0
    adx: float = 0.0
    volume_ratio: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "ema9": self.ema9,
            "ema21": self.ema21,
            "rsi": self.rsi,
            "ema_trend": self.ema_trend,
            "atr": self.atr,
            "adx": self.adx,
            "volume_ratio": self.volume_ratio,
        }


@dataclass
class MarketState:
    """Latest market snapshot used by the dashboard."""

    last_close: float = 0.0
    last_signal: Signal = Signal.HOLD
    indicators: IndicatorValues = field(default_factory=IndicatorValues)


@dataclass
class TradeLogEntry:
    """A single row in the trade log shown on the dashboard."""

    timestamp: str = ""
    iteration: int = 0
    symbol: Optional[str] = None
    signal: Optional[str] = None
    close_price: Optional[float] = None
    indicators: Optional[IndicatorValues] = None
    action: Optional[str] = None
    error: Optional[str] = None
    cash: Optional[float] = None
    buying_power: Optional[float] = None
    equity: Optional[float] = None
    realized_pnl: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "iteration": self.iteration,
        }
        if self.symbol is not None:
            d["symbol"] = self.symbol
        if self.signal is not None:
            d["signal"] = self.signal
        if self.close_price is not None:
            d["close"] = self.close_price
        if self.indicators is not None:
            d["ema9"] = self.indicators.ema9
            d["ema21"] = self.indicators.ema21
            d["rsi"] = self.indicators.rsi
            d["ema_trend"] = self.indicators.ema_trend
            d["atr"] = self.indicators.atr
            d["adx"] = self.indicators.adx
            d["volume_ratio"] = self.indicators.volume_ratio
        if self.action is not None:
            d["action"] = self.action
        if self.error is not None:
            d["error"] = self.error
        if self.cash is not None:
            d["cash"] = self.cash
        if self.buying_power is not None:
            d["buying_power"] = self.buying_power
        if self.equity is not None:
            d["equity"] = self.equity
        if self.realized_pnl is not None:
            d["realized_pnl"] = self.realized_pnl
        return d


# ---------------------------------------------------------------------------
# Aggregate bot state
# ---------------------------------------------------------------------------

MAX_LOG_ENTRIES = 200
MAX_HISTORY_ENTRIES = 100


@dataclass
class RiskDecision:
    position_size: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    is_allowed: bool = False


@dataclass
class BotState:
    """Complete state of the trading bot, owned by TradingEngine."""

    status: BotStatus = BotStatus.STOPPED
    symbol: str = "AAPL"
    trade_qty: float = 1.0
    loop_delay: int = 10
    iteration: int = 0
    trading_symbols: tuple[str, ...] = ("AAPL",)

    # Per-symbol runtime contexts (populated at start)
    symbols: dict[str, SymbolContext] = field(default_factory=dict)

    # Market
    market: MarketState = field(default_factory=MarketState)

    # Account
    account: AccountSnapshot = field(
        default_factory=lambda: AccountSnapshot(cash=100_000.0, buying_power=400_000.0)
    )

    # Counters
    total_trades: int = 0
    buy_count: int = 0
    sell_count: int = 0

    # Timestamps
    started_at: Optional[str] = None

    # Histories (bounded)
    trade_log: deque[TradeLogEntry] = field(
        default_factory=lambda: deque(maxlen=MAX_LOG_ENTRIES)
    )
    price_history: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_HISTORY_ENTRIES)
    )
    signal_history: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_HISTORY_ENTRIES)
    )

    @property
    def primary_symbol(self) -> str:
        return self.trading_symbols[0] if self.trading_symbols else self.symbol

    # ------------------------------------------------------------------
    # Serialisation for the /api/state endpoint
    # ------------------------------------------------------------------

    def to_api_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary matching the frontend contract."""
        return {
            "running": self.status == BotStatus.RUNNING,
            "symbol": self.symbol,
            "trading_symbols": list(self.trading_symbols),
            "trade_qty": self.trade_qty,
            "loop_delay": self.loop_delay,
            "iteration": self.iteration,
            "last_signal": self.market.last_signal.value,
            "last_ema9": self.market.indicators.ema9,
            "last_ema21": self.market.indicators.ema21,
            "last_rsi": self.market.indicators.rsi,
            "last_ema_trend": self.market.indicators.ema_trend,
            "last_atr": self.market.indicators.atr,
            "last_adx": self.market.indicators.adx,
            "last_volume_ratio": self.market.indicators.volume_ratio,
            "last_close": self.market.last_close,
            "cash": self.account.cash,
            "buying_power": self.account.buying_power,
            "equity": self.account.equity,
            "realized_pnl": self.account.realized_pnl,
            "unrealized_pnl": self.account.unrealized_pnl,
            "positions": [p.to_dict() for p in self.account.positions],
            "total_trades": self.total_trades,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "started_at": self.started_at,
            "trade_log": [e.to_dict() for e in self.trade_log],
            "price_history": list(self.price_history),
            "signal_history": list(self.signal_history),
        }

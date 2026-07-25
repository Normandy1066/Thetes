"""Enumerations used throughout the Thetes trading bot."""

from __future__ import annotations

from enum import Enum


class Signal(str, Enum):
    """Trading signal emitted by the strategy."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class BotStatus(str, Enum):
    """Lifecycle status of the trading engine."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class OrderSide(str, Enum):
    """Side of a trade order."""

    BUY = "BUY"
    SELL = "SELL"

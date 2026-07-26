"""mock_broker.py

In-memory MockBroker implementation of the Broker interface.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from thetes.broker import Broker
from thetes.models import AccountSnapshot, Position
from thetes.portfolio_manager import PortfolioManager

logger = logging.getLogger(__name__)


class MockBroker(Broker):
    """Mock broker simulating account balances and positions in memory."""

    def __init__(self, initial_cash: float = 100000.0, initial_buying_power: float = 400000.0) -> None:
        self._portfolio = PortfolioManager(initial_cash, initial_buying_power)

    @property
    def portfolio_manager(self) -> PortfolioManager:
        return self._portfolio

    def get_account(self) -> AccountSnapshot:
        return self._portfolio.get_account_snapshot()

    def get_position(self, symbol: str) -> Position:
        pm = self._portfolio
        with pm._lock:
            data = pm._positions.get(symbol)
            if data is None:
                raise ValueError(f"No position found for {symbol}")
            return Position(
                symbol=symbol,
                qty=data["qty"],
                avg_entry_price=data["avg_price"],
                side="long",
                market_value=data["qty"] * data["avg_price"],
                unrealized_pl=0.0,
            )

    def get_all_positions(self) -> List[Position]:
        pm = self._portfolio
        with pm._lock:
            return [
                Position(
                    symbol=sym,
                    qty=data["qty"],
                    avg_entry_price=data["avg_price"],
                    side="long",
                    market_value=data["qty"] * data["avg_price"],
                    unrealized_pl=0.0,
                )
                for sym, data in pm._positions.items()
            ]

    def buy(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        self._portfolio.execute_buy(symbol, qty, price)
        logger.info("Mock BUY executed: %s %s @ %s", qty, symbol, price)
        return {"id": "mock-buy-order", "symbol": symbol, "qty": qty, "price": price}

    def sell(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        self._portfolio.execute_sell(symbol, qty, price)
        logger.info("Mock SELL executed: %s %s @ %s", qty, symbol, price)
        return {"id": "mock-sell-order", "symbol": symbol, "qty": qty, "price": price}

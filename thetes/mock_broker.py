"""mock_broker.py

In-memory MockBroker implementation of the Broker interface.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List

from thetes.broker import Broker
from thetes.models import AccountSnapshot, Position

logger = logging.getLogger(__name__)


class MockBroker(Broker):
    """Mock broker simulating account balances and positions in memory."""

    def __init__(self, initial_cash: float = 100000.0, initial_buying_power: float = 400000.0) -> None:
        self._lock = threading.Lock()
        self._cash = initial_cash
        self._buying_power = initial_buying_power
        # maps symbol -> {"qty": float, "avg_price": float}
        self._positions: Dict[str, dict] = {}

    def get_account(self) -> AccountSnapshot:
        with self._lock:
            positions_list = [
                Position(
                    symbol=sym,
                    qty=data["qty"],
                    avg_entry_price=data["avg_price"],
                    side="long",
                    market_value=data["qty"] * data["avg_price"],
                    unrealized_pl=0.0
                )
                for sym, data in self._positions.items()
            ]
            return AccountSnapshot(
                cash=self._cash,
                buying_power=self._buying_power,
                positions=positions_list
            )

    def get_position(self, symbol: str) -> Position:
        with self._lock:
            if symbol in self._positions:
                data = self._positions[symbol]
                return Position(
                    symbol=symbol,
                    qty=data["qty"],
                    avg_entry_price=data["avg_price"],
                    side="long",
                    market_value=data["qty"] * data["avg_price"],
                    unrealized_pl=0.0
                )
            raise ValueError(f"No position found for {symbol}")

    def get_all_positions(self) -> List[Position]:
        with self._lock:
            return [
                Position(
                    symbol=sym,
                    qty=data["qty"],
                    avg_entry_price=data["avg_price"],
                    side="long",
                    market_value=data["qty"] * data["avg_price"],
                    unrealized_pl=0.0
                )
                for sym, data in self._positions.items()
            ]



    def _execute_buy(self, symbol: str, qty: float, price: float) -> dict:
        with self._lock:
            cost = qty * price
            if self._cash < cost:
                raise RuntimeError(f"Insufficient cash for mock BUY of {symbol}. Have ${self._cash:.2f}, need ${cost:.2f}")
            self._cash -= cost
            self._buying_power += cost # simplistic assumption from original execution.py
            
            pos = self._positions.get(symbol)
            if pos:
                total_qty = pos["qty"] + qty
                avg_price = (pos["qty"] * pos["avg_price"] + cost) / total_qty
                pos["qty"] = total_qty
                pos["avg_price"] = avg_price
            else:
                self._positions[symbol] = {"qty": qty, "avg_price": price}
            
            logger.info("Mock BUY executed: %s %s @ %s", qty, symbol, price)
            return {"id": "mock-buy-order", "symbol": symbol, "qty": qty, "price": price}

    def buy(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        return self._execute_buy(symbol, qty, price)

    def _execute_sell(self, symbol: str, qty: float, price: float) -> dict:
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos or pos["qty"] < qty:
                current_qty = pos["qty"] if pos else 0
                raise RuntimeError(f"Insufficient position for mock SELL of {symbol}. Have {current_qty}, trying to sell {qty}")
            
            proceeds = qty * price
            self._cash += proceeds
            self._buying_power -= proceeds # simplistic assumption from original execution.py
            pos["qty"] -= qty
            if pos["qty"] == 0:
                del self._positions[symbol]
                
            logger.info("Mock SELL executed: %s %s @ %s", qty, symbol, price)
            return {"id": "mock-sell-order", "symbol": symbol, "qty": qty, "price": price}

    def sell(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        return self._execute_sell(symbol, qty, price)

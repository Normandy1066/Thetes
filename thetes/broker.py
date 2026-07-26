"""broker.py

Abstract Broker interface to decouple trading logic from the execution provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from thetes.models import AccountSnapshot, Position


class Broker(ABC):
    """Abstract base class representing a brokerage interface."""

    @property
    def portfolio_manager(self):
        """Return the associated ``PortfolioManager``, or ``None``.

        Subclasses that maintain a ``PortfolioManager`` should override this.
        """
        return None

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """Return the current account snapshot (balances and positions)."""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        """Return the current position for a given symbol.

        Raises
        ------
        Exception
            If no position exists for the symbol.
        """
        pass

    @abstractmethod
    def get_all_positions(self) -> List[Position]:
        """Return all open positions."""
        pass

    @abstractmethod
    def buy(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        """Submit a market BUY order.

        Returns
        -------
        dict
            Order execution response detailing order details (e.g. ID).
        """
        pass

    @abstractmethod
    def sell(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        """Submit a market SELL order.

        Returns
        -------
        dict
            Order execution response detailing order details (e.g. ID).
        """
        pass

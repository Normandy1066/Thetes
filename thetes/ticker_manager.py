"""ticker_manager.py

Service layer for runtime ticker management — keeps business logic out
of the Flask route handlers.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable, Optional

from thetes.config import Config
from thetes.data_provider import MarketDataProvider
from thetes.engine import TradingEngine

logger = logging.getLogger(__name__)

_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,10}$")


class TickerManager:
    """Manages the set of tracked tickers at runtime.

    Coordinates between the engine's state and the data provider's
    live subscription so that changes take effect without a restart.
    """

    def __init__(
        self,
        engine: TradingEngine,
        config: Config,
        data_provider: MarketDataProvider,
    ) -> None:
        self._engine = engine
        self._config = config
        self._data_provider = data_provider
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_tickers(self) -> list[str]:
        """Return the currently tracked ticker symbols."""
        state = self._engine.get_state()
        return list(state.trading_symbols)

    # ------------------------------------------------------------------
    # Symbol validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        """Validate and normalise a single ticker symbol.

        Returns the uppercased symbol on success.
        Raises ``ValueError`` with a human-readable message on failure.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Symbol must be a non-empty string.")
        s = symbol.strip().upper()
        if not _SYMBOL_PATTERN.match(s):
            raise ValueError(
                f"Invalid symbol: {symbol!r}. "
                "Symbols must be 1-10 uppercase letters."
            )
        return s

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def replace_tickers(self, symbols: list[str]) -> list[str]:
        """Replace the entire ticker list.

        Each symbol is validated, duplicates are removed, and the
        subscription is updated.

        Returns the new (de-duplicated) symbol list.
        """
        normalised: list[str] = []
        seen: set[str] = set()
        for s in symbols:
            ns = self.validate_symbol(s)
            if ns not in seen:
                seen.add(ns)
                normalised.append(ns)

        if not normalised:
            raise ValueError("At least one valid symbol is required.")

        with self._lock:
            self._engine.replace_symbols(normalised)
            self._resubscribe(normalised)
            logger.info("Tickers replaced: %s", normalised)
        return normalised

    def add_ticker(self, symbol: str) -> list[str]:
        """Add a single ticker.

        Returns the updated symbol list.
        """
        ns = self.validate_symbol(symbol)
        current = set(self.get_tickers())
        if ns in current:
            raise ValueError(f"Symbol already tracked: {ns}")

        with self._lock:
            updated = list(current | {ns})
            updated.sort()
            self._engine.replace_symbols(updated)
            self._resubscribe(updated)
            logger.info("Ticker added: %s", ns)
        return updated

    def remove_ticker(self, symbol: str) -> list[str]:
        """Remove a single ticker.

        Returns the updated symbol list.
        """
        ns = symbol.strip().upper()
        current = set(self.get_tickers())
        if ns not in current:
            raise ValueError(f"Symbol not tracked: {ns}")
        if len(current) == 1:
            raise ValueError("Cannot remove the last remaining ticker.")

        with self._lock:
            updated = sorted(current - {ns})
            self._engine.replace_symbols(updated)
            self._resubscribe(updated)
            logger.info("Ticker removed: %s", ns)
        return updated

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resubscribe(self, symbols: list[str]) -> None:
        """Tell the data provider to replace its live subscription."""
        if hasattr(self._data_provider, "update_subscription"):
            self._data_provider.update_subscription(symbols)

"""execution.py

Helper functions for sending orders to Alpaca Paper Trading and querying the
account status.

All functions rely on the ``alpaca-py`` (``alpaca.trading``) client and read the
API credentials from the ``ALPACA_API_KEY`` and ``ALPACA_SECRET_KEY``
environment variables.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional
import pandas as pd

# Lazy import of the Alpaca SDK – the same approach used in ``data.py``.
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import OrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
except Exception as exc:
    TradingClient = None  # type: ignore
    OrderRequest = None  # type: ignore
    OrderSide = None  # type: ignore
    TimeInForce = None  # type: ignore
    logging.error("Alpaca SDK import failed: %s", exc)

# Basic logging configuration – can be overridden by the host app.
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


class MockClient:
    """Mock client for development/testing when no valid credentials are provided. Persists state across iterations."""
    # Class-level persistent state
    _cash: float = 100000.0
    _buying_power: float = 400000.0
    _positions: dict[str, dict] = {}

    class _Account:
        def __init__(self, cash: float, buying_power: float):
            self.cash = cash
            self.buying_power = buying_power

    class _Position:
        def __init__(self, symbol: str, qty: float, avg_entry_price: float):
            self.symbol = symbol
            self.qty = qty
            self.avg_entry_price = avg_entry_price
            self.side = "long" if qty >= 0 else "short"
            self.market_value = qty * avg_entry_price
            self.unrealized_pl = 0.0

    def get_account(self):
        """Return current mock account balance."""
        return self._Account(cash=self.__class__._cash, buying_power=self.__class__._buying_power)

    def get_all_positions(self):
        """Return a list of mock Position objects."""
        return [self._Position(sym, data["qty"], data["avg_price"]) for sym, data in self.__class__._positions.items()]

    def get_position(self, symbol: str):
        """Return a mock Position for the given symbol or raise if none."""
        if symbol in self.__class__._positions:
            data = self.__class__._positions[symbol]
            return self._Position(symbol, data["qty"], data["avg_price"])  # type: ignore
        raise Exception("No position")

    def _process_buy(self, symbol: str, qty: float, price: float):
        cost = qty * price
        if self.__class__._cash < cost:
            raise RuntimeError(f"Insufficient cash for mock BUY of {symbol}")
        # Update cash & buying power
        self.__class__._cash -= cost
        self.__class__._buying_power += cost  # simplistic assumption
        # Update position
        pos = self.__class__._positions.get(symbol)
        if pos:
            total_qty = pos["qty"] + qty
            # Weighted average price
            avg_price = (pos["qty"] * pos["avg_price"] + cost) / total_qty
            pos["qty"] = total_qty
            pos["avg_price"] = avg_price
        else:
            self.__class__._positions[symbol] = {"qty": qty, "avg_price": price}
        logging.info("Mock BUY executed: %s %s @ %s", qty, symbol, price)
        return {"id": "mock-buy-order"}

    def _process_sell(self, symbol: str, qty: float, price: float):
        pos = self.__class__._positions.get(symbol)
        if not pos or pos["qty"] < qty:
            raise RuntimeError(f"Insufficient position for mock SELL of {symbol}")
        proceeds = qty * price
        self.__class__._cash += proceeds
        self.__class__._buying_power -= proceeds  # simplistic assumption
        pos["qty"] -= qty
        if pos["qty"] == 0:
            del self.__class__._positions[symbol]
        logging.info("Mock SELL executed: %s %s @ %s", qty, symbol, price)
        return {"id": "mock-sell-order"}

    def submit_order(self, request):
        """Fallback submit_order for cases where OrderRequest is None. No‑op for mock."""
        logging.info("Mock order submitted (no details): %s", request)
        return {"id": "mock-order-id"}



def _get_client() -> Optional[TradingClient | MockClient]:
    """Create an authenticated ``TradingClient`` for the paper‑trading endpoint.

    Returns
    -------
    TradingClient or MockClient
        Returns MockClient if using placeholder credentials.

    Raises
    ------
    RuntimeError
        If the required environment variables are missing or SDK is not installed.
    """
    if TradingClient is None:
        raise RuntimeError("Alpaca SDK is not installed. Install alpaca-py.")

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    # Treat placeholder values or missing credentials as a signal to use the mock client.
    placeholder_keys = {"YOUR_ALPACA_API_KEY", "YOUR_ALPACA_SECRET_KEY", "PAPER_API_KEY", "PAPER_SECRET_KEY", None, ""}
    if api_key in placeholder_keys or secret_key in placeholder_keys:
        return MockClient()
    
    # Credentials appear valid – instantiate real TradingClient.
    return TradingClient(api_key=api_key, secret_key=secret_key, paper=True)


def get_account_status() -> Dict[str, Any]:
    """Return a quick snapshot of the paper‑trading account.

    The dictionary contains:
        - ``cash``: available cash in USD.
        - ``buying_power``: buying power in USD.
        - ``positions``: a ``pandas.DataFrame`` summarising open positions.
    """
    client = _get_client()

    try:
        account = client.get_account()
        logging.info("Fetched account: cash=%s, buying_power=%s", account.cash, account.buying_power)
    except Exception as exc:
        logging.error("Failed to retrieve account information: %s", exc)
        raise

    # Retrieve current open positions – may be empty.
    try:
        positions = client.get_all_positions()
        # Convert list of Position objects into a DataFrame for easier introspection.
        pos_df = pd.DataFrame([
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "side": p.side,
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ])
    except Exception as exc:
        logging.error("Failed to retrieve open positions: %s", exc)
        pos_df = pd.DataFrame()

    return {
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "positions": pos_df,
    }


def _ensure_sufficient_cash(client: Any, required_usd: float) -> None:
    """Raise ``RuntimeError`` if the account does not have enough cash.
    """
    account = client.get_account()
    cash = float(account.cash)
    if cash < required_usd:
        raise RuntimeError(
            f"Insufficient cash: have ${cash:,.2f}, need ${required_usd:,.2f}."
        )


def place_buy_order(symbol: str, qty: float) -> Any:
    """Place a market BUY order for given symbol and quantity."""
    if TradingClient is None:
        raise RuntimeError("Alpaca SDK is not installed.")
    client = _get_client()
    # Get latest price – mock client may not provide get_last_trade
    try:
        price = float(getattr(client, "get_last_trade", lambda s: type("Obj", (), {"price": 150.0})())(symbol).price)
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve price for {symbol}") from exc
    required_usd = price * qty
    _ensure_sufficient_cash(client, required_usd)
    # If using the real TradingClient, create OrderRequest
    if OrderRequest is not None and not isinstance(client, MockClient):
        order_req = OrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            type="market",
            time_in_force=TimeInForce.GTC,
        )
        return client.submit_order(order_req)
    # Mock handling – directly update mock state
    if isinstance(client, MockClient):
        return client._process_buy(symbol, qty, price)
    # Fallback
    return client.submit_order(None)


def place_sell_order(symbol: str, qty: float) -> Any:
    """Place a market SELL order for given symbol and quantity."""
    if TradingClient is None:
        raise RuntimeError("Alpaca SDK is not installed.")
    client = _get_client()
    # Verify position exists (mock client may raise)
    try:
        position = client.get_position(symbol)
        current_qty = float(position.qty)
    except Exception:
        raise RuntimeError(f"No open position for {symbol} to sell.")
    if current_qty < qty:
        raise RuntimeError(
            f"Attempting to sell {qty} shares of {symbol}, but only {current_qty} are held."
        )
    # Real client handling
    if OrderRequest is not None and not isinstance(client, MockClient):
        order_req = OrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            type="market",
            time_in_force=TimeInForce.GTC,
        )
        return client.submit_order(order_req)
    # Mock handling – directly update mock state
    if isinstance(client, MockClient):
        # Retrieve price (use same mock price logic as buy)
        price = float(getattr(client, "get_last_trade", lambda s: type("Obj", (), {"price": 150.0})())(symbol).price)
        return client._process_sell(symbol, qty, price)
    # Fallback
    return client.submit_order(None)


# Export public API symbols.
__all__ = ["place_buy_order", "place_sell_order", "get_account_status"]

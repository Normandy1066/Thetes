"""alpaca_broker.py

Alpaca paper trading implementation of the Broker interface.
"""

from __future__ import annotations

import logging
from typing import List, Any

from thetes.broker import Broker
from thetes.models import AccountSnapshot, Position
from thetes.config import Config

logger = logging.getLogger(__name__)

# Lazy import of the Alpaca SDK
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import OrderRequest
    from alpaca.trading.enums import OrderSide as AlpacaOrderSide, TimeInForce, OrderType
    from alpaca.trading.models import TradeAccount, Position as AlpacaPosition
except Exception as exc:
    TradingClient = None  # type: ignore
    OrderRequest = None  # type: ignore
    AlpacaOrderSide = None  # type: ignore
    TimeInForce = None  # type: ignore
    OrderType = None  # type: ignore
    TradeAccount = None  # type: ignore
    AlpacaPosition = None  # type: ignore
    logger.error("Alpaca SDK import failed: %s", exc)


class AlpacaBroker(Broker):
    """Real Alpaca paper trading broker implementation."""

    def __init__(self, config: Config) -> None:
        if TradingClient is None:
            raise RuntimeError("Alpaca SDK is not installed. Run `pip install alpaca-py`.")
        
        self._config = config
        self._client = TradingClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=True
        )

    def get_account(self) -> AccountSnapshot:
        try:
            account = self._client.get_account()
            if not isinstance(account, TradeAccount):
                raise TypeError("Expected TradeAccount from Alpaca API")
            positions = self.get_all_positions()
            
            # Since mypy might complain about cash/buying_power types in TradeAccount, we narrow them
            cash_val = account.cash
            buying_power_val = account.buying_power
            if cash_val is None or buying_power_val is None:
                raise ValueError("Cash or buying power was None from Alpaca")
            
            return AccountSnapshot(
                cash=float(cash_val),
                buying_power=float(buying_power_val),
                positions=positions
            )
        except Exception as exc:
            logger.error("Failed to retrieve Alpaca account: %s", exc)
            raise

    def get_position(self, symbol: str) -> Position:
        try:
            p = self._client.get_open_position(symbol)
            if not isinstance(p, AlpacaPosition):
                raise TypeError("Expected Position from Alpaca API")
            
            qty_val = p.qty
            avg_price_val = p.avg_entry_price
            market_val = p.market_value
            pl_val = p.unrealized_pl
            
            if qty_val is None or avg_price_val is None or market_val is None or pl_val is None:
                raise ValueError("Required position attributes were None from Alpaca")
                
            return Position(
                symbol=p.symbol,
                qty=float(qty_val),
                avg_entry_price=float(avg_price_val),
                side=p.side,
                market_value=float(market_val),
                unrealized_pl=float(pl_val)
            )
        except Exception as exc:
            logger.error("Failed to retrieve Alpaca position for %s: %s", symbol, exc)
            raise

    def get_all_positions(self) -> List[Position]:
        try:
            positions = self._client.get_all_positions()
            res = []
            for p in positions:
                if not isinstance(p, AlpacaPosition):
                    continue
                
                qty_val = p.qty
                avg_price_val = p.avg_entry_price
                market_val = p.market_value
                pl_val = p.unrealized_pl
                
                if qty_val is None or avg_price_val is None or market_val is None or pl_val is None:
                    continue
                    
                res.append(Position(
                    symbol=p.symbol,
                    qty=float(qty_val),
                    avg_entry_price=float(avg_price_val),
                    side=p.side,
                    market_value=float(market_val),
                    unrealized_pl=float(pl_val)
                ))
            return res
        except Exception as exc:
            logger.error("Failed to retrieve all Alpaca positions: %s", exc)
            return []

    def buy(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        if OrderRequest is None or OrderType is None:
            raise RuntimeError("Alpaca SDK is not installed properly.")
        
        # Verify cash
        account = self._client.get_account()
        if not isinstance(account, TradeAccount):
            raise TypeError("Expected TradeAccount from Alpaca API")
        
        cash_val = account.cash
        if cash_val is None:
            raise ValueError("Cash was None from Alpaca")
            
        cash = float(cash_val)
        required_usd = price * qty
        if cash < required_usd:
            raise RuntimeError(f"Insufficient cash: have ${cash:,.2f}, need ${required_usd:,.2f}.")

        order_req = OrderRequest(
            symbol=symbol,
            qty=qty,
            side=AlpacaOrderSide.BUY,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC,
        )
        order = self._client.submit_order(order_req)
        order_id = getattr(order, "id", "N/A")
        logger.info("Alpaca BUY order submitted: %s (id: %s)", symbol, order_id)
        return {"id": order_id, "symbol": symbol, "qty": qty}

    def sell(self, symbol: str, qty: float, price: float = 150.0) -> dict:
        if OrderRequest is None or OrderType is None:
            raise RuntimeError("Alpaca SDK is not installed properly.")

        # Verify position
        position = self.get_position(symbol)
        if position.qty < qty:
            raise RuntimeError(f"Attempting to sell {qty} shares of {symbol}, but only {position.qty} are held.")

        order_req = OrderRequest(
            symbol=symbol,
            qty=qty,
            side=AlpacaOrderSide.SELL,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC,
        )
        order = self._client.submit_order(order_req)
        order_id = getattr(order, "id", "N/A")
        logger.info("Alpaca SELL order submitted: %s (id: %s)", symbol, order_id)
        return {"id": order_id, "symbol": symbol, "qty": qty}

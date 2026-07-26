"""portfolio_manager.py

Single source of truth for portfolio state — cash, positions, PnL.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from thetes.models import AccountSnapshot, Position


class PortfolioManager:
    """Tracks starting / current cash, buying power, open positions, and PnL."""

    def __init__(self, starting_cash: float = 100000.0, buying_power: Optional[float] = None) -> None:
        self._lock = threading.Lock()
        self._starting_cash = starting_cash
        self._cash = starting_cash
        self._buying_power = buying_power if buying_power is not None else starting_cash * 4.0
        # symbol -> {"qty": float, "avg_price": float}
        self._positions: Dict[str, dict] = {}
        self._realized_pnl = 0.0

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def buying_power(self) -> float:
        return self._buying_power

    @property
    def starting_cash(self) -> float:
        return self._starting_cash

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    def get_positions(self) -> Dict[str, dict]:
        """Return a copy of the internal position dictionary."""
        with self._lock:
            return {sym: dict(data) for sym, data in self._positions.items()}

    # ------------------------------------------------------------------
    # Order validation
    # ------------------------------------------------------------------

    def can_afford(self, order: dict) -> bool:
        """Return True if current cash can cover *order* (dict with ``qty`` + ``price``)."""
        cost = order.get("qty", 0) * order.get("price", 0)
        return cost <= self._cash

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_buy(self, symbol: str, qty: float, price: float) -> None:
        """Execute a buy: deduct cash, update / create position."""
        with self._lock:
            cost = qty * price
            if self._cash < cost:
                raise RuntimeError(
                    f"Insufficient cash for BUY {symbol}. "
                    f"Have ${self._cash:.2f}, need ${cost:.2f}"
                )
            self._cash -= cost
            self._buying_power += cost

            pos = self._positions.get(symbol)
            if pos:
                total_qty = pos["qty"] + qty
                pos["avg_price"] = (pos["qty"] * pos["avg_price"] + cost) / total_qty
                pos["qty"] = total_qty
            else:
                self._positions[symbol] = {"qty": qty, "avg_price": price}

    def execute_sell(self, symbol: str, qty: float, price: float) -> float:
        """Execute a sell: add cash, update / delete position, record realised PnL.

        Returns the realised PnL for this partial/full sale.
        """
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos or pos["qty"] < qty:
                current_qty = pos["qty"] if pos else 0
                raise RuntimeError(
                    f"Insufficient position for SELL {symbol}. "
                    f"Have {current_qty}, trying to sell {qty}"
                )

            proceeds = qty * price
            cost_basis = qty * pos["avg_price"]
            realised = proceeds - cost_basis

            self._cash += proceeds
            self._buying_power -= proceeds
            self._realized_pnl += realised

            pos["qty"] -= qty
            if pos["qty"] == 0:
                del self._positions[symbol]

            return realised

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def position_count(self) -> int:
        """Number of currently open positions."""
        with self._lock:
            return len(self._positions)

    def available_capital(self, min_reserve: float = 0.0) -> float:
        """Cash available for new trades, after reserving *min_reserve*."""
        with self._lock:
            return max(0.0, self._cash - min_reserve)

    def compute_buy_size(
        self,
        price: float,
        atr: float,
        stop_multiple: float,
        risk_per_trade_pct: float,
        max_position_size_pct: float,
        max_simultaneous_positions: int,
        min_cash_reserve: float,
        sizing_mode: str = "percentage",
        fixed_dollar_amount: float = 0.0,
        requested_qty: float = 0.0,
    ) -> float:
        """Compute the maximum number of shares to buy given portfolio constraints.

        Returns 0.0 if the trade should be rejected.
        """
        with self._lock:
            avail = max(0.0, self._cash - min_cash_reserve)
            if avail <= 0.0 or price <= 0.0:
                return 0.0

            if max_simultaneous_positions > 0 and len(self._positions) >= max_simultaneous_positions:
                return 0.0

            if sizing_mode == "fixed" and fixed_dollar_amount > 0.0:
                dollar_target = fixed_dollar_amount
            else:
                dollar_target = avail * (risk_per_trade_pct / 100.0)
            dollar_target = min(dollar_target, avail)

            atr_based_qty = dollar_target / (atr * stop_multiple) if atr > 0 and stop_multiple > 0 else float("inf")

            max_pos_dollars = avail * (max_position_size_pct / 100.0)
            max_pct_qty = max_pos_dollars / price if price > 0 else float("inf")

            dollar_qty = dollar_target / price if price > 0 else float("inf")

            size = min(atr_based_qty, max_pct_qty, dollar_qty)
            if requested_qty > 0:
                size = min(size, requested_qty)

            return max(0.0, round(size, 4))

    # ------------------------------------------------------------------
    # Portfolio valuation
    # ------------------------------------------------------------------

    def portfolio_value(self, prices: Dict[str, float]) -> float:
        """Total portfolio value (cash + market value of all positions)."""
        with self._lock:
            mv = 0.0
            for sym, data in self._positions.items():
                price = prices.get(sym, data["avg_price"])
                mv += data["qty"] * price
            return self._cash + mv

    def available_cash(self) -> float:
        """Alias for ``cash`` (convenience)."""
        return self._cash

    def total_return(self, prices: Dict[str, float]) -> float:
        """Return total return (realised + unrealised) as a decimal fraction."""
        if self._starting_cash == 0:
            return 0.0
        return (self.portfolio_value(prices) - self._starting_cash) / self._starting_cash

    def unrealized_pnl(self, prices: Dict[str, float]) -> float:
        """Sum of unrealised PnL across all positions at the given prices."""
        total = 0.0
        with self._lock:
            for sym, data in self._positions.items():
                price = prices.get(sym, data["avg_price"])
                total += (price - data["avg_price"]) * data["qty"]
            return total

    # ------------------------------------------------------------------
    # Snapshot for the Broker interface
    # ------------------------------------------------------------------

    def get_account_snapshot(self, prices: Optional[Dict[str, float]] = None) -> AccountSnapshot:
        """Build an ``AccountSnapshot`` from current state.

        When *prices* is provided, ``market_value`` and ``unrealised_pl``
        are computed from those prices; otherwise the average entry price
        is used (giving zero unrealised PnL).
        """
        with self._lock:
            positions: List[Position] = []
            total_mv = 0.0
            total_upnl = 0.0

            for sym, data in self._positions.items():
                price = prices.get(sym, data["avg_price"]) if prices else data["avg_price"]
                mv = data["qty"] * price
                upnl = (price - data["avg_price"]) * data["qty"]
                total_mv += mv
                total_upnl += upnl
                positions.append(
                    Position(
                        symbol=sym,
                        qty=data["qty"],
                        avg_entry_price=data["avg_price"],
                        side="long",
                        market_value=mv,
                        unrealized_pl=upnl,
                    )
                )

            equity = self._cash + total_mv
            return AccountSnapshot(
                cash=self._cash,
                buying_power=self._buying_power,
                positions=positions,
                equity=equity,
                realized_pnl=self._realized_pnl,
                unrealized_pnl=total_upnl,
            )

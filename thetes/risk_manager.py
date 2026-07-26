import logging
from typing import Dict, Optional

import pandas as pd

from thetes.broker import Broker
from thetes.config import Config
from thetes.enums import Signal
from thetes.indicators import AtrState, atr, atr_incremental, atr_state_from_series
from thetes.models import AccountSnapshot, RiskDecision

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config: Config, broker: Broker) -> None:
        self._config = config
        self._broker = broker
        self._atr_caches: Dict[str, AtrState] = {}

    def reset(self) -> None:
        self._atr_caches.clear()

    def evaluate(
        self,
        signal: Signal,
        price: float,
        df: pd.DataFrame,
        qty: float,
        symbol: str = "",
        account: Optional[AccountSnapshot] = None,
        atr_val: Optional[float] = None,
    ) -> RiskDecision:
        if signal == Signal.HOLD:
            return RiskDecision(is_allowed=False)

        if atr_val is None:
            atr_val = self._compute_atr(df, symbol)
        if atr_val <= 0:
            return RiskDecision(is_allowed=False)

        stop_distance = atr_val * self._config.atr_stop_multiple
        tp_distance = atr_val * self._config.atr_take_profit_multiple

        pm = self._broker.portfolio_manager

        if signal == Signal.BUY:
            if pm is not None:
                size = pm.compute_buy_size(
                    price=price,
                    atr=atr_val,
                    stop_multiple=self._config.atr_stop_multiple,
                    risk_per_trade_pct=self._config.risk_per_trade_pct,
                    max_position_size_pct=self._config.max_position_size_pct,
                    max_simultaneous_positions=self._config.max_simultaneous_positions,
                    min_cash_reserve=self._config.min_cash_reserve,
                    sizing_mode=self._config.position_sizing_mode,
                    fixed_dollar_amount=self._config.fixed_trade_amount,
                    requested_qty=qty,
                )
            else:
                # Legacy fallback
                if account is None:
                    account = self._broker.get_account()
                risk_amount = account.cash * (self._config.risk_per_trade_pct / 100.0)
                max_pos_value = account.cash * (self._config.max_position_size_pct / 100.0)
                risk_based_size = risk_amount / stop_distance
                cash_based_size = max_pos_value / price if price > 0 else qty
                size = min(qty, risk_based_size, cash_based_size)

            is_allowed = size > 0
        else:
            # SELL: use requested qty (broker validates against existing position)
            size = float(qty)
            is_allowed = size > 0

        if signal == Signal.BUY:
            stop_loss = price - stop_distance
            take_profit = price + tp_distance
        else:
            stop_loss = price + stop_distance
            take_profit = price - tp_distance

        return RiskDecision(
            position_size=round(size, 4),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            is_allowed=is_allowed,
        )

    def _compute_atr(self, df: pd.DataFrame, symbol: str = "") -> float:
        cache = self._atr_caches.get(symbol)
        if cache is not None and len(df) >= 2:
            if float(df["close"].iloc[-2]) == cache.prev_close:
                high = float(df["high"].iloc[-1])
                low = float(df["low"].iloc[-1])
                close = float(df["close"].iloc[-1])
                atr_val, self._atr_caches[symbol] = atr_incremental(high, low, close, cache)
                return atr_val

        atr_series = atr(df["high"], df["low"], df["close"], self._config.atr_period)
        atr_val = float(atr_series.iloc[-1])
        self._atr_caches[symbol] = atr_state_from_series(
            df["high"], df["low"], df["close"], self._config.atr_period
        )
        return atr_val

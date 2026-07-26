import logging

import pandas as pd

from thetes.broker import Broker
from thetes.config import Config
from thetes.enums import Signal
from thetes.indicators import atr
from thetes.models import RiskDecision

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config: Config, broker: Broker) -> None:
        self._config = config
        self._broker = broker

    def evaluate(self, signal: Signal, price: float, df: pd.DataFrame, qty: float) -> RiskDecision:
        if signal == Signal.HOLD:
            return RiskDecision(is_allowed=False)

        account = self._broker.get_account()
        atr_val = self._compute_atr(df)
        if atr_val <= 0:
            return RiskDecision(is_allowed=False)

        stop_distance = atr_val * self._config.atr_stop_multiple
        tp_distance = atr_val * self._config.atr_take_profit_multiple
        risk_amount = account.cash * (self._config.risk_per_trade_pct / 100.0)
        max_pos_value = account.cash * (self._config.max_position_size_pct / 100.0)

        risk_based_size = risk_amount / stop_distance
        cash_based_size = max_pos_value / price if price > 0 else qty
        size = min(qty, risk_based_size, cash_based_size)

        if signal == Signal.BUY:
            stop_loss = price - stop_distance
            take_profit = price + tp_distance
        else:
            stop_loss = price + stop_distance
            take_profit = price - tp_distance

        is_allowed = size > 0 and risk_amount > 0

        return RiskDecision(
            position_size=round(size, 4),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            is_allowed=is_allowed,
        )

    def _compute_atr(self, df: pd.DataFrame) -> float:
        atr_series = atr(df["high"], df["low"], df["close"], self._config.atr_period)
        return float(atr_series.iloc[-1])

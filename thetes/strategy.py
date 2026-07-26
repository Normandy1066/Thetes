"""strategy.py

Algorithmic day-trading signal generator.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Tuple

import pandas as pd

from thetes.config import Config
from thetes.enums import Signal
from thetes.indicators import (
    AdxState,
    AtrState,
    EmaState,
    RsiState,
    adx,
    adx_incremental,
    adx_state_from_series,
    atr,
    atr_incremental,
    atr_state_from_series,
    ema,
    ema_incremental,
    rsi,
    rsi_incremental,
    rsi_state_from_series,
    volume_sma,
)
from thetes.models import IndicatorValues

_DEFAULT_CONFIG = Config()


@dataclass
class IndicatorCache:
    ema9_state: EmaState
    ema21_state: EmaState
    ema_trend_state: EmaState
    rsi_state: RsiState
    atr_state: AtrState
    adx_state: AdxState
    volume_deque: deque[float]
    volume_sum: float
    volume_sma: float
    prev_close: float
    cooldown_buy: int
    cooldown_sell: int


def _config_or_default(cfg: Config | None) -> Config:
    return cfg if cfg is not None else _DEFAULT_CONFIG


def _validate_dataframe(df: pd.DataFrame, cfg: Config | None = None) -> None:
    cfg = _config_or_default(cfg)
    required_cols = {"open", "high", "low", "close", "volume"}
    if df.empty:
        raise ValueError("Input DataFrame is empty.")
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")
    min_rows = max(cfg.ema_trend, 21)
    if len(df) < min_rows:
        raise ValueError(f"DataFrame must contain at least {min_rows} rows.")


def generate_signals(df: pd.DataFrame, cfg: Config | None = None) -> Tuple[Signal, IndicatorValues]:
    return _generate_impl(df, None, cfg)[:2]


def generate_signals_cached(
    df: pd.DataFrame, cache: IndicatorCache | None, cfg: Config | None = None
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    return _generate_impl(df, cache, cfg)


def _generate_impl(
    df: pd.DataFrame, cache: IndicatorCache | None, cfg: Config | None
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    cfg = _config_or_default(cfg)
    _validate_dataframe(df, cfg)

    if cache is not None and _can_use_cache(df, cache):
        return _compute_from_cache(df, cache, cfg)
    return _compute_full(df, cfg)


def _can_use_cache(df: pd.DataFrame, cache: IndicatorCache) -> bool:
    if len(df) < 2:
        return False
    return float(df["close"].iloc[-2]) == cache.prev_close


def _volume_ratio(volume: pd.Series, sma: float) -> float:
    return float(volume.iloc[-1] / sma) if sma > 0 else 1.0


def _build_indicators(
    ema9_val: float, ema21_val: float, rsi_val: float,
    ema_trend_val: float, atr_val: float, adx_val: float,
    vol_ratio: float,
) -> IndicatorValues:
    return IndicatorValues(
        ema9=round(ema9_val, 4),
        ema21=round(ema21_val, 4),
        rsi=round(rsi_val, 2),
        ema_trend=round(ema_trend_val, 4),
        atr=round(atr_val, 4),
        adx=round(adx_val, 2),
        volume_ratio=round(vol_ratio, 4),
    )


def _decide_signal(
    ema9_prev: float, ema9_val: float,
    ema21_prev: float, ema21_val: float,
    close_val: float, rsi_val: float,
    ema_trend_val: float, adx_val: float,
    vol_ratio: float,
    cooldown_buy: int, cooldown_sell: int,
    cfg: Config,
) -> Signal:
    if cooldown_buy == 0:
        if ema9_prev <= ema21_prev and ema9_val > ema21_val:
            if cfg.rsi_oversold <= rsi_val <= cfg.rsi_overbought:
                if adx_val >= cfg.adx_threshold:
                    if vol_ratio >= cfg.volume_ratio_min:
                        if close_val > ema_trend_val:
                            return Signal.BUY
    if cooldown_sell == 0:
        if ema9_prev >= ema21_prev and ema9_val < ema21_val:
            if adx_val >= cfg.adx_threshold:
                if vol_ratio >= cfg.volume_ratio_min:
                    if close_val < ema_trend_val:
                        return Signal.SELL
    return Signal.HOLD


def _compute_from_cache(
    df: pd.DataFrame, cache: IndicatorCache, cfg: Config
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    close = df["close"]
    new_close = float(close.iloc[-1])
    new_high = float(df["high"].iloc[-1])
    new_low = float(df["low"].iloc[-1])
    new_volume = float(df["volume"].iloc[-1])

    ema9_val, ema9_state = ema_incremental(new_close, cfg.ema_fast, cache.ema9_state)
    ema21_val, ema21_state = ema_incremental(new_close, cfg.ema_slow, cache.ema21_state)
    ema_trend_val, ema_trend_state = ema_incremental(new_close, cfg.ema_trend, cache.ema_trend_state)
    rsi_val, rsi_state = rsi_incremental(new_close, cache.rsi_state)
    atr_val, atr_state = atr_incremental(new_high, new_low, new_close, cache.atr_state)
    adx_val, adx_state = adx_incremental(new_high, new_low, new_close, cache.adx_state)

    vd = cache.volume_deque
    if len(vd) == vd.maxlen:
        volume_sum = cache.volume_sum - vd[0]
    else:
        volume_sum = cache.volume_sum
    vd.append(new_volume)
    volume_sum += new_volume
    vol_sma = volume_sum / len(vd)
    vol_ratio = new_volume / vol_sma if vol_sma > 0 else 1.0

    cb = max(0, cache.cooldown_buy - 1)
    cs = max(0, cache.cooldown_sell - 1)

    signal = _decide_signal(
        ema9_prev=cache.ema9_state.value,
        ema9_val=ema9_val,
        ema21_prev=cache.ema21_state.value,
        ema21_val=ema21_val,
        close_val=new_close,
        rsi_val=rsi_val,
        ema_trend_val=ema_trend_val,
        adx_val=adx_val,
        vol_ratio=vol_ratio,
        cooldown_buy=cb,
        cooldown_sell=cs,
        cfg=cfg,
    )

    if signal == Signal.BUY:
        cb = cfg.cooldown_candles
    elif signal == Signal.SELL:
        cs = cfg.cooldown_candles

    indicators = _build_indicators(ema9_val, ema21_val, rsi_val, ema_trend_val, atr_val, adx_val, vol_ratio)

    new_cache = IndicatorCache(
        ema9_state=ema9_state,
        ema21_state=ema21_state,
        ema_trend_state=ema_trend_state,
        rsi_state=rsi_state,
        atr_state=atr_state,
        adx_state=adx_state,
        volume_deque=vd,
        volume_sum=volume_sum,
        volume_sma=vol_sma,
        prev_close=new_close,
        cooldown_buy=cb,
        cooldown_sell=cs,
    )
    return signal, indicators, new_cache


def _compute_full(
    df: pd.DataFrame, cfg: Config
) -> Tuple[Signal, IndicatorValues, IndicatorCache]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    ema9_s = ema(close, cfg.ema_fast)
    ema21_s = ema(close, cfg.ema_slow)
    ema_trend_s = ema(close, cfg.ema_trend)
    rsi_s = rsi(close, cfg.rsi_period)
    atr_s = atr(high, low, close, cfg.atr_period)
    adx_s = adx(high, low, close, cfg.adx_period)
    vol_sma_s = volume_sma(volume, cfg.volume_ma_period)

    ema9_val = float(ema9_s.iloc[-1])
    ema21_val = float(ema21_s.iloc[-1])
    ema_trend_val = float(ema_trend_s.iloc[-1])
    rsi_val = float(rsi_s.iloc[-1])
    atr_val = float(atr_s.iloc[-1])
    adx_val = float(adx_s.iloc[-1])
    close_val = float(close.iloc[-1])

    vol_sma_val = float(vol_sma_s.iloc[-1])
    vol_ratio = float(volume.iloc[-1] / vol_sma_val) if vol_sma_val > 0 else 1.0

    ema9_prev = float(ema9_s.iloc[-2])
    ema21_prev = float(ema21_s.iloc[-2])

    signal = _decide_signal(
        ema9_prev=ema9_prev,
        ema9_val=ema9_val,
        ema21_prev=ema21_prev,
        ema21_val=ema21_val,
        close_val=close_val,
        rsi_val=rsi_val,
        ema_trend_val=ema_trend_val,
        adx_val=adx_val,
        vol_ratio=vol_ratio,
        cooldown_buy=0,
        cooldown_sell=0,
        cfg=cfg,
    )

    cb = cfg.cooldown_candles if signal == Signal.BUY else 0
    cs = cfg.cooldown_candles if signal == Signal.SELL else 0

    indicators = _build_indicators(ema9_val, ema21_val, rsi_val, ema_trend_val, atr_val, adx_val, vol_ratio)

    volume_vals = list(volume.iloc[-cfg.volume_ma_period:])

    cache = IndicatorCache(
        ema9_state=EmaState(value=ema9_val, span=cfg.ema_fast),
        ema21_state=EmaState(value=ema21_val, span=cfg.ema_slow),
        ema_trend_state=EmaState(value=ema_trend_val, span=cfg.ema_trend),
        rsi_state=rsi_state_from_series(close, cfg.rsi_period),
        atr_state=atr_state_from_series(high, low, close, cfg.atr_period),
        adx_state=adx_state_from_series(high, low, close, cfg.adx_period),
        volume_deque=deque(volume_vals, maxlen=cfg.volume_ma_period),
        volume_sum=sum(volume_vals),
        volume_sma=vol_sma_val,
        prev_close=close_val,
        cooldown_buy=cb,
        cooldown_sell=cs,
    )
    return signal, indicators, cache

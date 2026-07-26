"""Centralized configuration for the Thetes trading bot.

All environment-variable reading happens here.  Every other module receives a
``Config`` instance instead of calling ``os.getenv`` directly.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional

# Optional dotenv — ignored if not installed.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = lambda *a, **kw: None  # type: ignore[assignment]


@dataclass(frozen=True)
class Config:
    """Immutable application configuration read from environment variables."""

    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    trading_symbol: str = "AAPL"
    trade_qty: float = 1.0
    loop_delay_seconds: int = 10
    max_iterations: Optional[int] = None  # None = infinite

    log_level: str = "INFO"

    # Risk management
    risk_per_trade_pct: float = 1.0
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    atr_take_profit_multiple: float = 3.0
    max_position_size_pct: float = 100.0

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> Config:
        """Create a ``Config`` from environment variables (+ ``.env`` file)."""
        load_dotenv()

        max_iter_raw = os.getenv("MAX_ITERATIONS", "").strip()
        max_iterations: Optional[int] = int(max_iter_raw) if max_iter_raw else None

        return cls(
            alpaca_api_key=os.getenv("ALPACA_API_KEY"),
            alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY"),
            alpaca_base_url=os.getenv(
                "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
            ),
            trading_symbol=os.getenv("TRADING_SYMBOL", "AAPL"),
            trade_qty=float(os.getenv("TRADE_QTY", "1")),
            loop_delay_seconds=int(os.getenv("LOOP_DELAY_SECONDS", "10")),
            max_iterations=max_iterations,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE_PCT", "1.0")),
            atr_period=int(os.getenv("ATR_PERIOD", "14")),
            atr_stop_multiple=float(os.getenv("ATR_STOP_MULTIPLE", "2.0")),
            atr_take_profit_multiple=float(os.getenv("ATR_TAKE_PROFIT_MULTIPLE", "3.0")),
            max_position_size_pct=float(os.getenv("MAX_POSITION_SIZE_PCT", "100.0")),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_mock_mode(self) -> bool:
        """Return ``True`` when credentials are missing or placeholder values."""
        placeholder_keys = {
            "YOUR_ALPACA_API_KEY",
            "YOUR_ALPACA_SECRET_KEY",
            "PAPER_API_KEY",
            "PAPER_SECRET_KEY",
            None,
            "",
        }
        return (
            self.alpaca_api_key in placeholder_keys
            or self.alpaca_secret_key in placeholder_keys
        )

    def configure_logging(self) -> None:
        """Set up the root logger once, based on ``log_level``."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

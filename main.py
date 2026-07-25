"""main.py

Entry point for the algorithmic day‑trading bot.

It ties together the data ingestion, signal generation, and order execution
modules we built earlier (`data.py`, `strategy.py`, `execution.py`).
The script reads configuration from a ``.env`` file (via ``python-dotenv``),
runs a configurable loop (default 5 minutes), and logs each iteration in a
human‑readable format.

The loop is resilient – any exception raised by a single API call is caught
and logged without terminating the bot.  A graceful shutdown handler ensures
the program can be stopped with ``Ctrl+C`` without leaving stray resources.
"""

from __future__ import annotations

import os
import time
import logging
import datetime
import signal
import sys
from typing import Tuple, Dict, Any

# Optional dotenv import – ignored if not installed
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda *args, **kwargs: None  # type: ignore


# Local modules – import after the environment is loaded so that any module
# which reads env vars at import time gets the correct values.

# The import paths assume these files live in the same workspace directory.
# They will be resolved relative to the current working directory when the
# script is executed.

# Lazy imports are fine because they do not have side‑effects besides defining
# functions.

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------
load_dotenv()  # load .env if available, otherwise continue

# Default configuration – can be overridden by the .env file.
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
TRADING_SYMBOL = os.getenv("TRADING_SYMBOL", "AAPL")
TRADE_QTY = float(os.getenv("TRADE_QTY", "1"))
LOOP_DELAY_SECONDS = int(os.getenv("LOOP_DELAY_SECONDS", "5"))  # 5 seconds for stress test

# Basic logging configuration – the user can change the level via env var if
# needed.
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Import our helper modules only after the environment is set up.
try:
    from data import get_latest_candles
    from strategy import generate_signals
    from execution import (
        place_buy_order,
        place_sell_order,
        get_account_status,
    )
except Exception as exc:
    logging.error("Failed to import internal modules: %s", exc)
    sys.exit(1)


def _graceful_exit(signum, frame):  # pragma: no cover
    """Signal handler for clean termination (Ctrl+C)."""
    logging.info("Received shutdown signal – exiting loop gracefully.")
    sys.exit(0)

# Register the handler for SIGINT (Ctrl+C) and SIGTERM.
signal.signal(signal.SIGINT, _graceful_exit)
signal.signal(signal.SIGTERM, _graceful_exit)


def _run_iteration() -> None:
    """Execute a single trading loop iteration.

    Steps:
        1. Pull the latest candles.
        2. Generate a signal and capture indicator values.
        3. If BUY/SELL, place the appropriate order.
        4. Log a concise status line.
    """
    try:
        df = get_latest_candles(TRADING_SYMBOL, timeframe="5Min", limit=100)
        if df.empty:
            logging.warning("No candle data retrieved – skipping iteration.")
            return
    except Exception as exc:
        logging.error("Error fetching candle data: %s", exc)
        return

    try:
        signal_str, indicator_vals = generate_signals(df)
    except Exception as exc:
        logging.error("Error generating signal: %s", exc)
        return

    # Default action description – may be overwritten if an order is placed.
    action_desc = "No action"

    if signal_str == "BUY":
        try:
            order = place_buy_order(TRADING_SYMBOL, TRADE_QTY)
            action_desc = f"Buy order placed (order_id={getattr(order, 'id', 'N/A')})"
        except Exception as exc:
            logging.error("Buy order failed: %s", exc)
            action_desc = f"Buy order error: {exc}"
    elif signal_str == "SELL":
        try:
            order = place_sell_order(TRADING_SYMBOL, TRADE_QTY)
            action_desc = f"Sell order placed (order_id={getattr(order, 'id', 'N/A')})"
        except Exception as exc:
            logging.error("Sell order failed: %s", exc)
            action_desc = f"Sell order error: {exc}"
    else:
        # HOLD – no trade.
        pass

    # Retrieve a quick snapshot of the account after any order attempt.
    try:
        acct = get_account_status()
        cash = acct.get("cash", 0.0)
        buying_power = acct.get("buying_power", 0.0)
    except Exception as exc:
        logging.error("Failed to get account status: %s", exc)
        cash = buying_power = None

    # Compose the log line.
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_parts = [
        f"Timestamp: {now}",
        f"Symbol: {TRADING_SYMBOL}",
        f"Signal: {signal_str}",
        f"EMA9: {indicator_vals.get('ema9'):.4f}",
        f"EMA21: {indicator_vals.get('ema21'):.4f}",
        f"RSI: {indicator_vals.get('rsi'):.2f}",
    ]
    if cash is not None:
        log_parts.append(f"Cash: ${cash:,.2f}")
    if buying_power is not None:
        log_parts.append(f"BuyingPower: ${buying_power:,.2f}")
    log_parts.append(f"Action: {action_desc}")

    logging.info(" | ".join(log_parts))


def main() -> None:
    """Main loop – runs for a limited number of iterations during stress test."""
    max_iters = int(os.getenv("MAX_ITERATIONS", "3"))
    logging.info("Starting trading bot – symbol=%s, qty=%s, max_iters=%s", TRADING_SYMBOL, TRADE_QTY, max_iters)
    for i in range(max_iters):
        _run_iteration()
        logging.info("Completed iteration %s of %s", i + 1, max_iters)
        if i < max_iters - 1:
            logging.info("Sleeping for %s seconds before next iteration...", LOOP_DELAY_SECONDS)
            time.sleep(LOOP_DELAY_SECONDS)
    logging.info("Stress test completed – exiting gracefully.")


if __name__ == "__main__":
    main()

"""main.py

CLI entry point for the algorithmic day-trading bot.
Runs the TradingEngine in a console loop.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from thetes.config import Config
from thetes.mock_broker import MockBroker
from thetes.alpaca_broker import AlpacaBroker
from thetes.mock_data import MockDataProvider
from thetes.engine import TradingEngine

# 1. Initialize configuration and logging
config = Config.from_env()
config.configure_logging()
logger = logging.getLogger(__name__)

# 2. Instantiate dependencies
if config.is_mock_mode():
    logger.info("Using MockBroker (no valid Alpaca credentials provided).")
    broker = MockBroker()
else:
    logger.info("Using AlpacaBroker with paper-trading endpoint.")
    broker = AlpacaBroker(config)

data_provider = MockDataProvider()

# 3. Create the trading engine
engine = TradingEngine(config, broker, data_provider)


# 4. Graceful shutdown handler
def _graceful_exit(signum, frame):
    logger.info("Received shutdown signal – exiting gracefully.")
    engine.stop()
    sys.exit(0)


signal.signal(signal.SIGINT, _graceful_exit)
signal.signal(signal.SIGTERM, _graceful_exit)


def main() -> None:
    logger.info(
        "Starting trading bot CLI – symbol=%s, qty=%s, max_iterations=%s",
        config.trading_symbol,
        config.trade_qty,
        config.max_iterations,
    )

    max_iters = config.max_iterations

    # If max_iterations is set, run a bounded loop on the main thread
    if max_iters is not None:
        for i in range(max_iters):
            # Update iteration count in engine state for logging consistency
            with engine._state_lock:
                engine._state.iteration += 1
                current_iter = engine._state.iteration
            
            logger.info("Executing iteration %d of %d", current_iter, max_iters)
            engine.run_once()
            
            if i < max_iters - 1:
                logger.info("Sleeping for %d seconds...", config.loop_delay_seconds)
                time.sleep(config.loop_delay_seconds)
        logger.info("Stress test completed – exiting gracefully.")
    else:
        # Otherwise, start background thread and wait indefinitely
        engine.start()
        logger.info("Bot running in background thread. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()

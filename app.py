"""app.py

Flask web application that wraps the trading bot with a real-time dashboard.
Defines endpoints that poll/control the TradingEngine.
"""

from __future__ import annotations

import logging
from flask import Flask, render_template, jsonify, request

from thetes.config import Config
from thetes.enums import BotStatus
from thetes.mock_broker import MockBroker
from thetes.alpaca_broker import AlpacaBroker
from thetes.mock_data import MockDataProvider
from thetes.alpaca_data import AlpacaDataProvider
from thetes.engine import TradingEngine

# 1. Initialize configuration and logging
config = Config.from_env()
config.configure_logging()
logger = logging.getLogger(__name__)

# 2. Instantiate dependencies
# Use AlpacaBroker and AlpacaDataProvider if credentials are valid, otherwise fallback to mock
if config.is_mock_mode():
    logger.info("Using MockBroker and MockDataProvider (no valid Alpaca credentials provided).")
    broker = MockBroker()
    data_provider = MockDataProvider()
else:
    logger.info("Using AlpacaBroker and AlpacaDataProvider with paper-trading endpoint.")
    broker = AlpacaBroker(config)
    data_provider = AlpacaDataProvider(config)

# 3. Create the trading engine
engine = TradingEngine(config, broker, data_provider)

# 4. Set up Flask app
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    """Return the JSON representation of current bot state."""
    return jsonify(engine.get_state_dict())


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start the trading bot loop."""
    state = engine.get_state()
    if state.status == BotStatus.RUNNING:
        return jsonify({"status": "already_running"})

    # Parse potential runtime overrides from frontend
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol")
    
    trade_qty = None
    if "trade_qty" in data:
        trade_qty = float(data["trade_qty"])

    loop_delay = None
    if "loop_delay" in data:
        loop_delay = int(data["loop_delay"])

    engine.start(symbol=symbol, trade_qty=trade_qty, loop_delay=loop_delay)
    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop the trading bot loop."""
    state = engine.get_state()
    if state.status == BotStatus.STOPPED:
        return jsonify({"status": "not_running"})

    engine.stop()
    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    logger.info("Starting web dashboard at http://127.0.0.1:5000")
    # Bind to all addresses for access on local networks
    app.run(host="0.0.0.0", port=5000, debug=False)

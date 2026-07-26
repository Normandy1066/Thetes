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
from thetes.ticker_manager import TickerManager

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

# 4. Create ticker manager service
ticker_manager = TickerManager(engine, config, data_provider)

# 5. Set up Flask app
app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_header(r):
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r

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
    try:
        print("API START CALLED")
        state = engine.get_state()
        if state.status == BotStatus.RUNNING:
            return jsonify({"status": "already_running"}), 200

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
        return jsonify({"status": "started"}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop the trading bot loop."""
    state = engine.get_state()
    if state.status == BotStatus.STOPPED:
        return jsonify({"status": "not_running"})

    engine.stop()
    return jsonify({"status": "stopped"})


# ---------------------------------------------------------------------------
# Ticker management endpoints
# ---------------------------------------------------------------------------


@app.route("/api/tickers", methods=["GET"])
def api_get_tickers():
    """Return the current list of tracked tickers."""
    return jsonify({"tickers": ticker_manager.get_tickers()})


@app.route("/api/tickers", methods=["PUT"])
def api_replace_tickers():
    """Replace the entire ticker list."""
    try:
        data = request.get_json(silent=True) or {}
        symbols = data.get("symbols", [])
        if not isinstance(symbols, list):
            return jsonify({"error": "symbols must be a list"}), 400
        result = ticker_manager.replace_tickers(symbols)
        return jsonify({"tickers": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Failed to replace tickers")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickers", methods=["POST"])
def api_add_ticker():
    """Add a ticker to the tracked list."""
    try:
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "")
        result = ticker_manager.add_ticker(symbol)
        return jsonify({"tickers": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Failed to add ticker")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickers", methods=["DELETE"])
def api_remove_ticker():
    """Remove a ticker from the tracked list."""
    try:
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "")
        result = ticker_manager.remove_ticker(symbol)
        return jsonify({"tickers": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Failed to remove ticker")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    logger.info("Starting web dashboard at http://127.0.0.1:5000")
    # Bind to all addresses for access on local networks
    app.run(host="0.0.0.0", port=5000, debug=False)

"""app.py

Flask web application that wraps the trading bot with a real-time dashboard.
Runs the bot loop in a background thread and exposes API endpoints for the
frontend to poll.
"""

from __future__ import annotations

import os
import sys
import time
import json
import logging
import datetime
import threading
from collections import deque
from typing import Any, Dict, List

from flask import Flask, render_template, jsonify, request

# ---------------------------------------------------------------------------
# dotenv
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Import our bot modules
# ---------------------------------------------------------------------------
from data import get_latest_candles
from strategy import generate_signals
from execution import place_buy_order, place_sell_order, get_account_status

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Shared state  (thread-safe via the GIL for simple reads/writes)
# ---------------------------------------------------------------------------
MAX_LOG_ENTRIES = 200

bot_state: Dict[str, Any] = {
    "running": False,
    "symbol": os.getenv("TRADING_SYMBOL", "AAPL"),
    "trade_qty": float(os.getenv("TRADE_QTY", "1")),
    "loop_delay": int(os.getenv("LOOP_DELAY_SECONDS", "10")),
    "iteration": 0,
    "last_signal": "—",
    "last_ema9": 0.0,
    "last_ema21": 0.0,
    "last_rsi": 0.0,
    "last_close": 0.0,
    "cash": 100_000.0,
    "buying_power": 400_000.0,
    "positions": [],
    "total_trades": 0,
    "buy_count": 0,
    "sell_count": 0,
    "started_at": None,
}

trade_log: deque = deque(maxlen=MAX_LOG_ENTRIES)
price_history: deque = deque(maxlen=100)
signal_history: deque = deque(maxlen=100)

_stop_event = threading.Event()
_bot_thread: threading.Thread | None = None


def _bot_loop() -> None:
    """Background loop that mirrors main.py logic but writes to shared state."""
    global bot_state
    symbol = bot_state["symbol"]
    qty = bot_state["trade_qty"]
    delay = bot_state["loop_delay"]
    bot_state["started_at"] = datetime.datetime.now().isoformat()

    while not _stop_event.is_set():
        bot_state["iteration"] += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry: Dict[str, Any] = {"timestamp": ts, "iteration": bot_state["iteration"]}

        # 1. Fetch candles
        try:
            df = get_latest_candles(symbol, timeframe="5Min", limit=100)
            if df.empty:
                entry["error"] = "No candle data"
                trade_log.appendleft(entry)
                _sleep_or_stop(delay)
                continue
            last_close = float(df["close"].iloc[-1])
            bot_state["last_close"] = last_close
            price_history.append({"t": ts, "price": round(last_close, 2)})
        except Exception as exc:
            entry["error"] = str(exc)
            trade_log.appendleft(entry)
            _sleep_or_stop(delay)
            continue

        # 2. Generate signal
        try:
            signal_str, indicators = generate_signals(df)
            bot_state["last_signal"] = signal_str
            bot_state["last_ema9"] = round(indicators.get("ema9", 0), 4)
            bot_state["last_ema21"] = round(indicators.get("ema21", 0), 4)
            bot_state["last_rsi"] = round(indicators.get("rsi", 0), 2)
            entry["signal"] = signal_str
            entry["ema9"] = bot_state["last_ema9"]
            entry["ema21"] = bot_state["last_ema21"]
            entry["rsi"] = bot_state["last_rsi"]
            entry["close"] = round(last_close, 2)
            signal_history.append({"t": ts, "signal": signal_str})
        except Exception as exc:
            entry["error"] = str(exc)
            trade_log.appendleft(entry)
            _sleep_or_stop(delay)
            continue

        # 3. Execute
        action = "HOLD"
        if signal_str == "BUY":
            try:
                place_buy_order(symbol, qty)
                action = "BUY ORDER PLACED"
                bot_state["buy_count"] += 1
                bot_state["total_trades"] += 1
            except Exception as exc:
                action = f"BUY FAILED: {exc}"
        elif signal_str == "SELL":
            try:
                place_sell_order(symbol, qty)
                action = "SELL ORDER PLACED"
                bot_state["sell_count"] += 1
                bot_state["total_trades"] += 1
            except Exception as exc:
                action = f"SELL FAILED: {exc}"
        entry["action"] = action

        # 4. Account snapshot
        try:
            acct = get_account_status()
            bot_state["cash"] = acct.get("cash", 0)
            bot_state["buying_power"] = acct.get("buying_power", 0)
            pos_df = acct.get("positions")
            if pos_df is not None and not pos_df.empty:
                bot_state["positions"] = pos_df.to_dict("records")
            else:
                bot_state["positions"] = []
        except Exception:
            pass

        entry["cash"] = bot_state["cash"]
        entry["buying_power"] = bot_state["buying_power"]
        trade_log.appendleft(entry)

        _sleep_or_stop(delay)

    bot_state["running"] = False


def _sleep_or_stop(seconds: int) -> None:
    """Sleep in small increments so we can respond to stop quickly."""
    for _ in range(seconds * 10):
        if _stop_event.is_set():
            return
        time.sleep(0.1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    """Return the full bot state + recent trade log."""
    return jsonify({
        **bot_state,
        "trade_log": list(trade_log),
        "price_history": list(price_history),
        "signal_history": list(signal_history),
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    global _bot_thread
    if bot_state["running"]:
        return jsonify({"status": "already_running"})
    # Apply optional overrides from the request
    data = request.get_json(silent=True) or {}
    if "symbol" in data:
        bot_state["symbol"] = data["symbol"]
    if "trade_qty" in data:
        bot_state["trade_qty"] = float(data["trade_qty"])
    if "loop_delay" in data:
        bot_state["loop_delay"] = int(data["loop_delay"])

    _stop_event.clear()
    bot_state["running"] = True
    bot_state["iteration"] = 0
    bot_state["total_trades"] = 0
    bot_state["buy_count"] = 0
    bot_state["sell_count"] = 0
    trade_log.clear()
    price_history.clear()
    signal_history.clear()
    _bot_thread = threading.Thread(target=_bot_loop, daemon=True)
    _bot_thread.start()
    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not bot_state["running"]:
        return jsonify({"status": "not_running"})
    _stop_event.set()
    bot_state["running"] = False
    return jsonify({"status": "stopped"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    print("\n  >>> Trading Bot Dashboard running at  http://127.0.0.1:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)

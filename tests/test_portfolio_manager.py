"""Comprehensive unit tests for PortfolioManager."""

import pytest
from thetes.portfolio_manager import PortfolioManager


def test_initial_state():
    pm = PortfolioManager(starting_cash=10000.0)
    assert pm.cash == 10000.0
    assert pm.starting_cash == 10000.0
    assert pm.available_cash() == 10000.0
    assert pm.realized_pnl == 0.0
    assert pm.get_positions() == {}
    assert pm.portfolio_value({}) == 10000.0
    assert pm.total_return({}) == 0.0


def test_initial_state_custom_buying_power():
    pm = PortfolioManager(starting_cash=5000.0, buying_power=25000.0)
    assert pm.buying_power == 25000.0


def test_can_afford_true():
    pm = PortfolioManager(starting_cash=1000.0)
    assert pm.can_afford({"qty": 5, "price": 100.0}) is True


def test_can_afford_false():
    pm = PortfolioManager(starting_cash=100.0)
    assert pm.can_afford({"qty": 3, "price": 50.0}) is False


def test_can_afford_exact():
    pm = PortfolioManager(starting_cash=100.0)
    assert pm.can_afford({"qty": 2, "price": 50.0}) is True


def test_execute_buy_reduces_cash():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    assert pm.cash == 500.0
    assert pm.available_cash() == 500.0


def test_execute_buy_increases_buying_power():
    pm = PortfolioManager(starting_cash=1000.0, buying_power=4000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    assert pm.buying_power == 4500.0


def test_execute_buy_creates_position():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    positions = pm.get_positions()
    assert positions == {"AAPL": {"qty": 10.0, "avg_price": 50.0}}


def test_execute_buy_averages_position():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_buy("AAPL", 10, price=70.0)
    pos = pm.get_positions()["AAPL"]
    assert pos["qty"] == 20.0
    assert pos["avg_price"] == 60.0  # (10*50 + 10*70) / 20


def test_execute_buy_insufficient_cash():
    pm = PortfolioManager(starting_cash=100.0)
    with pytest.raises(RuntimeError, match="Insufficient cash"):
        pm.execute_buy("AAPL", 3, price=50.0)


def test_execute_sell_increases_cash():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 5, price=60.0)
    assert pm.cash == 800.0  # 500 (after buy) + 300 (sale proceeds)


def test_execute_sell_decreases_buying_power():
    pm = PortfolioManager(starting_cash=1000.0, buying_power=4000.0)
    pm.execute_buy("AAPL", 10, price=50.0)  # bp -> 4500
    pm.execute_sell("AAPL", 5, price=60.0)  # proceeds = 300, bp -> 4200
    assert pm.buying_power == 4200.0


def test_execute_sell_reduces_position():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 4, price=55.0)
    pos = pm.get_positions()["AAPL"]
    assert pos["qty"] == 6.0


def test_execute_sell_removes_position_when_zero():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 10, price=55.0)
    assert pm.get_positions() == {}


def test_execute_sell_insufficient_position():
    pm = PortfolioManager(starting_cash=1000.0)
    with pytest.raises(RuntimeError, match="Insufficient position"):
        pm.execute_sell("AAPL", 1, price=50.0)


def test_execute_sell_exceeds_position():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 5, price=50.0)
    with pytest.raises(RuntimeError, match="Insufficient position"):
        pm.execute_sell("AAPL", 10, price=55.0)


def test_realized_pnl_profit():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 10, price=60.0)
    assert pm.realized_pnl == 100.0  # (60 - 50) * 10


def test_realized_pnl_loss():
    pm = PortfolioManager(starting_cash=1000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 10, price=40.0)
    assert pm.realized_pnl == -100.0


def test_realized_pnl_accumulates():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=50.0)
    pm.execute_sell("AAPL", 5, price=60.0)   # realized = 50
    pm.execute_sell("AAPL", 5, price=40.0)   # realized = -50
    assert pm.realized_pnl == 0.0


def test_realized_pnl_partial_sell():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=100.0)
    pm.execute_sell("AAPL", 3, price=110.0)  # realized = 30
    assert pm.realized_pnl == 30.0
    pos = pm.get_positions()["AAPL"]
    assert pos["qty"] == 7.0
    assert pos["avg_price"] == 100.0


def test_multiple_symbols():
    pm = PortfolioManager(starting_cash=100000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    pm.execute_buy("MSFT", 5, price=300.0)
    assert pm.cash == 100000.0 - 1500.0 - 1500.0  # 97000
    positions = pm.get_positions()
    assert set(positions.keys()) == {"AAPL", "MSFT"}


def test_portfolio_value():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)   # cost 1500
    pm.execute_buy("MSFT", 5, price=200.0)    # cost 1000
    # cash = 10000 - 1500 - 1000 = 7500
    # MV = 10 * 160 + 5 * 210 = 1600 + 1050 = 2650
    total = pm.portfolio_value({"AAPL": 160.0, "MSFT": 210.0})
    assert total == 7500.0 + 2650.0


def test_portfolio_value_with_missing_price():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    # If price missing, uses avg_entry_price (150)
    total = pm.portfolio_value({"OTHER": 999.0})
    assert total == (10000.0 - 1500.0) + 10 * 150.0


def test_unrealized_pnl():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    upnl = pm.unrealized_pnl({"AAPL": 160.0})
    assert upnl == 100.0  # (160 - 150) * 10


def test_unrealized_pnl_multiple_symbols():
    pm = PortfolioManager(starting_cash=100000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    pm.execute_buy("MSFT", 5, price=200.0)
    upnl = pm.unrealized_pnl({"AAPL": 160.0, "MSFT": 190.0})
    assert upnl == 10 * 10.0 + 5 * (-10.0)  # 100 - 50 = 50


def test_unrealized_pnl_no_positions():
    pm = PortfolioManager(starting_cash=10000.0)
    assert pm.unrealized_pnl({"AAPL": 200.0}) == 0.0


def test_total_return():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)  # cost 1500
    # cash = 8500, MV = 10 * 160 = 1600
    ret = pm.total_return({"AAPL": 160.0})
    expected = (8500.0 + 1600.0 - 10000.0) / 10000.0
    assert ret == pytest.approx(expected)


def test_total_return_zero_starting():
    pm = PortfolioManager(starting_cash=0.0)
    assert pm.total_return({}) == 0.0


def test_account_snapshot_no_prices():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    snap = pm.get_account_snapshot()
    assert snap.cash == 8500.0
    assert len(snap.positions) == 1
    assert snap.positions[0].market_value == 1500.0   # qty * avg_price
    assert snap.positions[0].unrealized_pl == 0.0
    assert snap.equity == 10000.0                     # cash + MV at avg_price
    assert snap.realized_pnl == 0.0
    assert snap.unrealized_pnl == 0.0


def test_account_snapshot_with_prices():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=150.0)
    snap = pm.get_account_snapshot({"AAPL": 170.0})
    assert snap.positions[0].market_value == 1700.0
    assert snap.positions[0].unrealized_pl == 200.0
    assert snap.equity == 8500.0 + 1700.0
    assert snap.unrealized_pnl == 200.0


def test_account_snapshot_realized_pnl():
    pm = PortfolioManager(starting_cash=10000.0)
    pm.execute_buy("AAPL", 10, price=100.0)
    pm.execute_sell("AAPL", 5, price=110.0)
    snap = pm.get_account_snapshot()
    assert snap.realized_pnl == 50.0


def test_available_cash_equals_cash():
    pm = PortfolioManager(starting_cash=5000.0)
    assert pm.available_cash() == pm.cash
    pm.execute_buy("AAPL", 10, price=100.0)
    assert pm.available_cash() == pm.cash


def test_thread_safety():
    import threading

    pm = PortfolioManager(starting_cash=100000.0)
    errors = []

    def buyer():
        try:
            for _ in range(50):
                pm.execute_buy("AAPL", 1, 100.0)
                pm.execute_sell("AAPL", 1, 101.0)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=buyer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_trades = 4 * 50
    assert not errors
    assert pm.get_positions() == {}
    assert pm.cash == 100000.0 + total_trades * 1.0  # $1 profit per round-trip
    assert pm.realized_pnl == total_trades * 1.0

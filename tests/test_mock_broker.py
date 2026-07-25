import pytest
from thetes.mock_broker import MockBroker


def test_mock_broker_initial_state():
    broker = MockBroker(initial_cash=500.0, initial_buying_power=2000.0)
    acct = broker.get_account()
    assert acct.cash == 500.0
    assert acct.buying_power == 2000.0
    assert len(acct.positions) == 0


def test_mock_broker_buy_insufficient_cash():
    broker = MockBroker(initial_cash=100.0)
    with pytest.raises(RuntimeError, match="Insufficient cash"):
        broker.buy("AAPL", 2, price=60.0)  # Cost 120.0 > 100.0


def test_mock_broker_buy_sell_flow():
    broker = MockBroker(initial_cash=1000.0, initial_buying_power=4000.0)
    
    # 1. Buy AAPL
    buy_res = broker.buy("AAPL", 2, price=150.0)  # Cost 300.0
    assert buy_res["id"] == "mock-buy-order"
    
    acct = broker.get_account()
    assert acct.cash == 700.0
    assert len(acct.positions) == 1
    assert acct.positions[0].symbol == "AAPL"
    assert acct.positions[0].qty == 2.0
    assert acct.positions[0].avg_entry_price == 150.0

    # 2. Sell part of position
    broker.sell("AAPL", 1, price=160.0)  # Proceeds 160.0
    acct = broker.get_account()
    assert acct.cash == 860.0
    assert len(acct.positions) == 1
    assert acct.positions[0].qty == 1.0

    # 3. Sell remainder of position
    broker.sell("AAPL", 1, price=170.0)  # Proceeds 170.0
    acct = broker.get_account()
    assert acct.cash == 1030.0
    assert len(acct.positions) == 0


def test_mock_broker_sell_errors():
    broker = MockBroker()
    # Sell with no position should raise error
    with pytest.raises(RuntimeError, match="Insufficient position"):
        broker.sell("AAPL", 1, price=150.0)
        
    # Sell more than position should raise error
    broker.buy("AAPL", 1, price=150.0)
    with pytest.raises(RuntimeError, match="Insufficient position"):
        broker.sell("AAPL", 2, price=150.0)

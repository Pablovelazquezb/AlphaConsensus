import unittest

from alphaconsensus.execution.smoke import run_smoke_test


class FakeBroker:
    def __init__(self, market_open: bool = True, reject: bool = False) -> None:
        self.market_open = market_open
        self.reject = reject
        self.positions = []
        self.equity = 1000.0
        self.closed = False
        self.orders = {}

    def get_clock(self):
        return {"is_open": self.market_open, "next_open": "2026-11-20T14:30:00Z"}

    def get_positions(self):
        return list(self.positions)

    def get_account(self):
        return {"equity": self.equity}

    def submit_notional_buy(self, symbol, notional, client_order_id=None):
        order = {"id": "o1", "status": "rejected" if self.reject else "new"}
        self.orders["o1"] = dict(order)
        return order

    def get_order(self, order_id):
        order = dict(self.orders[order_id])
        if order["status"] == "new":
            order.update(
                {"status": "filled", "filled_qty": "0.00147", "filled_avg_price": "680.12"}
            )
            self.positions = [{"symbol": "SPY", "qty": "0.00147"}]
            self.orders[order_id] = dict(order)
        return order

    def close_position(self, symbol):
        self.positions = []
        self.equity = 999.98
        self.closed = True

    def submit_market_order(self, symbol, qty, side, client_order_id=None):
        raise AssertionError("no debería usarse el fallback")


def fast_smoke(broker):
    return run_smoke_test(broker, timeout=1.0, poll=0.0, sleep=lambda _: None)


class SmokeTestTests(unittest.TestCase):
    def test_happy_path_buys_and_closes(self) -> None:
        broker = FakeBroker()
        result = fast_smoke(broker)
        self.assertTrue(result.ok)
        self.assertTrue(result.closed)
        self.assertEqual(result.status, "filled")
        self.assertAlmostEqual(result.qty, 0.00147)
        self.assertTrue(broker.closed)
        self.assertEqual(broker.positions, [])

    def test_market_closed_does_not_send_orders(self) -> None:
        broker = FakeBroker(market_open=False)
        result = fast_smoke(broker)
        self.assertFalse(result.ok)
        self.assertIn("cerrado", result.message)
        self.assertEqual(broker.orders, {})

    def test_existing_position_is_left_alone(self) -> None:
        broker = FakeBroker()
        broker.positions = [{"symbol": "SPY", "qty": "1"}]
        result = fast_smoke(broker)
        self.assertFalse(result.ok)
        self.assertIn("posición", result.message)
        self.assertEqual(broker.orders, {})

    def test_rejected_order_is_reported(self) -> None:
        broker = FakeBroker(reject=True)
        result = fast_smoke(broker)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.closed)


if __name__ == "__main__":
    unittest.main()

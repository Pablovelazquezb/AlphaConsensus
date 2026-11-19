import unittest
from datetime import date, datetime, timezone

from alphaconsensus.config import RiskConfig
from alphaconsensus.credibility.prices import Bar
from alphaconsensus.models import ConsensusSignal, Direction
from alphaconsensus.risk.engine import RiskEngine


def make_signal(direction: Direction = Direction.BULLISH) -> ConsensusSignal:
    now = datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc)
    return ConsensusSignal(
        ticker="AAA",
        direction=direction,
        score=1.5,
        n_accounts=3,
        accounts=["a", "b", "c"],
        window_start=now,
        window_end=now,
        created_at=now,
        avg_confidence=0.8,
    )


def make_bar(price: float) -> Bar:
    return Bar(date=date(2026, 5, 4), open=price, high=price * 1.01, low=price * 0.99, close=price, volume=1_000_000)


class RiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RiskConfig(
            equity=1_000.0,
            risk_per_trade_pct=1.0,
            max_position_pct=24.0,
            max_open_positions=4,
            allow_shorts=False,
            allow_fractional=True,
            fractional_shorts=False,
            min_notional=20.0,
            min_dollar_volume=0.0,
            max_atr_pct=100.0,
        )
        self.risk = RiskEngine(self.config)

    def evaluate(self, price: float, atr: float = 5.0, equity: float = 1_000.0, peak: float = 1_000.0, direction=Direction.BULLISH):
        return self.risk.evaluate(
            make_signal(direction), make_bar(price), atr, 1e12, equity, peak
        )

    def test_small_account_can_size_a_fractional_long(self) -> None:
        decision = self.evaluate(price=300.0)
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.qty, 0.8)

    def test_notional_cap_wins_over_risk_sizing(self) -> None:
        decision = self.evaluate(price=100.0)
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.qty, 1.0)

    def test_whole_share_mode_rounds_to_zero_for_expensive_stock(self) -> None:
        risk = RiskEngine(RiskConfig(**{**self.config.__dict__, "allow_fractional": False}))
        decision = risk.evaluate(make_signal(), make_bar(900.0), 5.0, 1e12, 1_000.0, 1_000.0)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "size_zero")

    def test_shorts_are_disabled_on_this_profile(self) -> None:
        decision = self.evaluate(price=300.0, direction=Direction.BEARISH)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "shorts_disabled")

    def test_kill_switch_blocks_new_positions(self) -> None:
        decision = self.evaluate(price=300.0, equity=800.0, peak=1_000.0)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "kill_switch_drawdown")

    def test_min_notional_is_enforced(self) -> None:
        risk = RiskEngine(RiskConfig(**{**self.config.__dict__, "min_notional": 300.0}))
        decision = risk.evaluate(make_signal(), make_bar(300.0), 5.0, 1e12, 1_000.0, 1_000.0)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "size_too_small")


class AlpacaQuantityTests(unittest.TestCase):
    def test_fractional_qty_formatting(self) -> None:
        from alphaconsensus.execution.alpaca import AlpacaPaperBroker

        self.assertEqual(AlpacaPaperBroker.format_qty(0.8), "0.8")
        self.assertEqual(AlpacaPaperBroker.format_qty(2.0), "2")
        self.assertEqual(AlpacaPaperBroker.format_qty(0.123456), "0.1235")


if __name__ == "__main__":
    unittest.main()

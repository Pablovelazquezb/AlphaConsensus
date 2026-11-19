import unittest
from dataclasses import replace
from datetime import datetime, timezone

from alphaconsensus.credibility.prices import SyntheticMarket
from alphaconsensus.execution.simulator import PaperSimulator
from alphaconsensus.models import ConsensusSignal, Direction


def make_consensus(direction: Direction = Direction.BULLISH) -> ConsensusSignal:
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


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.market = SyntheticMarket.generate(["AAA"], days=40, seed=2)
        self.series = self.market.series["AAA"]
        self.day = self.market.trading_days[10]
        self.bar = self.series.bar_on(self.day)
        self.sim = PaperSimulator(equity=100_000.0, slippage_bps=0.0, commission_per_share=0.0)

    def test_long_stop_exit(self) -> None:
        signal = make_consensus(Direction.BULLISH)
        self.sim.open_position(signal, 10, 100.0, self.day, 10, stop=95.0, target=110.0, horizon_days=5)
        bar = replace(self.bar, open=100.0, high=103.0, low=94.0, close=101.0)
        closed = self.sim.process_bar(self.day, {"AAA": bar}, session=10)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].exit_reason, "stop")
        self.assertAlmostEqual(closed[0].exit_price, 95.0)
        self.assertAlmostEqual(closed[0].pnl, -50.0)

    def test_long_target_exit(self) -> None:
        signal = make_consensus(Direction.BULLISH)
        self.sim.open_position(signal, 10, 100.0, self.day, 10, stop=95.0, target=110.0, horizon_days=5)
        bar = replace(self.bar, open=100.0, high=111.0, low=99.0, close=108.0)
        closed = self.sim.process_bar(self.day, {"AAA": bar}, session=10)
        self.assertEqual(closed[0].exit_reason, "target")
        self.assertAlmostEqual(closed[0].pnl, 100.0)

    def test_horizon_exit(self) -> None:
        signal = make_consensus(Direction.BULLISH)
        self.sim.open_position(signal, 10, 100.0, self.day, 10, stop=50.0, target=200.0, horizon_days=1)
        bar = replace(self.bar, open=100.0, high=103.0, low=99.0, close=102.0)
        closed = self.sim.process_bar(self.day, {"AAA": bar}, session=10)
        self.assertEqual(closed[0].exit_reason, "horizon")
        self.assertAlmostEqual(closed[0].pnl, 20.0)

    def test_short_profits_when_price_falls(self) -> None:
        signal = make_consensus(Direction.BEARISH)
        self.sim.open_position(signal, 10, 100.0, self.day, 10, stop=105.0, target=90.0, horizon_days=5)
        bar = replace(self.bar, open=100.0, high=101.0, low=89.0, close=92.0)
        closed = self.sim.process_bar(self.day, {"AAA": bar}, session=10)
        self.assertEqual(closed[0].exit_reason, "target")
        self.assertAlmostEqual(closed[0].pnl, 100.0)

    def test_mark_to_market_keeps_equity_flat_without_moves(self) -> None:
        signal = make_consensus(Direction.BULLISH)
        self.sim.open_position(signal, 10, 100.0, self.day, 10, stop=95.0, target=110.0, horizon_days=5)
        equity = self.sim.mark(self.day, {"AAA": 100.0})
        self.assertAlmostEqual(equity, 100_000.0)
        self.assertEqual(len(self.sim.equity_curve), 1)


    def test_fractional_position_size(self) -> None:
        signal = make_consensus(Direction.BULLISH)
        self.sim.open_position(signal, 0.5, 100.0, self.day, 10, stop=90.0, target=120.0, horizon_days=1)
        bar = replace(self.bar, open=100.0, high=111.0, low=99.0, close=110.0)
        closed = self.sim.process_bar(self.day, {"AAA": bar}, session=10)
        self.assertEqual(closed[0].exit_reason, "horizon")
        self.assertAlmostEqual(closed[0].pnl, 5.0)
        self.assertAlmostEqual(closed[0].return_pct, 0.1)


if __name__ == "__main__":
    unittest.main()

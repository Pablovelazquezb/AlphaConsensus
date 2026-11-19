import unittest

from alphaconsensus.backtest.runner import run_demo
from alphaconsensus.config import load_settings


class DemoRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        cls.result = run_demo(cls.settings, seed=11, persist=False)

    def test_live_period_has_one_equity_point_per_session(self) -> None:
        self.assertEqual(
            len(self.result.outcome.equity_curve), self.settings.backtest.live_days
        )

    def test_pipeline_produces_signals_and_scores(self) -> None:
        self.assertGreater(self.result.stats["actionable_signals"], 0)
        self.assertTrue(self.result.scores)
        self.assertGreater(self.result.stats["accounts_active"], 0)

    def test_consensus_fires_and_some_trade_executes(self) -> None:
        self.assertGreaterEqual(self.result.stats["consensus_signals"], 1)
        self.assertGreater(self.result.stats["trades"], 0)
        self.assertTrue(all(t.exit_time is not None for t in self.result.trades))

    def test_ablation_uses_equal_weights(self) -> None:
        self.assertGreaterEqual(
            self.result.benchmark.stats["consensus_signals"],
            self.result.stats["consensus_signals"],
        )

    def test_stats_are_coherent(self) -> None:
        stats = self.result.stats
        self.assertLessEqual(stats["win_rate"], 1.0)
        self.assertGreaterEqual(stats["max_drawdown"], -1.0)
        self.assertAlmostEqual(
            stats["final_equity"] / stats["starting_equity"] - 1.0,
            stats["total_return"],
            places=6,
        )


if __name__ == "__main__":
    unittest.main()

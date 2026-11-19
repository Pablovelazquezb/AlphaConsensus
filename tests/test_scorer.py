import unittest
from datetime import datetime, time, timezone

from alphaconsensus.credibility.prices import SyntheticMarket
from alphaconsensus.credibility.scorer import CredibilityScorer, ScorerConfig
from alphaconsensus.models import Direction, TradingSignal


def make_signal(author: str, index: int, day, direction: Direction, ticker: str = "AAA") -> TradingSignal:
    return TradingSignal(
        tweet_id=f"{author}-{index}",
        author=author,
        ticker=ticker,
        direction=direction,
        horizon_days=5,
        confidence=0.8,
        created_at=datetime.combine(day, time(15, 0), tzinfo=timezone.utc),
    )


class CredibilityScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.market = SyntheticMarket.generate(["AAA", "BBB"], days=90, seed=3)
        days = self.market.trading_days[20:70:2]
        self.good = []
        self.bad = []
        self.noise = []
        for i, day in enumerate(days):
            result = self.market.forward_excess("AAA", day, 5)
            if result is None:
                continue
            _, _, excess = result
            good_direction = Direction.BULLISH if excess > 0 else Direction.BEARISH
            self.good.append(make_signal("good", i, day, good_direction))
            self.bad.append(make_signal("bad", i, day, good_direction.opposite))
            noisy = Direction.BULLISH if i % 2 == 0 else Direction.BEARISH
            self.noise.append(make_signal("noise", i, day, noisy))

    def test_good_account_gets_weight_and_bad_gets_none(self) -> None:
        scores = CredibilityScorer(ScorerConfig(min_calls=10)).score(
            self.good + self.bad + self.noise, self.market
        )
        self.assertGreater(scores["good"].weight, 0.2)
        self.assertEqual(scores["bad"].weight, 0.0)
        self.assertGreater(scores["good"].weight, scores["noise"].weight)
        self.assertGreater(scores["good"].hit_rate, 0.9)

    def test_calls_outside_the_price_history_are_skipped(self) -> None:
        late_day = self.market.trading_days[-1]
        late = make_signal("late", 0, late_day, Direction.BULLISH)
        scores = CredibilityScorer(ScorerConfig(min_calls=1)).score([late], self.market)
        self.assertNotIn("late", scores)

    def test_shrinkage_punishes_small_samples(self) -> None:
        config = ScorerConfig(min_calls=20, provisional_discount=0.25)
        small = self.good[:5]
        scores = CredibilityScorer(config).score(small, self.market)
        self.assertTrue(scores["good"].provisional)
        self.assertLess(scores["good"].weight, 0.3)


if __name__ == "__main__":
    unittest.main()

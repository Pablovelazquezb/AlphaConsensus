import unittest
from datetime import datetime, timedelta, timezone

from alphaconsensus.config import ConsensusConfig
from alphaconsensus.consensus.engine import ConsensusEngine
from alphaconsensus.models import Direction, TradingSignal

BASE = datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc)


def signal(author: str, direction: Direction, minutes: int = 0, ticker: str = "NVDA", confidence: float = 0.8) -> TradingSignal:
    return TradingSignal(
        tweet_id=f"{author}-{minutes}",
        author=author,
        ticker=ticker,
        direction=direction,
        horizon_days=5,
        confidence=confidence,
        created_at=BASE + timedelta(minutes=minutes),
    )


class ConsensusEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ConsensusConfig(
            window_minutes=120,
            min_accounts=3,
            min_weight=1.0,
            min_agreement=0.7,
            cooldown_minutes=120,
            default_author_weight=0.5,
        )
        self.weights = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5}
        self.engine = ConsensusEngine(self.config, self.weights)

    def feed(self, *signals: TradingSignal):
        results = [self.engine.ingest(s) for s in signals]
        return [r for r in results if r is not None]

    def test_three_accounts_reach_quorum(self) -> None:
        fired = self.feed(
            signal("a", Direction.BULLISH, 0),
            signal("b", Direction.BULLISH, 10),
            signal("c", Direction.BULLISH, 20),
        )
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].n_accounts, 3)
        self.assertEqual(fired[0].score, 1.5)

    def test_two_accounts_do_not(self) -> None:
        fired = self.feed(
            signal("a", Direction.BULLISH, 0),
            signal("b", Direction.BULLISH, 10),
        )
        self.assertEqual(fired, [])

    def test_split_vote_blocks_signal(self) -> None:
        fired = self.feed(
            signal("a", Direction.BULLISH, 0),
            signal("b", Direction.BULLISH, 5),
            signal("c", Direction.BEARISH, 10),
        )
        self.assertEqual(fired, [])

    def test_one_vote_per_author(self) -> None:
        fired = self.feed(
            signal("a", Direction.BULLISH, 0),
            signal("a", Direction.BULLISH, 5),
            signal("b", Direction.BULLISH, 10),
        )
        self.assertEqual(fired, [])

    def test_cooldown_prevents_immediate_refire(self) -> None:
        fired = self.feed(
            signal("a", Direction.BULLISH, 0),
            signal("b", Direction.BULLISH, 10),
            signal("c", Direction.BULLISH, 20),
        )
        self.assertEqual(len(fired), 1)
        again = self.feed(
            signal("a", Direction.BULLISH, 30, confidence=0.9),
            signal("b", Direction.BULLISH, 40, confidence=0.9),
            signal("c", Direction.BULLISH, 50, confidence=0.9),
        )
        self.assertEqual(again, [])

    def test_stale_signals_leave_the_window(self) -> None:
        self.feed(signal("a", Direction.BULLISH, 0))
        fired = self.feed(
            signal("b", Direction.BULLISH, 125),
            signal("c", Direction.BULLISH, 130),
        )
        self.assertEqual(fired, [])

    def test_zero_weight_account_is_ignored(self) -> None:
        engine = ConsensusEngine(self.config, {**self.weights, "c": 0.0})
        fired = [
            result
            for result in (
                engine.ingest(signal("a", Direction.BULLISH, 0)),
                engine.ingest(signal("b", Direction.BULLISH, 10)),
                engine.ingest(signal("c", Direction.BULLISH, 20)),
            )
            if result is not None
        ]
        self.assertEqual(fired, [])

    def test_horizon_is_median_of_voters(self) -> None:
        first = signal("a", Direction.BULLISH, 0)
        second = signal("b", Direction.BULLISH, 10)
        third = signal("c", Direction.BULLISH, 20)
        third = TradingSignal(
            tweet_id="c-20", author="c", ticker="NVDA", direction=Direction.BULLISH,
            horizon_days=21, confidence=0.8, created_at=third.created_at,
        )
        fired = self.feed(first, second, third)
        self.assertEqual(fired[0].horizon_days, 5)


if __name__ == "__main__":
    unittest.main()

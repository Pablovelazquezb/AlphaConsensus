import unittest
from datetime import datetime, timezone

from alphaconsensus.config import NLPConfig
from alphaconsensus.models import Direction, Tweet
from alphaconsensus.nlp.rules import RulesParser

UNIVERSE = {"NVDA", "AAPL", "MSFT", "TSLA", "AMD"}


def tweet(text: str) -> Tweet:
    return Tweet(
        id="t1",
        author="demo_semis",
        text=text,
        created_at=datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc),
    )


class RulesParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = RulesParser(UNIVERSE, config=NLPConfig(min_confidence=0.5))

    def test_bullish_call(self) -> None:
        signals = self.parser.parse(
            tweet("Added to $NVDA here. Breakout above 120 on volume, targeting 145. Strong setup.")
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].ticker, "NVDA")
        self.assertIs(signals[0].direction, Direction.BULLISH)
        self.assertTrue(signals[0].actionable)
        self.assertGreaterEqual(signals[0].confidence, 0.6)

    def test_bearish_call(self) -> None:
        signals = self.parser.parse(
            tweet("Shorting $TSLA into earnings. Guidance looks weak, target 180. Overvalued.")
        )
        self.assertEqual(len(signals), 1)
        self.assertIs(signals[0].direction, Direction.BEARISH)

    def test_multiple_tickers_share_direction(self) -> None:
        signals = self.parser.parse(tweet("Long $AAPL and $MSFT into earnings. Bullish."))
        self.assertEqual({s.ticker for s in signals}, {"AAPL", "MSFT"})
        self.assertTrue(all(s.direction is Direction.BULLISH for s in signals))

    def test_negation_kills_the_signal(self) -> None:
        self.assertEqual(self.parser.parse(tweet("I am not bullish on $AAPL at all")), [])

    def test_no_ticker_no_signal(self) -> None:
        self.assertEqual(self.parser.parse(tweet("Markets are wild today, huge moves everywhere")), [])

    def test_no_direction_no_signal(self) -> None:
        self.assertEqual(self.parser.parse(tweet("Watching $AAPL closely today, no position")), [])

    def test_intraday_horizon(self) -> None:
        signals = self.parser.parse(tweet("Day trade $NVDA calls, breakout above 120 today"))
        self.assertEqual(signals[0].horizon_days, 1)

    def test_confidence_is_bounded(self) -> None:
        signals = self.parser.parse(
            tweet(
                "Buying $NVDA aggressively, breakout, gap up, all time high, "
                "strong upside, price target 200, calls, risk on, moon"
            )
        )
        self.assertLessEqual(signals[0].confidence, 0.95)


if __name__ == "__main__":
    unittest.main()

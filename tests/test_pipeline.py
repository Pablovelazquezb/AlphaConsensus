import unittest
from datetime import datetime, timezone

from alphaconsensus.config import FilterConfig
from alphaconsensus.ingestion.pipeline import TweetFilter
from alphaconsensus.models import Tweet


def tweet(text: str, **kwargs) -> Tweet:
    return Tweet(
        id=kwargs.pop("id", "t1"),
        author="demo_semis",
        text=text,
        created_at=datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc),
        **kwargs,
    )


class TweetFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filter = TweetFilter(FilterConfig())

    def test_accepts_a_real_call(self) -> None:
        ok, reason = self.filter.classify(
            tweet("Added to $NVDA here. Breakout above 120 on volume.")
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_rejects_retweets(self) -> None:
        ok, reason = self.filter.classify(tweet("RT @someone: $NVDA to the moon, buy now"))
        self.assertFalse(ok)
        self.assertEqual(reason, "retweet")

    def test_rejects_replies(self) -> None:
        ok, reason = self.filter.classify(tweet("@friend check $AAPL before the close"))
        self.assertFalse(ok)
        self.assertEqual(reason, "reply")

    def test_rejects_promos(self) -> None:
        ok, reason = self.filter.classify(
            tweet("Join my telegram for $TSLA signals t.me/notarealchannel")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "promo")

    def test_rejects_too_short(self) -> None:
        ok, reason = self.filter.classify(tweet("buy $AAPL"))
        self.assertFalse(ok)
        self.assertEqual(reason, "too_short")

    def test_deduplicates_by_id(self) -> None:
        items = [
            tweet("Added to $NVDA here. Breakout above 120 on volume.", id="same"),
            tweet("Added to $NVDA here. Breakout above 120 on volume.", id="same"),
        ]
        accepted = self.filter.apply(items)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(self.filter.stats["duplicate"], 1)


if __name__ == "__main__":
    unittest.main()

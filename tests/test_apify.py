import unittest
from datetime import datetime, timezone

from alphaconsensus.ingestion.apify import ApifySource

SAMPLE_ITEM = {
    "id": "123",
    "text": "Added to $NVDA here. Breakout above 120, targeting 145.",
    "createdAt": "2026-01-02T15:30:00Z",
    "author": {"userName": "demo_semis"},
    "url": "https://x.com/demo_semis/status/123",
    "lang": "en",
    "isRetweet": False,
    "isReply": False,
}


class FakeApify(ApifySource):
    def __init__(self):
        super().__init__(token="test-token")
        self.payloads = []

    def _run_actor(self, payload):
        self.payloads.append(payload)
        return [SAMPLE_ITEM]


class ApifyProfileTests(unittest.TestCase):
    def test_timeline_payload_uses_start_urls(self) -> None:
        source = FakeApify()
        tweets = source.fetch_profiles(["@Demo_Semis"], limit_per_account=50)
        self.assertEqual(len(tweets), 1)
        payload = source.payloads[0]
        self.assertEqual(payload["startUrls"], [{"url": "https://x.com/demo_semis"}])
        self.assertEqual(payload["maxItems"], 50)
        self.assertEqual(payload["sort"], "Latest")

    def test_normalizes_author_and_date(self) -> None:
        source = FakeApify()
        tweet = source.fetch_profiles(["demo_semis"], limit_per_account=1)[0]
        self.assertEqual(tweet.author, "demo_semis")
        self.assertEqual(tweet.created_at, datetime(2026, 1, 2, 15, 30, tzinfo=timezone.utc))
        self.assertIn("NVDA", tweet.text)

    def test_extra_input_can_override_payload(self) -> None:
        source = ApifySource(token="t", extra_input={"tweetLanguage": "en"})
        payload = {"startUrls": [{"url": "https://x.com/a"}], "maxItems": 10}
        payload.update(source.extra_input)
        self.assertEqual(payload["tweetLanguage"], "en")


if __name__ == "__main__":
    unittest.main()

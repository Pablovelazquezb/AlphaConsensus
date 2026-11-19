import unittest
from datetime import date

from alphaconsensus.ingestion.congress import CongressSource, CongressTrade

SAMPLE = {
    "member": "Nancy Pelosi",
    "member_slug": "nancy-pelosi",
    "chamber": "house",
    "state": "CA11",
    "ticker": "NVDA",
    "asset": "NVIDIA Corporation - Common Stock",
    "type": "purchase",
    "amount_low": 500001,
    "amount_high": 1000000,
    "amount_range": "$500,001 - $1,000,000",
    "transaction_date": "2026-05-29",
    "disclosure_date": "2026-06-20",
    "est_price": 180.0,
    "recent_price": 210.0,
    "perf_pct": 16.6,
    "outcome": "gain",
}


class CongressTradeTests(unittest.TestCase):
    def test_lag_and_direction(self) -> None:
        trade = CongressTrade.from_api(SAMPLE)
        self.assertEqual(trade.lag_days, 22)
        self.assertEqual(trade.direction.value, "bullish")

    def test_large_purchase_has_high_confidence(self) -> None:
        trade = CongressTrade.from_api(SAMPLE)
        self.assertGreaterEqual(trade.confidence, 0.8)

    def test_signal_is_stamped_at_disclosure_date(self) -> None:
        signal = CongressTrade.from_api(SAMPLE).to_signal()
        self.assertIsNotNone(signal)
        self.assertEqual(signal.created_at.date(), date(2026, 6, 20))
        self.assertEqual(signal.author, "congress:nancy-pelosi")
        self.assertEqual(signal.parser, "congress")

    def test_exchange_has_no_direction(self) -> None:
        trade = CongressTrade.from_api({**SAMPLE, "type": "exchange"})
        self.assertIsNone(trade.to_signal())

    def test_small_trade_is_not_actionable(self) -> None:
        trade = CongressTrade.from_api(
            {**SAMPLE, "amount_low": 201, "amount_high": 1000, "amount_range": "$201 - $1,000"}
        )
        signal = trade.to_signal()
        self.assertIsNotNone(signal)
        self.assertFalse(signal.actionable)


class FakeSource(CongressSource):
    def __init__(self, pages):
        super().__init__(api_key="test", page_size=2)
        self.pages = pages
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, params))
        return {"trades": self.pages[len(self.calls) - 1]}


class PaginationTests(unittest.TestCase):
    def test_pagination_stops_at_limit(self) -> None:
        source = FakeSource([[SAMPLE, SAMPLE], [SAMPLE]])
        trades = source.trades(limit=3)
        self.assertEqual(len(trades), 3)
        self.assertEqual(len(source.calls), 2)
        self.assertEqual(source.calls[1][1]["page"], 1)

    def test_single_page_does_not_request_more(self) -> None:
        source = FakeSource([[SAMPLE]])
        trades = source.trades(limit=100)
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(source.calls), 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, timedelta

from alphaconsensus.credibility.congress_scorer import (
    CongressCredibilityScorer,
    CongressScorerConfig,
)
from alphaconsensus.credibility.prices import Bar, PriceSeries
from alphaconsensus.ingestion.congress import CongressTrade


def business_days(start: date, count: int):
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def series(ticker: str, start_price: float, end_price: float, days=180) -> PriceSeries:
    calendar = business_days(date(2025, 1, 2), days)
    step = (end_price - start_price) / (days - 1)
    bars = []
    for i, day in enumerate(calendar):
        price = start_price + step * i
        bars.append(Bar(day, price, price * 1.01, price * 0.99, price, 1_000_000))
    return PriceSeries(ticker, bars)


def trade(member: str, ticker: str, kind: str, txn: date, amount=100_000) -> CongressTrade:
    return CongressTrade(
        member=member, member_slug=member.lower().replace(" ", "-"),
        chamber="house", state="CA11", ticker=ticker, asset="",
        type=kind, amount_low=amount, amount_high=amount,
        amount_range=f"${amount:,}", transaction_date=txn,
        disclosure_date=txn + timedelta(days=20),
        est_price=None, recent_price=None, perf_pct=None, outcome="",
    )


def batch(member: str, ticker: str, kind: str, count: int, start=date(2025, 2, 3)):
    return [
        trade(member, ticker, kind, start + timedelta(days=7 * i))
        for i in range(count)
    ]


class CongressScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prices = {
            "SPY": series("SPY", 100, 100),
            "AAA": series("AAA", 100, 160),
            "BBB": series("BBB", 100, 50),
            "CCC": series("CCC", 100, 140),
        }
        self.scorer = CongressCredibilityScorer(
            CongressScorerConfig(min_trades=10, horizon_days=21)
        )

    def test_diversified_winner_is_significant(self) -> None:
        trades = batch("Good Member", "AAA", "purchase", 10) + batch(
            "Good Member", "CCC", "purchase", 10
        )
        score = self.scorer.score(trades, self.prices)["good-member"]
        self.assertGreater(score.n_trades, 14)
        self.assertTrue(score.significant)
        self.assertGreater(score.weight, 0.5)
        self.assertFalse(score.provisional)

    def test_buying_a_loser_gets_zero_weight(self) -> None:
        trades = batch("Bad Member", "BBB", "purchase", 20)
        score = self.scorer.score(trades, self.prices)["bad-member"]
        self.assertEqual(score.weight, 0.0)

    def test_shorting_a_loser_scores(self) -> None:
        trades = batch("Short Seller", "BBB", "sale", 20)
        score = self.scorer.score(trades, self.prices)["short-seller"]
        self.assertGreater(score.weight, 0.3)

    def test_small_sample_is_provisional_and_discounted(self) -> None:
        trades = batch("New Member", "AAA", "purchase", 5)
        score = self.scorer.score(trades, self.prices)["new-member"]
        self.assertTrue(score.provisional)
        self.assertFalse(score.significant)
        self.assertLess(score.weight, 0.5)

    def test_transaction_clock_has_more_edge_than_disclosure_clock(self) -> None:
        trades = batch("Good Member", "AAA", "purchase", 10) + batch(
            "Good Member", "CCC", "purchase", 10
        )
        score = self.scorer.score(trades, self.prices)["good-member"]
        self.assertGreater(score.mean_excess_txn, score.mean_excess_disc)
        self.assertGreater(score.decay, 0)


if __name__ == "__main__":
    unittest.main()

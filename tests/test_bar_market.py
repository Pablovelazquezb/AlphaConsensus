import unittest
from datetime import date, timedelta

from alphaconsensus.credibility.prices import Bar, BarMarket, PriceSeries


def business_days(start: date, count: int):
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def series(ticker: str, start_price: float, end_price: float, days=60) -> PriceSeries:
    calendar = business_days(date(2025, 1, 2), days)
    step = (end_price - start_price) / (days - 1)
    return PriceSeries(
        ticker,
        [
            Bar(day, start_price + step * i, start_price + step * i + 1,
                start_price + step * i - 1, start_price + step * i, 1_000_000)
            for i, day in enumerate(calendar)
        ],
    )


class BarMarketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.market = BarMarket({"SPY": series("SPY", 100, 100), "AAA": series("AAA", 100, 130)})

    def test_positive_excess_for_a_rising_stock(self) -> None:
        result = self.market.forward_excess("AAA", date(2025, 1, 10), 5)
        self.assertIsNotNone(result)
        ret, spy_ret, excess = result
        self.assertGreater(ret, 0)
        self.assertAlmostEqual(spy_ret, 0.0, places=6)
        self.assertGreater(excess, 0)

    def test_unknown_ticker_returns_none(self) -> None:
        self.assertIsNone(self.market.forward_excess("ZZZ", date(2025, 1, 10), 5))

    def test_window_beyond_data_returns_none(self) -> None:
        self.assertIsNone(self.market.forward_excess("AAA", date(2025, 6, 1), 5))

    def test_benchmark_must_exist(self) -> None:
        market = BarMarket({"AAA": series("AAA", 100, 130)}, benchmark="QQQ")
        self.assertIsNone(market.forward_excess("AAA", date(2025, 1, 10), 5))


if __name__ == "__main__":
    unittest.main()

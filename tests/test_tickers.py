import unittest

from alphaconsensus.nlp.tickers import TickerExtractor


class TickerExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = TickerExtractor(
            universe={"NVDA", "AAPL", "MSFT", "AMD"}, blacklist={"CEO", "USD"}
        )

    def test_cashtag_is_extracted(self) -> None:
        self.assertEqual(self.extractor.extract("Long $NVDA here"), ["NVDA"])

    def test_bare_symbol_only_counts_if_in_universe(self) -> None:
        self.assertEqual(self.extractor.extract("NVDA looks strong"), ["NVDA"])
        self.assertEqual(self.extractor.extract("AI and EV are hype"), [])

    def test_blacklisted_acronyms_are_ignored(self) -> None:
        self.assertEqual(self.extractor.extract("$CEO sold $USD"), [])

    def test_urls_are_stripped(self) -> None:
        self.assertEqual(self.extractor.extract("see https://x.com/user/NVDA"), [])

    def test_duplicates_are_removed(self) -> None:
        self.assertEqual(self.extractor.extract("Buy $NVDA, NVDA is cheap"), ["NVDA"])

    def test_max_tickers_is_respected(self) -> None:
        extractor = TickerExtractor({"AAPL", "MSFT", "AMD"}, max_tickers=2)
        self.assertEqual(extractor.extract("$AAPL $MSFT $AMD"), ["AAPL", "MSFT"])

    def test_is_cashtag(self) -> None:
        self.assertTrue(self.extractor.is_cashtag("buy $nvda", "NVDA"))
        self.assertFalse(self.extractor.is_cashtag("buy NVDA", "NVDA"))


if __name__ == "__main__":
    unittest.main()

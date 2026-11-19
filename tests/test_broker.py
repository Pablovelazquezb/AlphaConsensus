import os
import unittest
from unittest.mock import patch

from alphaconsensus.execution.alpaca import AlpacaPaperBroker


class AlpacaBrokerConfigTests(unittest.TestCase):
    def test_without_credentials_is_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            broker = AlpacaPaperBroker(api_key="", secret_key="")
            self.assertFalse(broker.available)

    def test_defaults_to_paper_endpoint(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            broker = AlpacaPaperBroker(api_key="k", secret_key="s")
            self.assertIn("paper-api", broker.base_url)
            self.assertTrue(broker.available)

    def test_custom_endpoint_is_respected(self) -> None:
        broker = AlpacaPaperBroker(
            api_key="k", secret_key="s", base_url="https://paper-api.alpaca.markets/v2/"
        )
        self.assertEqual(broker.base_url, "https://paper-api.alpaca.markets/v2")


if __name__ == "__main__":
    unittest.main()

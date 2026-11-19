import unittest
from datetime import date

from alphaconsensus.ingestion.house_clerk import Filing, HouseClerkSource, _matches_member

SAMPLE_TEXT = """
                                                                  Filing ID #20035780
Name:                 Hon. Test Member
State/District: CA11

ID         Owner Asset                                            Transaction Date                 Notification Amount                 Cap.
                                                                  Type                             Date                                Gains >
                                                                                                                                       $200?

           SP          Tesla, Inc. - Common Stock               S                 01/15/2025 02/06/2025     $15,001 -
                       (TSLA) [ST]                                                                         $50,000
                       F      S     : New
                       D           : sold

           JT          Apple Inc. - Common Stock (AAPL)         P                 01/10/2025 01/12/2025     $1,001 - $15,000
                       [ST]

           SP          Some Option (XYZ) [OP]                   P                 01/11/2025 01/12/2025     $1,001 - $15,000
                       D           : Put option
"""


def filing() -> Filing:
    return Filing(
        member="Nancy Pelosi", first="Nancy", last="Pelosi",
        state="CA11", year=2025, doc_id="123", filing_date=date(2025, 2, 6),
    )


class PtrParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = HouseClerkSource()

    def test_parses_wrapped_amount_and_ticker(self) -> None:
        trades = self.source.parse_ptr(SAMPLE_TEXT, filing())
        self.assertEqual(len(trades), 2)
        tesla = trades[0]
        self.assertEqual(tesla.ticker, "TSLA")
        self.assertEqual(tesla.type, "sale")
        self.assertEqual(tesla.amount_low, 15001)
        self.assertEqual(tesla.amount_high, 50000)
        self.assertEqual(tesla.transaction_date, date(2025, 1, 15))
        self.assertEqual(tesla.disclosure_date, date(2025, 2, 6))
        self.assertEqual(tesla.lag_days, 22)

    def test_removes_owner_prefix(self) -> None:
        trades = self.source.parse_ptr(SAMPLE_TEXT, filing())
        self.assertFalse(trades[0].asset.startswith("SP"))
        self.assertTrue(trades[0].asset.startswith("Tesla"))

    def test_skips_options(self) -> None:
        trades = self.source.parse_ptr(SAMPLE_TEXT, filing())
        self.assertNotIn("XYZ", {t.ticker for t in trades})

    def test_no_rows_for_scanned_text(self) -> None:
        self.assertEqual(self.source.parse_ptr("", filing()), [])


class MemberMatchingTests(unittest.TestCase):
    def test_middle_initials_do_not_break_matching(self) -> None:
        self.assertTrue(_matches_member("David J. Taylor", ["David Taylor"]))
        self.assertTrue(_matches_member("Thomas H. Kean", ["Thomas Kean"]))
        self.assertTrue(_matches_member("Michael T. McCaul", ["Michael McCaul"]))
        self.assertFalse(_matches_member("Nancy Pelosi", ["Kevin Hern"]))


if __name__ == "__main__":
    unittest.main()

"""Ticker extraction with two guardrails against false positives.

1. Cashtags (``$NVDA``) are trusted if they look like a symbol and are not in
   a blacklist of acronyms that look like tickers (``$CEO``, ``$USD``...).
2. Bare uppercase tokens (``NVDA``) only count if the symbol exists in the
   curated universe, because ``AI``, ``EV`` or ``DD`` in a tweet are noise.

URLs are stripped first: ``https://x.com/.../NVDA`` must not become a signal.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Set

URL_RE = re.compile(r"https?://\S+")
CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})(?![A-Za-z0-9])")
BARE_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Never valid tickers in this context, even as cashtags.
EXTRA_STOPWORDS = {
    "RT", "CC", "DM", "LOL", "WTF", "OMG", "FOMO", "YOLO", "HODL", "TBH",
    "IMO", "IMHO", "NFA", "DYOR", "DD", "OP", "EOD", "EOW", "YTD", "MTD",
    "QTD", "TBD", "AKA", "FYI", "BTW", "FUD", "KYC", "SEC", "FED", "CPI",
    "PPI", "NFP", "FOMC", "PCE", "GDP", "EPS", "PE", "PS", "EV", "AI",
}


class TickerExtractor:
    def __init__(
        self,
        universe: Iterable[str],
        blacklist: Iterable[str] = (),
        max_tickers: int = 3,
    ) -> None:
        self.universe: Set[str] = {t.upper() for t in universe}
        self.blacklist: Set[str] = {t.upper() for t in blacklist} | EXTRA_STOPWORDS
        self.max_tickers = max_tickers

    def extract(self, text: str) -> List[str]:
        clean = URL_RE.sub(" ", text)
        found: List[str] = []
        seen: Set[str] = set()

        def add(ticker: str) -> None:
            ticker = ticker.upper()
            if ticker in seen or ticker in self.blacklist:
                return
            if len(found) >= self.max_tickers:
                return
            seen.add(ticker)
            found.append(ticker)

        for match in CASHTAG_RE.finditer(clean):
            add(match.group(1))

        for match in BARE_RE.finditer(clean):
            symbol = match.group(1)
            if symbol in self.universe:
                add(symbol)

        return found

    def is_cashtag(self, text: str, ticker: str) -> bool:
        return bool(re.search(rf"\${re.escape(ticker)}\b", text, re.IGNORECASE))

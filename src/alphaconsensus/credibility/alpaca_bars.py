"""Alpaca market-data client for historical daily bars.

Uses the same paper credentials as the broker. The free IEX feed is enough for
liquid US equities and ETFs; coverage for thin names is incomplete, so callers
must tolerate missing symbols. No third-party SDK required.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .prices import Bar, PriceSeries

BASE = "https://data.alpaca.markets/v2/stocks/bars"


class AlpacaBarsError(RuntimeError):
    pass


def _chunks(values: Sequence[str], size: int = 100) -> Iterable[Sequence[str]]:
    for i in range(0, len(values), size):
        yield values[i: i + size]


class AlpacaBars:
    name = "alpaca_bars"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: str = "iex",
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self.feed = feed
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.available:
            raise AlpacaBarsError("Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY")
        url = f"{BASE}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise AlpacaBarsError(f"Alpaca data HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AlpacaBarsError(f"No se pudo conectar a Alpaca data: {exc.reason}") from exc

    def fetch(
        self,
        tickers: Sequence[str],
        start: date,
        end: date,
    ) -> Dict[str, PriceSeries]:
        symbols = sorted({t.upper() for t in tickers if t})
        collected: Dict[str, List[Bar]] = {}
        for chunk in _chunks(symbols, 100):
            page_token: Optional[str] = None
            while True:
                params: Dict[str, Any] = {
                    "symbols": ",".join(chunk),
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "limit": 10000,
                    "adjustment": "all",
                    "feed": self.feed,
                }
                if page_token:
                    params["page_token"] = page_token
                payload = self._get(params)
                for symbol, rows in (payload.get("bars") or {}).items():
                    bucket = collected.setdefault(symbol, [])
                    for row in rows:
                        stamp = str(row.get("t", ""))
                        try:
                            day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
                        except ValueError:
                            continue
                        bucket.append(
                            Bar(
                                date=day,
                                open=float(row["o"]),
                                high=float(row["h"]),
                                low=float(row["l"]),
                                close=float(row["c"]),
                                volume=float(row.get("v") or 0),
                            )
                        )
                page_token = payload.get("next_page_token")
                if not page_token:
                    break

        series: Dict[str, PriceSeries] = {}
        for symbol, bars in collected.items():
            if len(bars) < 5:
                continue
            bars.sort(key=lambda b: b.date)
            series[symbol] = PriceSeries(symbol, bars)
        return series

"""Congressional trading disclosures (STOCK Act) as a signal source.

Why a separate source instead of an X whitelist? Members of Congress do not
tweet "buying $NVDA"; they file Periodic Transaction Reports within ~45 days.
The alpha, if any, lives in the *disclosure*, not in a tweet. This adapter
normalises Bargo's free API (House + Senate, last ~3 months, per-trade
performance) into the same ``TradingSignal`` shape used by the rest of the
pipeline, stamped at the **disclosure date** — the first moment a retail
trader could act.

Caveats baked into the design:
  * transaction amounts are ranges, not exact sizes;
  * the free tier is a rolling ~3-month window (paid providers go back years);
  * a signal is only tradable from ``disclosure_date``, so the lag is part of
    the model, not an afterthought.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..models import Direction, TradingSignal

BASE_URL = "https://www.bargo.ai/free-apis/congress/v1"


class CongressError(RuntimeError):
    pass


def _as_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CongressTrade:
    member: str
    member_slug: str
    chamber: str
    state: str
    ticker: str
    asset: str
    type: str  # purchase | sale | exchange
    amount_low: Optional[float]
    amount_high: Optional[float]
    amount_range: str
    transaction_date: Optional[date]
    disclosure_date: Optional[date]
    est_price: Optional[float]
    recent_price: Optional[float]
    perf_pct: Optional[float]
    outcome: str

    @classmethod
    def from_api(cls, item: Dict[str, Any]) -> "CongressTrade":
        return cls(
            member=str(item.get("member") or ""),
            member_slug=str(item.get("member_slug") or ""),
            chamber=str(item.get("chamber") or ""),
            state=str(item.get("state") or ""),
            ticker=str(item.get("ticker") or "").upper(),
            asset=str(item.get("asset") or ""),
            type=str(item.get("type") or ""),
            amount_low=_as_float(item.get("amount_low")),
            amount_high=_as_float(item.get("amount_high")),
            amount_range=str(item.get("amount_range") or ""),
            transaction_date=_as_date(item.get("transaction_date")),
            disclosure_date=_as_date(item.get("disclosure_date")),
            est_price=_as_float(item.get("est_price")),
            recent_price=_as_float(item.get("recent_price")),
            perf_pct=_as_float(item.get("perf_pct")),
            outcome=str(item.get("outcome") or ""),
        )

    @classmethod
    def from_dict(cls, item: Dict[str, Any]) -> "CongressTrade":
        return cls(
            member=str(item.get("member") or ""),
            member_slug=str(item.get("member_slug") or ""),
            chamber=str(item.get("chamber") or ""),
            state=str(item.get("state") or ""),
            ticker=str(item.get("ticker") or "").upper(),
            asset=str(item.get("asset") or ""),
            type=str(item.get("type") or ""),
            amount_low=_as_float(item.get("amount_low")),
            amount_high=_as_float(item.get("amount_high")),
            amount_range=str(item.get("amount_range") or ""),
            transaction_date=_as_date(item.get("transaction_date")),
            disclosure_date=_as_date(item.get("disclosure_date")),
            est_price=_as_float(item.get("est_price")),
            recent_price=_as_float(item.get("recent_price")),
            perf_pct=_as_float(item.get("perf_pct")),
            outcome=str(item.get("outcome") or ""),
        )

    @property
    def lag_days(self) -> Optional[int]:
        if self.transaction_date is None or self.disclosure_date is None:
            return None
        return (self.disclosure_date - self.transaction_date).days

    @property
    def direction(self) -> Direction:
        if self.type == "purchase":
            return Direction.BULLISH
        if self.type == "sale":
            return Direction.BEARISH
        return Direction.NEUTRAL

    @property
    def confidence(self) -> float:
        """A crude conviction proxy: size bucket, penalised by disclosure lag."""
        high = self.amount_high or 0.0
        if high >= 1_000_000:
            score = 0.85
        elif high >= 250_000:
            score = 0.78
        elif high >= 50_000:
            score = 0.68
        elif high >= 15_000:
            score = 0.58
        else:
            score = 0.48
        lag = self.lag_days
        if lag is not None and lag > 45:
            score -= 0.05
        return round(max(0.35, min(0.95, score)), 2)

    def to_signal(self, horizon_days: int = 21) -> Optional[TradingSignal]:
        if self.direction is Direction.NEUTRAL or not self.ticker or self.disclosure_date is None:
            return None
        created = datetime.combine(self.disclosure_date, time(21, 0), tzinfo=timezone.utc)
        return TradingSignal(
            tweet_id=f"congress-{self.member_slug}-{self.ticker}-{self.transaction_date}",
            author=f"congress:{self.member_slug}",
            ticker=self.ticker,
            direction=self.direction,
            horizon_days=horizon_days,
            confidence=self.confidence,
            created_at=created,
            actionable=self.confidence >= 0.5,
            rationale=f"{self.type} {self.amount_range} lag={self.lag_days}d",
            parser="congress",
        )


class CongressSource:
    name = "congress"

    def __init__(
        self,
        base_url: str = BASE_URL,
        api_key: Optional[str] = None,
        timeout: int = 30,
        page_size: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("BARGO_API_KEY", "")
        self.timeout = timeout
        self.page_size = max(1, min(page_size, 250))

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        headers = {"User-Agent": "AlphaConsensus/0.1"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise CongressError(f"Bargo HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CongressError(f"No se pudo conectar a Bargo: {exc.reason}") from exc

    def health(self) -> Dict[str, Any]:
        return self._get("/health")

    def members(self, limit: int = 500) -> List[Dict[str, Any]]:
        return list(self._get("/members", {"limit": limit}).get("members", []))

    def member(self, slug: str) -> Dict[str, Any]:
        return self._get(f"/members/{urllib.parse.quote(slug)}")

    def trades(
        self,
        member: Optional[str] = None,
        ticker: Optional[str] = None,
        chamber: Optional[str] = None,
        trade_type: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
        limit: int = 100,
        max_pages: int = 3,
    ) -> List[CongressTrade]:
        collected: List[CongressTrade] = []
        page = 0
        while page < max_pages:
            payload = self._get(
                "/trades",
                {
                    "member": member,
                    "ticker": ticker,
                    "chamber": chamber,
                    "type": trade_type,
                    "from": since.isoformat() if since else None,
                    "to": until.isoformat() if until else None,
                    "limit": self.page_size,
                    "page": page,
                },
            )
            rows = payload.get("trades", [])
            collected.extend(CongressTrade.from_api(row) for row in rows)
            if len(collected) >= limit or len(rows) < self.page_size:
                break
            page += 1
        return collected[:limit]

"""Core domain models shared by every layer of the pipeline.

The whole system speaks in three nouns:
  * ``Tweet``            — a raw post from a whitelisted account.
  * ``TradingSignal``    — what the NLP layer extracted from one tweet.
  * ``ConsensusSignal``  — what the aggregation engine decided to act on.

Keeping these as plain dataclasses (no ORM, no pydantic) keeps the core
dependency-free, which matters for a pipeline that will later run inside a
scheduler/worker with a minimal footprint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Naive datetimes are assumed to already be UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

    @property
    def sign(self) -> int:
        return {Direction.BULLISH: 1, Direction.BEARISH: -1, Direction.NEUTRAL: 0}[self]

    @property
    def opposite(self) -> "Direction":
        if self is Direction.BULLISH:
            return Direction.BEARISH
        if self is Direction.BEARISH:
            return Direction.BULLISH
        return Direction.NEUTRAL


@dataclass(frozen=True)
class Tweet:
    id: str
    author: str
    text: str
    created_at: datetime
    is_retweet: bool = False
    is_reply: bool = False
    url: str = ""
    lang: str = "en"
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "author", self.author.lstrip("@").lower())

    def to_row(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "text": self.text,
            "is_retweet": int(self.is_retweet),
            "is_reply": int(self.is_reply),
            "url": self.url,
            "lang": self.lang,
        }


@dataclass(frozen=True)
class TradingSignal:
    """One actionable (ticker, direction) pair extracted from one tweet."""

    tweet_id: str
    author: str
    ticker: str
    direction: Direction
    horizon_days: int
    confidence: float
    created_at: datetime
    actionable: bool = True
    rationale: str = ""
    parser: str = "rules"

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "author", self.author.lstrip("@").lower())
        object.__setattr__(self, "ticker", self.ticker.upper())
        object.__setattr__(self, "confidence", float(max(0.0, min(1.0, self.confidence))))

    @property
    def key(self) -> tuple:
        return (self.author, self.ticker, self.direction)

    def to_row(self) -> Dict[str, Any]:
        return {
            "tweet_id": self.tweet_id,
            "author": self.author,
            "ticker": self.ticker,
            "direction": self.direction.value,
            "horizon_days": self.horizon_days,
            "confidence": self.confidence,
            "actionable": int(self.actionable),
            "created_at": self.created_at.isoformat(),
            "rationale": self.rationale,
            "parser": self.parser,
        }


@dataclass(frozen=True)
class ConsensusSignal:
    """Aggregated agreement that cleared the quorum thresholds."""

    ticker: str
    direction: Direction
    score: float
    n_accounts: int
    accounts: List[str]
    window_start: datetime
    window_end: datetime
    created_at: datetime
    avg_confidence: float
    horizon_days: int = 5
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def side(self) -> str:
        return "long" if self.direction is Direction.BULLISH else "short"

    def to_row(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "direction": self.direction.value,
            "score": self.score,
            "n_accounts": self.n_accounts,
            "accounts": ",".join(self.accounts),
            "created_at": self.created_at.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "avg_confidence": self.avg_confidence,
        }


@dataclass(frozen=True)
class AccountScore:
    handle: str
    n_calls: int
    hits: int
    hit_rate: float
    shrunk_hit_rate: float
    mean_excess_return: float
    weight: float
    provisional: bool = False
    computed_at: datetime = field(default_factory=utcnow)

    def to_row(self) -> Dict[str, Any]:
        return {
            "handle": self.handle,
            "n_calls": self.n_calls,
            "hits": self.hits,
            "hit_rate": self.hit_rate,
            "shrunk_hit_rate": self.shrunk_hit_rate,
            "mean_excess_return": self.mean_excess_return,
            "weight": self.weight,
            "provisional": int(self.provisional),
            "computed_at": self.computed_at.isoformat(),
        }


@dataclass
class Trade:
    ticker: str
    side: str  # "long" | "short"
    qty: float
    entry_time: datetime
    entry_price: float
    signal_id: str = ""
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    return_pct: float = 0.0
    exit_reason: str = ""
    stop_price: float = 0.0
    target_price: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    def to_row(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "ticker": self.ticker,
            "side": self.side,
            "qty": self.qty,
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "return_pct": self.return_pct,
            "exit_reason": self.exit_reason,
        }


@dataclass(frozen=True)
class ParsedTweet:
    """Result of the NLP layer for a single tweet (possibly several tickers)."""

    tweet: Tweet
    signals: List[TradingSignal]
    filtered_reason: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.signals)

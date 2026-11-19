"""Noise filtering applied before anything reaches the NLP layer.

Retweets and reply-guys are the cheapest source of false consensus: an account
that RTs 40 bullish posts a day would otherwise look like 40 independent votes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from ..config import FilterConfig
from ..models import Tweet

PROMO_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bt\.me/",
        r"\bjoin (my|our) (discord|telegram|group|channel)",
        r"\bdm me\b",
        r"\blink in bio\b",
        r"\b(course|mentorship|masterclass)\b.*\b(join|enroll|buy)\b",
        r"\bgiveaway\b",
        r"\bsignals? group\b",
        r"\bpaid (discord|community|group)\b",
    )
]

URL_RE = re.compile(r"https?://\S+")


@dataclass
class TweetFilter:
    config: FilterConfig = field(default_factory=FilterConfig)
    stats: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stats = {
            "seen": 0,
            "accepted": 0,
            "retweet": 0,
            "reply": 0,
            "too_short": 0,
            "promo": 0,
            "duplicate": 0,
        }

    def _bump(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def classify(self, tweet: Tweet) -> Tuple[bool, str]:
        """Return (accepted, reason). ``reason`` is '' when accepted."""
        if self.config.exclude_retweets and (
            tweet.is_retweet or tweet.text.lstrip().startswith("RT @")
        ):
            return False, "retweet"
        if self.config.exclude_replies and (
            tweet.is_reply or tweet.text.lstrip().startswith("@")
        ):
            return False, "reply"
        stripped = URL_RE.sub(" ", tweet.text).strip()
        if len(stripped) < self.config.min_tweet_chars:
            return False, "too_short"
        if self.config.exclude_promos and any(p.search(tweet.text) for p in PROMO_PATTERNS):
            return False, "promo"
        return True, ""

    def apply(self, tweets: Sequence[Tweet]) -> List[Tweet]:
        seen_ids = set()
        out: List[Tweet] = []
        for tweet in tweets:
            self._bump("seen")
            if tweet.id in seen_ids:
                self._bump("duplicate")
                continue
            seen_ids.add(tweet.id)
            ok, reason = self.classify(tweet)
            if not ok:
                self._bump(reason)
                continue
            self._bump("accepted")
            out.append(tweet)
        return out


@dataclass
class IngestResult:
    tweets: List[Tweet]
    stats: Dict[str, int]


def ingest(tweets: Sequence[Tweet], config: FilterConfig | None = None) -> IngestResult:
    tweet_filter = TweetFilter(config or FilterConfig())
    accepted = tweet_filter.apply(tweets)
    return IngestResult(tweets=accepted, stats=dict(tweet_filter.stats))

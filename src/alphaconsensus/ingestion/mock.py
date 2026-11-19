"""Deterministic synthetic X feed.

Why synthetic data in a product about real tweets? Because the architecture —
ticker extraction, consensus quorum, credibility weighting, sizing, P&L — must
be validated *before* paying for API access or trusting a strategy. Every
account here has a hidden "skill" parameter; good accounts are more likely to
tweet in the direction that the synthetic price action will reward.

⚠️  This is a harness, not evidence. The good demo accounts are generated with
knowledge of future returns, so demo P&L is optimistic by construction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import AccountConfig
from ..credibility.prices import SyntheticMarket
from ..models import Tweet

CLUSTER_TICKERS: Dict[str, Tuple[str, ...]] = {
    "semis": ("NVDA", "AMD", "AVGO", "SMCI", "MSFT", "AAPL"),
    "megacap": ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NFLX"),
    "highbeta": ("TSLA", "PLTR", "COIN", "SMCI", "NFLX", "UBER"),
    "macro": ("SPY", "QQQ", "TLT", "GLD", "IWM", "XLF"),
    "general": ("AAPL", "NVDA", "TSLA", "MSFT", "SPY", "QQQ", "META", "AMD", "PLTR", "COIN"),
}

# Ground truth for the demo. Deliberately includes strong, weak, noise and
# anti-signal accounts so the scorer's ability to separate them is visible.
DEMO_SKILLS: Dict[str, float] = {
    "demo_semis": 0.90,
    "demo_silicon": 0.70,
    "demo_mega": 0.85,
    "demo_value": 0.60,
    "demo_degen": 0.75,
    "demo_momo": 0.55,
    "demo_macro": 0.65,
    "demo_rates": 0.60,
    "demo_quant": 0.80,
    "demo_flow": 0.70,
    "demo_wafer": 0.00,
    "demo_bigtech": 0.05,
    "demo_retail": 0.00,
    "demo_etf": 0.00,
    "demo_news": 0.00,
    "demo_charts": 0.10,
    "demo_dividend": 0.15,
    "demo_hedge": 0.20,
    "demo_ape": -0.45,
    "demo_fab": -0.50,
}

BULL_TEMPLATES = (
    "Added to ${t} here. Breakout above {p1} on volume, targeting {p2} over the next {w} weeks. Strong setup.",
    "Still long ${t}. Uptrend intact, buying dips toward {p1}. Price target {p2}.",
    "${t} looks undervalued at these levels. Accumulating, expecting a rally into month end.",
    "Big beat for ${t} tonight. Guidance raised, gap up tomorrow. Bullish.",
    "Calls on ${t} are cheap. Breakout setup with a price target of {p2}. Risk on.",
    "Long ${t} and $QQQ into the close. Breadth is strong, adding on strength.",
)

BEAR_TEMPLATES = (
    "Shorting ${t} into earnings. Guidance looks weak, price target {p2}. Overvalued.",
    "Sold my ${t}. Breakdown below {p1}, downside to {p2}. Bearish.",
    "${t} is a bubble here. Dumping into strength, expecting a crash toward {p2}.",
    "Trimmed ${t}. Momentum fading, weak volume, lower lows. Fading this.",
    "Puts on ${t}. Overvalued after the run, downside {p2}, target cut.",
    "Short ${t} and $QQQ here. Breadth is weak, the rally is exhausted.",
)

NOISE_TEMPLATES = (
    "Anyone watching ${t} today? Not sure what to do here.",
    "What is the consensus on ${t}? Bull or bear?",
    "Watching ${t} closely, no position yet.",
    "Great thread on ${t} by @someone. Worth a read.",
    "Markets are wild today lol. Nothing to do.",
    "RT @someone: ${t} to the moon 🚀🚀",
    "@friend check ${t} when you get a chance",
    "Join my telegram for ${t} signals t.me/notarealchannel",
)


@dataclass
class MockSource:
    """Generates a deterministic stream of tweets for the whitelisted accounts."""

    accounts: Sequence[AccountConfig]
    market: SyntheticMarket
    skills: Dict[str, float] = field(default_factory=lambda: dict(DEMO_SKILLS))
    seed: int = 7
    noise_rate: float = 0.15
    name: str = "mock"

    def _rng(self, handle: str) -> random.Random:
        stable = sum((i + 1) * ord(c) for i, c in enumerate(handle))
        return random.Random(self.seed * 100_003 + stable)

    def _clusters_for(self, account: AccountConfig) -> Tuple[str, ...]:
        return CLUSTER_TICKERS.get(account.cluster, CLUSTER_TICKERS["general"])

    def _pick_ticker(self, account: AccountConfig, rng: random.Random) -> str:
        cluster = self._clusters_for(account)
        if rng.random() < 0.75:
            return rng.choice(cluster)
        return rng.choice(CLUSTER_TICKERS["general"])

    def _price_on(self, ticker: str, day: date) -> float:
        series = self.market.series.get(ticker)
        bar = series.bar_on(day) if series else None
        return bar.close if bar else 100.0

    def _skill(self, handle: str) -> float:
        return self.skills.get(handle, 0.0)

    def _direction_for(
        self, ticker: str, day: date, horizon: int, skill: float, rng: random.Random
    ) -> Optional[str]:
        result = self.market.forward_excess(ticker, day, horizon)
        if result is None:
            return None
        _, _, excess = result
        if excess == 0:
            return rng.choice(("bullish", "bearish"))
        correct = excess > 0
        p_correct = 0.5 + 0.5 * skill
        agree = rng.random() < p_correct
        bullish = correct if agree else not correct
        return "bullish" if bullish else "bearish"

    def _compose(
        self, ticker: str, direction: str, price: float, rng: random.Random
    ) -> str:
        template = rng.choice(BULL_TEMPLATES if direction == "bullish" else BEAR_TEMPLATES)
        if direction == "bullish":
            p1, p2 = price * 0.97, price * 1.12
        else:
            p1, p2 = price * 1.03, price * 0.88
        return template.format(
            t=ticker, p1=f"{p1:.0f}", p2=f"{p2:.0f}", w=rng.randint(1, 4)
        )

    def _tweet_time(self, day: date, rng: random.Random) -> datetime:
        minute = rng.randint(0, 390)
        hour_utc = 13 + minute // 60
        return datetime.combine(day, time(hour_utc, minute % 60), tzinfo=timezone.utc)

    def generate(self, start: date, end: date) -> List[Tweet]:
        tweets: List[Tweet] = []
        days = [d for d in self.market.trading_days if start <= d <= end]
        for account in sorted(self.accounts, key=lambda a: a.handle):
            if not account.enabled:
                continue
            rng = self._rng(account.handle)
            skill = self._skill(account.handle)
            daily = max(1, int(round(1.5 + abs(skill) * 1.5)))
            for day in days:
                for i in range(rng.randint(0, daily)):
                    created = self._tweet_time(day, rng)
                    if rng.random() < self.noise_rate:
                        ticker = self._pick_ticker(account, rng)
                        text = rng.choice(NOISE_TEMPLATES).format(t=ticker)
                        tweets.append(
                            Tweet(
                                id=f"mock-{account.handle}-{day.isoformat()}-{i}",
                                author=account.handle,
                                text=text,
                                created_at=created,
                                is_retweet=text.startswith("RT @"),
                                is_reply=text.startswith("@"),
                            )
                        )
                        continue

                    ticker = self._pick_ticker(account, rng)
                    horizon = rng.choice((1, 5, 5, 5, 5, 21))
                    direction = self._direction_for(ticker, day, horizon, skill, rng)
                    if direction is None:
                        continue
                    text = self._compose(ticker, direction, self._price_on(ticker, day), rng)
                    tweets.append(
                        Tweet(
                            id=f"mock-{account.handle}-{day.isoformat()}-{i}",
                            author=account.handle,
                            text=text,
                            created_at=created,
                        )
                    )
        tweets.sort(key=lambda t: t.created_at)
        return tweets

    # -- TweetSource protocol -------------------------------------------
    def fetch(
        self,
        handles: Sequence[str],
        since: datetime,
        until: datetime,
        limit_per_account: int = 100,
    ) -> List[Tweet]:
        wanted = {h.lstrip("@").lower() for h in handles}
        start = since.date() - timedelta(days=1)
        end = until.date() + timedelta(days=1)
        tweets = [t for t in self.generate(start, end) if t.author in wanted]
        tweets = [t for t in tweets if since <= t.created_at <= until]
        out: List[Tweet] = []
        counts: Dict[str, int] = {}
        for tweet in tweets:
            if counts.get(tweet.author, 0) >= limit_per_account:
                continue
            counts[tweet.author] = counts.get(tweet.author, 0) + 1
            out.append(tweet)
        return out

"""Rule-based tweet parser (the zero-cost baseline for the NLP layer).

It is intentionally boring and auditable: a finance lexicon, negation handling
and a confidence heuristic. It exists so the whole pipeline can run without an
LLM key, and it doubles as an offline baseline to measure the LLM against.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from ..config import NLPConfig
from ..models import Direction, TradingSignal, Tweet
from .tickers import TickerExtractor

BULL_WORDS = frozenset(
    """
    bullish bull bulls long longs buy buying bought add adding added accumulate
    accumulating accumulation calls call breakout out upside rally rip moon rocket
    strength strong stronger uptrend squeeze higher highs ath undervalued cheap
    beat beats explode parabolic overweight upgrade outperform bid green
    """.split()
)

BEAR_WORDS = frozenset(
    """
    bearish bear bears short shorts shorting shorted sell selling sold puts put
    breakdown down downside dump crash tank weak weakness weaker downtrend fade
    overvalued expensive rich miss misses lower lows bubble top rotation
    underweight downgrade underperform offer red bloodbath rug liquidation
    """.split()
)

BULL_PHRASES = (
    "gap up", "break out", "breaking out", "broke out", "all-time high",
    "all time high", "buy the dip", "buying the dip", "risk on",
    "price target raised", "target raised", "new highs",
)

BEAR_PHRASES = (
    "gap down", "break down", "breaking down", "broke down", "all-time low",
    "all time low", "sell off", "selloff", "risk off", "dead cat bounce",
    "price target cut", "target cut", "new lows", "profit taking",
)

ACTION_RE = re.compile(
    r"\b(buying|bought|buy|adding|added|add|long|shorting|shorted|short|"
    r"selling|sold|sell|trimming|trimmed|trim|scaling|stalking)\b",
    re.IGNORECASE,
)
HEDGE_RE = re.compile(
    r"\b(maybe|might|could|considering|thinking about|possibly|not sure|if)\b",
    re.IGNORECASE,
)
TARGET_RE = re.compile(
    r"(?:price target|pt|target(?:ing|ed)?)\s*[:=]?\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(
    r"\b(not|no|never|isn'?t|aren'?t|won'?t|don'?t|doesn'?t|can'?t|cannot|hardly)\b"
    r"(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)

TIMEFRAMES: Tuple[Tuple[re.Pattern, int, str], ...] = (
    (re.compile(r"\b(0dte|intraday|day ?trade|today|tomorrow)\b", re.I), 1, "intraday"),
    (re.compile(r"\b(this|next) week\b|\bswing\b|\bweekly\b", re.I), 5, "swing"),
    (re.compile(r"\b(this|next) month\b|\bmonthly\b|\b4-6 weeks\b", re.I), 21, "monthly"),
    (re.compile(r"\b(long[ -]term|this year|next year|12 months?)\b", re.I), 60, "long-term"),
)


def _negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 40):start]
    return bool(NEGATION_RE.search(prefix))


def _count(text_lower: str, words: Iterable[str], phrases: Sequence[str]) -> int:
    score = 0
    for word in words:
        for match in re.finditer(rf"\b{re.escape(word)}\b", text_lower):
            if not _negated(text_lower, match.start()):
                score += 1
    for phrase in phrases:
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", text_lower):
            if not _negated(text_lower, match.start()):
                score += 1
    return score


def detect_horizon(text: str, default: int = 5) -> Tuple[int, Optional[str]]:
    for pattern, days, label in TIMEFRAMES:
        if pattern.search(text):
            return days, label
    return default, None


class RulesParser:
    def __init__(
        self,
        universe: Iterable[str],
        blacklist: Iterable[str] = (),
        config: Optional[NLPConfig] = None,
    ) -> None:
        self.config = config or NLPConfig()
        self.extractor = TickerExtractor(
            universe, blacklist, max_tickers=self.config.max_tickers_per_tweet
        )

    def parse(self, tweet: Tweet) -> List[TradingSignal]:
        text = tweet.text
        lower = text.lower()

        tickers = self.extractor.extract(text)
        if not tickers:
            return []

        bull = _count(lower, BULL_WORDS, BULL_PHRASES)
        bear = _count(lower, BEAR_WORDS, BEAR_PHRASES)
        if bull == bear:
            return []
        direction = Direction.BULLISH if bull > bear else Direction.BEARISH

        horizon, timeframe_label = detect_horizon(text, self.config.default_horizon_days)

        confidence = 0.5 + 0.1 * min(abs(bull - bear), 3)
        if self.extractor.is_cashtag(text, tickers[0]):
            confidence += 0.05
        if timeframe_label:
            confidence += 0.07
        if TARGET_RE.search(text):
            confidence += 0.06
        if ACTION_RE.search(text):
            confidence += 0.05
        if HEDGE_RE.search(text):
            confidence -= 0.08
        confidence = round(max(0.35, min(0.95, confidence)), 2)

        actionable = confidence >= self.config.min_confidence
        rationale = ", ".join(
            [
                f"{direction.value} {bull}/{bear}",
                f"tf={timeframe_label or 'default'}",
                f"conf={confidence:.2f}",
            ]
        )

        return [
            TradingSignal(
                tweet_id=tweet.id,
                author=tweet.author,
                ticker=ticker,
                direction=direction,
                horizon_days=horizon,
                confidence=confidence,
                created_at=tweet.created_at,
                actionable=actionable,
                rationale=rationale,
                parser="rules",
            )
            for ticker in tickers
        ]

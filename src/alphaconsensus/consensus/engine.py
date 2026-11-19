"""Consensus aggregation: the core of the product.

Design choices worth knowing:

* **One vote per author.** An account tweeting the same idea five times in an
  hour still has one vote; we keep its most confident signal in the window.
* **Weighted quorum.** Passing requires both a minimum number of distinct
  accounts and a minimum summed credibility weight, so three low-quality
  accounts cannot outvote two high-quality ones by count alone.
* **Directional dominance.** The winning side must hold ``min_agreement`` of
  the total weight, which blocks firing on a 51/49 split.
* **Cooldown.** Once a ticker fires, it is muted for ``cooldown_minutes`` to
  avoid re-entering on every new tweet that confirms the same idea.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Iterable, List, Optional

from ..config import ConsensusConfig
from ..models import ConsensusSignal, Direction, TradingSignal


class ConsensusEngine:
    def __init__(
        self,
        config: Optional[ConsensusConfig] = None,
        weights: Optional[Dict[str, float]] = None,
        overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        self.config = config or ConsensusConfig()
        self.weights: Dict[str, float] = dict(weights or {})
        if overrides:
            self.weights.update(overrides)
        self._signals: Deque[TradingSignal] = deque()
        self._last_fire: Dict[str, datetime] = {}

    # -- helpers ---------------------------------------------------------
    def weight_for(self, author: str) -> float:
        return float(self.weights.get(author, self.config.default_author_weight))

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.config.window_minutes)
        while self._signals and self._signals[0].created_at < cutoff:
            self._signals.popleft()

    def _window_signals(self, ticker: str, now: datetime) -> List[TradingSignal]:
        self._prune(now)
        return [s for s in self._signals if s.ticker == ticker and s.actionable]

    # -- main API --------------------------------------------------------
    def ingest(self, signal: TradingSignal, now: Optional[datetime] = None) -> Optional[ConsensusSignal]:
        if not signal.actionable:
            return None
        if self.weight_for(signal.author) <= 0:
            return None

        self._signals.append(signal)
        now = now or signal.created_at
        self._prune(now)

        window = self._window_signals(signal.ticker, now)
        if not window:
            return None

        # One vote per author: keep each author's most confident signal.
        by_author: Dict[str, TradingSignal] = {}
        for candidate in window:
            current = by_author.get(candidate.author)
            if current is None or candidate.confidence > current.confidence:
                by_author[candidate.author] = candidate

        bulls = [s for s in by_author.values() if s.direction is Direction.BULLISH]
        bears = [s for s in by_author.values() if s.direction is Direction.BEARISH]
        bull_weight = sum(self.weight_for(s.author) for s in bulls)
        bear_weight = sum(self.weight_for(s.author) for s in bears)
        total_weight = bull_weight + bear_weight
        if total_weight <= 0:
            return None

        if bull_weight >= bear_weight:
            direction, dominant, voters = Direction.BULLISH, bull_weight, bulls
        else:
            direction, dominant, voters = Direction.BEARISH, bear_weight, bears

        if len(voters) < self.config.min_accounts:
            return None
        if dominant < self.config.min_weight:
            return None
        if dominant / total_weight < self.config.min_agreement:
            return None

        last = self._last_fire.get(signal.ticker)
        if last is not None and now - last < timedelta(minutes=self.config.cooldown_minutes):
            return None

        self._last_fire[signal.ticker] = now
        voters.sort(key=lambda s: s.confidence, reverse=True)
        horizons = sorted(s.horizon_days for s in voters)
        return ConsensusSignal(
            ticker=signal.ticker,
            direction=direction,
            score=round(dominant, 4),
            n_accounts=len(voters),
            accounts=[s.author for s in voters],
            window_start=min(s.created_at for s in voters),
            window_end=now,
            created_at=now,
            avg_confidence=round(sum(s.confidence for s in voters) / len(voters), 4),
            horizon_days=horizons[len(horizons) // 2],
        )

    def ingest_many(
        self, signals: Iterable[TradingSignal]
    ) -> List[ConsensusSignal]:
        fired: List[ConsensusSignal] = []
        for signal in sorted(signals, key=lambda s: s.created_at):
            result = self.ingest(signal)
            if result is not None:
                fired.append(result)
        return fired

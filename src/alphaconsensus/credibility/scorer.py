"""Credibility scoring: turn a track record of calls into a voting weight.

The estimator is deliberately conservative:

  * hits are measured on **excess return vs SPY**, not absolute return, so a
    permabull in a bull market does not get credit for beta;
  * the hit rate is shrunk towards 0.5 with a Beta prior, so 3 lucky calls do
    not outrank 60 mediocre ones;
  * weight combines reliability (edge over a coin flip) with magnitude (size
    of the edge), and is discounted while the sample is small.

A negative edge yields weight 0: the account is silenced, not inverted.
Inverting bad accounts is a separate strategy with its own risks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .prices import MarketData
from ..models import AccountScore, TradingSignal, utcnow


@dataclass(frozen=True)
class ScorerConfig:
    prior_strength: float = 4.0
    min_calls: int = 20
    excess_scale: float = 0.04
    provisional_discount: float = 0.25
    min_weight: float = 0.02
    max_horizon_days: int = 60


class CredibilityScorer:
    def __init__(self, config: Optional[ScorerConfig] = None) -> None:
        self.config = config or ScorerConfig()

    def _excess_for(self, signal: TradingSignal, market: MarketData) -> Optional[float]:
        horizon = max(1, min(signal.horizon_days, self.config.max_horizon_days))
        result = market.forward_excess(signal.ticker, signal.created_at.date(), horizon)
        if result is None:
            return None
        _, _, excess = result
        return signal.direction.sign * excess

    def score(
        self,
        signals: Iterable[TradingSignal],
        market: MarketData,
    ) -> Dict[str, AccountScore]:
        edges: Dict[str, List[float]] = {}
        for signal in signals:
            if not signal.actionable:
                continue
            excess = self._excess_for(signal, market)
            if excess is None:
                continue
            edges.setdefault(signal.author, []).append(excess)

        scores: Dict[str, AccountScore] = {}
        for handle, values in edges.items():
            n = len(values)
            hits = sum(1 for v in values if v > 0)
            hit_rate = hits / n
            prior = self.config.prior_strength
            shrunk = (hits + prior * 0.5) / (n + prior)
            reliability = max(0.0, min(1.0, (shrunk - 0.5) * 2.0))
            mean_excess = sum(values) / n
            magnitude = max(0.0, math.tanh(mean_excess / self.config.excess_scale))
            weight = reliability * (0.55 + 0.45 * magnitude)
            provisional = n < self.config.min_calls
            if provisional:
                weight *= max(self.config.provisional_discount, n / self.config.min_calls)
            if weight < self.config.min_weight:
                weight = 0.0
            scores[handle] = AccountScore(
                handle=handle,
                n_calls=n,
                hits=hits,
                hit_rate=round(hit_rate, 4),
                shrunk_hit_rate=round(shrunk, 4),
                mean_excess_return=round(mean_excess, 6),
                weight=round(weight, 4),
                provisional=provisional,
                computed_at=utcnow(),
            )
        return scores

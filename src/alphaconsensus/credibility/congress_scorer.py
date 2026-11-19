"""Credibility scoring for congressional trades.

Two clocks, deliberately:

  * ``transaction_date`` — what the member knew when they traded. Not tradable,
    but it measures whether the call itself had an edge.
  * ``disclosure_date`` — the first day a retail trader could copy the trade.
    This is the only number that matters for the strategy.

The gap between both is the alpha decay caused by the STOCK Act lag. A member
who looks brilliant on the transaction clock but worthless on the disclosure
clock is not a signal; they are a history lesson.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .prices import PriceSeries
from ..ingestion.congress import CongressTrade


@dataclass(frozen=True)
class CongressScore:
    member: str
    member_slug: str
    n_trades: int
    buys: int
    sells: int
    hit_rate_txn: float
    hit_rate_disc: float
    mean_excess_txn: float
    mean_excess_disc: float
    decay: float
    weight: float
    provisional: bool
    significant: bool = False
    t_stat: float = 0.0
    unique_tickers: int = 0

    def to_row(self) -> Dict[str, object]:
        return {
            "member": self.member,
            "member_slug": self.member_slug,
            "n_trades": self.n_trades,
            "buys": self.buys,
            "sells": self.sells,
            "hit_rate_txn": round(self.hit_rate_txn, 4),
            "hit_rate_disc": round(self.hit_rate_disc, 4),
            "mean_excess_txn": round(self.mean_excess_txn, 6),
            "mean_excess_disc": round(self.mean_excess_disc, 6),
            "decay": round(self.decay, 6),
            "weight": round(self.weight, 4),
            "provisional": self.provisional,
            "significant": self.significant,
            "t_stat": round(self.t_stat, 3),
            "unique_tickers": self.unique_tickers,
        }


@dataclass(frozen=True)
class CongressScorerConfig:
    horizon_days: int = 21
    prior_strength: float = 4.0
    min_trades: int = 8
    excess_scale: float = 0.05
    provisional_discount: float = 0.25
    min_weight: float = 0.02


class CongressCredibilityScorer:
    def __init__(self, config: Optional[CongressScorerConfig] = None) -> None:
        self.config = config or CongressScorerConfig()

    @staticmethod
    def _signed_excess(
        series: PriceSeries,
        spy: PriceSeries,
        start,
        direction: int,
        horizon: int,
    ) -> Optional[float]:
        entry = series.index_after(start)
        exit_idx = entry + horizon - 1
        if entry >= len(series) or exit_idx >= len(series):
            return None
        entry_date = series.bars[entry].date
        exit_date = series.bars[exit_idx].date

        spy_entry_idx = spy.index_on_or_after(entry_date)
        spy_exit_idx = spy.index_on_or_after(exit_date)
        if spy_entry_idx >= len(spy) or spy_exit_idx >= len(spy):
            return None

        stock_ret = series.bars[exit_idx].close / series.bars[entry].open - 1.0
        spy_ret = spy.bars[spy_exit_idx].close / spy.bars[spy_entry_idx].open - 1.0
        return direction * (stock_ret - spy_ret)

    def score(
        self,
        trades: Iterable[CongressTrade],
        prices: Dict[str, PriceSeries],
        benchmark: str = "SPY",
    ) -> Dict[str, CongressScore]:
        trades = list(trades)
        spy = prices.get(benchmark)
        if spy is None:
            raise ValueError(f"Falta el benchmark {benchmark} en los precios")

        per_member: Dict[str, Dict[str, List[float]]] = {}
        counts: Dict[str, List[int]] = {}
        for trade in trades:
            if trade.type not in {"purchase", "sale"}:
                continue
            series = prices.get(trade.ticker)
            if series is None or trade.transaction_date is None or trade.disclosure_date is None:
                continue
            direction = 1 if trade.type == "purchase" else -1
            disc = self._signed_excess(
                series, spy, trade.disclosure_date, direction, self.config.horizon_days
            )
            txn = self._signed_excess(
                series, spy, trade.transaction_date, direction, self.config.horizon_days
            )
            if disc is None and txn is None:
                continue
            bucket = per_member.setdefault(trade.member_slug, {"disc": [], "txn": []})
            if disc is not None:
                bucket["disc"].append(disc)
            if txn is not None:
                bucket["txn"].append(txn)
            counter = counts.setdefault(trade.member_slug, [0, 0])
            if trade.type == "purchase":
                counter[0] += 1
            else:
                counter[1] += 1

        scores: Dict[str, CongressScore] = {}
        for slug, bucket in per_member.items():
            disc = bucket["disc"]
            txn = bucket["txn"]
            if not disc:
                continue
            n = len(disc)
            hits = sum(1 for value in disc if value > 0)
            prior = self.config.prior_strength
            shrunk = (hits + prior * 0.5) / (n + prior)
            reliability = max(0.0, min(1.0, (shrunk - 0.5) * 2.0))
            mean_disc = sum(disc) / n
            magnitude = max(0.0, math.tanh(mean_disc / self.config.excess_scale))
            weight = reliability * (0.55 + 0.45 * magnitude)

            mean_txn = sum(txn) / len(txn) if txn else 0.0
            std = statistics.stdev(disc) if n > 1 else 0.0
            t_stat = (mean_disc / (std / math.sqrt(n))) if std > 0 else 0.0
            unique_tickers = len({t.ticker for t in trades if t.member_slug == slug})
            buys, sells = counts.get(slug, [0, 0])

            provisional = n < self.config.min_trades
            if provisional:
                weight *= max(self.config.provisional_discount, n / self.config.min_trades)
            significant = t_stat >= 2.0 and n >= 15
            if not significant:
                if t_stat < 1.0:
                    weight = 0.0
                else:
                    weight *= 0.5
                    provisional = True
            if weight < self.config.min_weight:
                weight = 0.0
            scores[slug] = CongressScore(
                member=_member_name(slug, trades),
                member_slug=slug,
                n_trades=n,
                buys=buys,
                sells=sells,
                hit_rate_txn=(sum(1 for v in txn if v > 0) / len(txn)) if txn else 0.0,
                hit_rate_disc=hits / n,
                mean_excess_txn=mean_txn,
                mean_excess_disc=mean_disc,
                decay=mean_txn - mean_disc,
                weight=weight,
                provisional=provisional,
                significant=significant,
                t_stat=t_stat,
                unique_tickers=unique_tickers,
            )
        return scores


def _member_name(slug: str, trades: Iterable[CongressTrade]) -> str:
    for trade in trades:
        if trade.member_slug == slug:
            return trade.member
    return slug

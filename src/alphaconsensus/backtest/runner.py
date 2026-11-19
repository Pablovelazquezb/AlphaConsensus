"""End-to-end replay: synthetic tweets → NLP → credibility → consensus → paper P&L.

The runner is deliberately explicit (no framework) so every step is auditable
and easy to swap in Phase 2/3: replace ``MockSource`` with ``ApifySource``,
replace ``SyntheticMarket`` with real bars, keep everything else identical.

It also runs a **credibility ablation**: the same consensus rules with every
account voting with equal weight. The gap between both runs is the value added
by the scoring layer (and a sanity check that the weighting is not cosmetic).
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..config import Settings
from ..consensus.engine import ConsensusEngine
from ..credibility.prices import Bar, SyntheticMarket
from ..credibility.scorer import CredibilityScorer
from ..execution.simulator import PaperSimulator
from ..ingestion.mock import MockSource
from ..ingestion.pipeline import TweetFilter
from ..models import AccountScore, ConsensusSignal, Trade, TradingSignal, Tweet
from ..nlp.service import SignalExtractor
from ..risk.engine import RiskEngine
from ..storage.db import Repository
from .metrics import compute_stats

log = logging.getLogger(__name__)


@dataclass
class SimOutcome:
    trades: List[Trade]
    equity_curve: List[tuple]
    executed: List[ConsensusSignal]
    rejections: Dict[str, int]
    stats: Dict[str, float]


@dataclass
class RunResult:
    market: SyntheticMarket
    tweets: List[Tweet]
    signals: List[TradingSignal]
    scores: Dict[str, AccountScore]
    consensus: List[ConsensusSignal]
    outcome: SimOutcome
    benchmark: SimOutcome
    ingest_stats: Dict[str, int]
    parse_latency_ms: Dict[str, float]
    live_start: datetime
    live_end: datetime
    seed: int

    @property
    def trades(self) -> List[Trade]:
        return self.outcome.trades

    @property
    def stats(self) -> Dict[str, float]:
        return self.outcome.stats

    def to_report(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "live_start": self.live_start.date().isoformat(),
            "live_end": self.live_end.date().isoformat(),
            "stats": self.stats,
            "ablation_equal_weight": self.benchmark.stats,
            "ingest": self.ingest_stats,
            "risk_rejections": self.outcome.rejections,
            "parse_latency_ms": self.parse_latency_ms,
            "accounts": [s.to_row() for s in self.scores.values()],
            "consensus": [c.to_row() for c in self.consensus],
            "trades": [t.to_row() for t in self.trades],
        }


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def _simulate(
    consensus: Sequence[ConsensusSignal],
    market: SyntheticMarket,
    settings: Settings,
    days: Sequence[date],
    live_start_idx: int,
) -> SimOutcome:
    broker = PaperSimulator(
        equity=settings.risk.equity,
        slippage_bps=settings.execution.slippage_bps,
        commission_per_share=settings.execution.commission_per_share,
    )
    risk = RiskEngine(settings.risk)
    rejections: Counter = Counter()
    executed: List[ConsensusSignal] = []

    schedule: Dict[int, List[ConsensusSignal]] = {}
    for signal in consensus:
        series = market.series.get(signal.ticker)
        if series is None:
            rejections["no_data"] += 1
            continue
        entry_idx = series.index_after(signal.created_at.date())
        if entry_idx >= len(series) or entry_idx < live_start_idx:
            rejections["no_entry_bar"] += 1
            continue
        schedule.setdefault(entry_idx, []).append(signal)

    last_closes: Dict[str, float] = {}
    for session in range(live_start_idx, len(days)):
        day = days[session]
        bars = market.bars_for(day)
        closes = {ticker: bar.close for ticker, bar in bars.items()}

        for signal in schedule.get(session, []):
            bar = bars.get(signal.ticker)
            series = market.series.get(signal.ticker)
            if bar is None or series is None:
                rejections["missing_bar"] += 1
                continue
            prev = max(0, session - 1)
            risk_bar = Bar(day, bar.open, bar.high, bar.low, bar.open, bar.volume)
            decision = risk.evaluate(
                signal,
                risk_bar,
                series.atr(prev),
                series.avg_dollar_volume(prev),
                broker.equity(last_closes),
                broker.peak_equity,
                broker.open_tickers,
            )
            if not decision.approved:
                rejections[decision.reason] += 1
                continue
            broker.open_position(
                signal, decision.qty, bar.open, day, session,
                decision.stop_price, decision.target_price, signal.horizon_days,
            )
            executed.append(signal)

        broker.process_bar(day, bars, session)
        broker.mark(day, closes)
        last_closes = closes

    if broker.positions:
        broker.close_all(days[-1], last_closes, reason="end_of_test")
        if broker.equity_curve:
            broker.equity_curve[-1] = (days[-1], round(broker.equity(last_closes), 2))

    return SimOutcome(
        trades=broker.trades,
        equity_curve=broker.equity_curve,
        executed=executed,
        rejections=dict(rejections),
        stats={},
    )


def run_demo(
    settings: Settings,
    seed: Optional[int] = None,
    persist: bool = True,
    db_path: Optional[Path] = None,
) -> RunResult:
    seed = int(seed if seed is not None else settings.backtest.seed)
    bt = settings.backtest

    market = SyntheticMarket.generate(sorted(settings.universe), days=bt.price_days, seed=seed)
    days = market.trading_days

    live_days = max(5, min(bt.live_days, len(days) - 20))
    live_start_idx = len(days) - live_days
    history_start_idx = max(0, live_start_idx - bt.history_days)
    live_start = days[live_start_idx]
    tweet_start = days[history_start_idx]
    live_cutoff = datetime.combine(live_start, dtime.min, tzinfo=timezone.utc)

    # 1) Ingest (synthetic) + noise filtering --------------------------------
    mock = MockSource(settings.accounts, market, seed=seed)
    raw_tweets = mock.generate(tweet_start, days[-1])
    tweet_filter = TweetFilter(settings.filters)
    tweets = tweet_filter.apply(raw_tweets)

    # 2) NLP extraction ------------------------------------------------------
    extractor = SignalExtractor(settings)
    signals: List[TradingSignal] = []
    latencies: List[float] = []
    for tweet in tweets:
        started = time.perf_counter()
        signals.extend(extractor.parse(tweet))
        latencies.append((time.perf_counter() - started) * 1000.0)
    actionable = [s for s in signals if s.actionable]

    # 3) Credibility: only calls whose outcome is already known ---------------
    history_signals = [s for s in actionable if s.created_at < live_cutoff]
    scores = CredibilityScorer().score(history_signals, market)
    weights = {handle: score.weight for handle, score in scores.items()}

    # 4) Consensus over the live window --------------------------------------
    live_signals = [s for s in actionable if s.created_at >= live_cutoff]
    engine = ConsensusEngine(settings.consensus, weights, settings.weight_overrides)
    consensus = engine.ingest_many(live_signals)

    # 4b) Ablation: identical rules, every whitelisted account gets one vote.
    equal_weights = {handle: 1.0 for handle in settings.enabled_handles}
    equal_config = replace(
        settings.consensus, min_weight=settings.consensus.min_weight * 3.0
    )
    ablation_engine = ConsensusEngine(equal_config, equal_weights)
    ablation_consensus = ablation_engine.ingest_many(live_signals)

    # 5) Execution simulation ------------------------------------------------
    spy = market.spy
    benchmark_return = spy.bars[-1].close / spy.bars[live_start_idx].open - 1.0

    outcome = _simulate(consensus, market, settings, days, live_start_idx)
    outcome.stats = compute_stats(
        outcome.trades, outcome.equity_curve, settings.risk.equity, benchmark_return
    )
    outcome.stats.update(
        {
            "consensus_signals": len(consensus),
            "executed_signals": len(outcome.executed),
            "actionable_signals": len(actionable),
            "accounts_scored": len(scores),
            "accounts_active": sum(1 for w in weights.values() if w > 0),
            "tweets_ingested": len(raw_tweets),
            "tweets_processed": len(tweets),
        }
    )

    ablation = _simulate(ablation_consensus, market, settings, days, live_start_idx)
    ablation.stats = compute_stats(
        ablation.trades, ablation.equity_curve, settings.risk.equity, benchmark_return
    )
    ablation.stats.update(
        {
            "consensus_signals": len(ablation_consensus),
            "executed_signals": len(ablation.executed),
        }
    )

    result = RunResult(
        market=market,
        tweets=tweets,
        signals=signals,
        scores=scores,
        consensus=consensus,
        outcome=outcome,
        benchmark=ablation,
        ingest_stats=dict(tweet_filter.stats),
        parse_latency_ms={
            "p50": round(_percentile(latencies, 50), 3),
            "p95": round(_percentile(latencies, 95), 3),
            "max": round(max(latencies) if latencies else 0.0, 3),
        },
        live_start=datetime.combine(live_start, dtime.min, tzinfo=timezone.utc),
        live_end=datetime.combine(days[-1], dtime.min, tzinfo=timezone.utc),
        seed=seed,
    )

    if persist:
        _persist(settings, result, db_path)
    return result


def _persist(settings: Settings, result: RunResult, db_path: Optional[Path]) -> None:
    path = db_path or (settings.root / "data" / "alphaconsensus.db")
    try:
        repo = Repository(path)
        repo.reset()
        for tweet in result.tweets:
            repo.save_tweet(tweet)
        for signal in result.signals:
            repo.save_signal(signal)
        for score in result.scores.values():
            repo.save_score(score)
        for consensus in result.consensus:
            repo.save_consensus(consensus)
        for trade in result.trades:
            repo.save_trade(trade)
        for day, equity in result.outcome.equity_curve:
            repo.save_equity(str(day), equity)
        repo.commit()
        repo.close()
        log.info("Persistido en %s", path)

        report_path = path.parent / "demo_report.json"
        report_path.write_text(
            json.dumps(result.to_report(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # persistence must never break the run
        log.warning("No se pudo persistir el resultado: %s", exc)

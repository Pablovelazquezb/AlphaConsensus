"""Performance metrics computed from a list of closed trades and an equity curve."""

from __future__ import annotations

import math
from statistics import mean, median, pstdev
from typing import Dict, Optional, Sequence, Tuple

from ..models import Trade


def max_drawdown(equity_curve: Sequence[Tuple[object, float]]) -> float:
    peak = -math.inf
    worst = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (equity / peak) - 1.0
            worst = min(worst, drawdown)
    return worst


def sharpe_ratio(equity_curve: Sequence[Tuple[object, float]]) -> float:
    values = [e for _, e in equity_curve]
    if len(values) < 3:
        return 0.0
    returns = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]
    if len(returns) < 2:
        return 0.0
    deviation = pstdev(returns)
    if deviation == 0:
        return 0.0
    return (mean(returns) / deviation) * math.sqrt(252)


def compute_stats(
    trades: Sequence[Trade],
    equity_curve: Sequence[Tuple[object, float]],
    starting_equity: float,
    benchmark_return: Optional[float] = None,
) -> Dict[str, float]:
    closed = [t for t in trades if not t.is_open]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    final_equity = equity_curve[-1][1] if equity_curve else starting_equity
    total_return = final_equity / starting_equity - 1.0 if starting_equity else 0.0
    hold_days = [
        max(0, (t.exit_time - t.entry_time).days)
        for t in closed
        if t.exit_time is not None
    ]

    stats: Dict[str, float] = {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0,
        "total_pnl": sum(t.pnl for t in closed),
        "avg_trade_pct": mean([t.return_pct for t in closed]) if closed else 0.0,
        "avg_win": mean([t.pnl for t in wins]) if wins else 0.0,
        "avg_loss": mean([t.pnl for t in losses]) if losses else 0.0,
        "starting_equity": starting_equity,
        "final_equity": final_equity,
        "total_return": total_return,
        "max_drawdown": max_drawdown(equity_curve),
        "sharpe": sharpe_ratio(equity_curve),
        "avg_hold_days": mean(hold_days) if hold_days else 0.0,
        "median_hold_days": median(hold_days) if hold_days else 0.0,
        "benchmark_return": benchmark_return if benchmark_return is not None else 0.0,
    }
    if benchmark_return is not None:
        stats["excess_vs_benchmark"] = total_return - benchmark_return
    return stats

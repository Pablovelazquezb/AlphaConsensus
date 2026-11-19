"""Risk filter and position sizing.

Every consensus signal must survive this gate before it reaches the broker:
liquidity, price sanity, volatility cap, position limits, drawdown kill switch.
Sizing is risk-based: a fixed fraction of equity is risked between entry and
stop, and the stop distance comes from ATR.

Fractional shares matter for small accounts: with $1,000 and a 1% risk budget,
whole-share sizing rounds most $300+ stocks down to zero. Alpaca supports
fractional *long* market orders but not fractional shorts, hence the two
separate flags.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Set

from ..config import RiskConfig
from ..credibility.prices import Bar
from ..models import ConsensusSignal, Direction


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    qty: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    reason: str = ""

    @classmethod
    def reject(cls, reason: str) -> "RiskDecision":
        return cls(approved=False, reason=reason)


class RiskEngine:
    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()

    def evaluate(
        self,
        signal: ConsensusSignal,
        bar: Bar,
        atr: float,
        avg_dollar_volume: float,
        equity: float,
        peak_equity: float,
        open_tickers: Optional[Set[str]] = None,
    ) -> RiskDecision:
        cfg = self.config
        open_tickers = open_tickers or set()

        if peak_equity > 0 and equity < peak_equity * (1.0 - cfg.max_drawdown_pct / 100.0):
            return RiskDecision.reject("kill_switch_drawdown")
        if len(open_tickers) >= cfg.max_open_positions:
            return RiskDecision.reject("max_open_positions")
        if signal.ticker in open_tickers:
            return RiskDecision.reject("already_open")
        if signal.direction is Direction.BEARISH and not cfg.allow_shorts:
            return RiskDecision.reject("shorts_disabled")
        if bar.close < cfg.min_price:
            return RiskDecision.reject("penny_stock")
        if atr <= 0:
            return RiskDecision.reject("no_atr")
        if (atr / bar.close) * 100.0 > cfg.max_atr_pct:
            return RiskDecision.reject("volatility_too_high")
        if avg_dollar_volume < cfg.min_dollar_volume:
            return RiskDecision.reject("illiquid")

        risk_amount = equity * (cfg.risk_per_trade_pct / 100.0)
        stop_distance = cfg.stop_atr_mult * atr
        if stop_distance <= 0:
            return RiskDecision.reject("no_stop_distance")

        qty = risk_amount / stop_distance
        max_by_notional = (equity * cfg.max_position_pct / 100.0) / bar.close
        qty = min(qty, max_by_notional)

        whole_only = not cfg.allow_fractional or (
            signal.direction is Direction.BEARISH and not cfg.fractional_shorts
        )
        if whole_only:
            qty = float(math.floor(qty))
        qty = round(qty, 4)

        if qty <= 0:
            return RiskDecision.reject("size_zero")
        if qty * bar.close < cfg.min_notional:
            return RiskDecision.reject("size_too_small")

        if signal.direction is Direction.BULLISH:
            stop = bar.close - stop_distance
            target = bar.close + cfg.take_profit_atr_mult * atr
        else:
            stop = bar.close + stop_distance
            target = bar.close - cfg.take_profit_atr_mult * atr

        return RiskDecision(
            approved=True,
            qty=qty,
            stop_price=round(max(stop, 0.01), 2),
            target_price=round(max(target, 0.01), 2),
            reason="ok",
        )

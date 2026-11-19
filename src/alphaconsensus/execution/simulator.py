"""In-process paper-trading simulator.

Fills happen at the next session open plus slippage, stops/targets are checked
against the session's high/low, and a position is force-closed at the close of
its horizon session. When both the stop and the target are inside the same
daily bar, the stop wins (conservative assumption). This is a backtest harness,
not an execution engine: there is no queue position, partial fill, borrow cost
or market impact model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Dict, List, Optional, Set

from ..credibility.prices import Bar
from ..models import ConsensusSignal, Trade


def _session_dt(day: date, hour: int = 14, minute: int = 30) -> datetime:
    """Market open expressed in UTC (approximate across DST; cosmetic only)."""
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


@dataclass
class _Position:
    trade: Trade
    entry_session: int
    stop: float
    target: float
    horizon_days: int


class PaperSimulator:
    def __init__(
        self,
        equity: float = 100_000.0,
        slippage_bps: float = 5.0,
        commission_per_share: float = 0.0,
    ) -> None:
        self.starting_equity = equity
        self.cash = equity
        self.slippage = slippage_bps / 10_000.0
        self.commission = commission_per_share
        self.positions: Dict[str, _Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[tuple] = []
        self.peak_equity = equity

    # -- accounting ------------------------------------------------------
    def equity(self, closes: Dict[str, float]) -> float:
        value = self.cash
        for ticker, pos in self.positions.items():
            price = closes.get(ticker, pos.trade.entry_price)
            qty = pos.trade.qty
            value += qty * price if pos.trade.side == "long" else -qty * price
        return value

    @property
    def open_tickers(self) -> Set[str]:
        return set(self.positions)

    def _commission(self, qty: int) -> float:
        return self.commission * qty

    def _buy_fill(self, price: float) -> float:
        return price * (1.0 + self.slippage)

    def _sell_fill(self, price: float) -> float:
        return price * (1.0 - self.slippage)

    # -- order flow ------------------------------------------------------
    def open_position(
        self,
        signal: ConsensusSignal,
        qty: float,
        price: float,
        day: date,
        session: int,
        stop: float,
        target: float,
        horizon_days: int,
    ) -> Trade:
        if signal.ticker in self.positions:
            raise ValueError(f"position already open for {signal.ticker}")
        side = signal.side
        fill = self._buy_fill(price) if side == "long" else self._sell_fill(price)
        commission = self._commission(qty)
        if side == "long":
            self.cash -= fill * qty + commission
        else:
            self.cash += fill * qty - commission

        trade = Trade(
            ticker=signal.ticker,
            side=side,
            qty=qty,
            entry_time=_session_dt(day),
            entry_price=round(fill, 4),
            signal_id=signal.id,
            stop_price=stop,
            target_price=target,
        )
        self.positions[signal.ticker] = _Position(
            trade=trade,
            entry_session=session,
            stop=stop,
            target=target,
            horizon_days=horizon_days,
        )
        return trade

    def _close(self, pos: _Position, day: date, exit_price: float, reason: str) -> Trade:
        trade = pos.trade
        qty = trade.qty
        if trade.side == "long":
            fill = self._sell_fill(exit_price)
            self.cash += fill * qty - self._commission(qty)
            gross = (fill - trade.entry_price) * qty
        else:
            fill = self._buy_fill(exit_price)
            self.cash -= fill * qty + self._commission(qty)
            gross = (trade.entry_price - fill) * qty

        trade.exit_time = _session_dt(day, 20, 59)
        trade.exit_price = round(fill, 4)
        trade.pnl = round(gross - 2 * self._commission(qty), 2)
        trade.return_pct = round(trade.pnl / (trade.entry_price * qty), 6) if qty else 0.0
        trade.exit_reason = reason
        self.trades.append(trade)
        del self.positions[trade.ticker]
        return trade

    def process_bar(self, day: date, bars: Dict[str, Bar], session: int) -> List[Trade]:
        closed: List[Trade] = []
        for ticker in list(self.positions):
            pos = self.positions.get(ticker)
            bar = bars.get(ticker)
            if pos is None or bar is None:
                continue
            trade = pos.trade
            is_long = trade.side == "long"
            exit_price: Optional[float] = None
            reason = ""

            if is_long and bar.open <= pos.stop:
                exit_price, reason = bar.open, "gap_stop"
            elif not is_long and bar.open >= pos.stop:
                exit_price, reason = bar.open, "gap_stop"
            elif is_long and bar.low <= pos.stop:
                exit_price, reason = pos.stop, "stop"
            elif not is_long and bar.high >= pos.stop:
                exit_price, reason = pos.stop, "stop"
            elif is_long and bar.high >= pos.target:
                exit_price, reason = pos.target, "target"
            elif not is_long and bar.low <= pos.target:
                exit_price, reason = pos.target, "target"
            elif session - pos.entry_session + 1 >= pos.horizon_days:
                exit_price, reason = bar.close, "horizon"

            if exit_price is not None:
                closed.append(self._close(pos, day, exit_price, reason))
        return closed

    def mark(self, day: date, closes: Dict[str, float]) -> float:
        value = self.equity(closes)
        self.peak_equity = max(self.peak_equity, value)
        self.equity_curve.append((day, round(value, 2)))
        return value

    def close_all(self, day: date, closes: Dict[str, float], reason: str = "end_of_test") -> List[Trade]:
        closed: List[Trade] = []
        for ticker in list(self.positions):
            price = closes.get(ticker)
            if price is None:
                continue
            closed.append(self._close(self.positions[ticker], day, price, reason))
        return closed

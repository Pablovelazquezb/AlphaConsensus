"""Price data: a deterministic synthetic market plus a yfinance adapter.

Synthetic data exists so the entire pipeline (credibility scoring, consensus,
execution, P&L) can be validated end-to-end with zero API keys and zero money.
It is explicitly *not* a market simulator: returns are GBM-ish, there are no
earnings, halts, borrow costs or slippage beyond a fixed bps assumption.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Protocol, Sequence, Tuple


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceSeries:
    def __init__(self, ticker: str, bars: Sequence[Bar]) -> None:
        self.ticker = ticker
        self.bars: List[Bar] = list(bars)
        self._dates: List[date] = [b.date for b in self.bars]
        self._index: Dict[date, int] = {b.date: i for i, b in enumerate(self.bars)}

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def dates(self) -> List[date]:
        return self._dates

    def bar_on(self, day: date) -> Optional[Bar]:
        idx = self._index.get(day)
        return None if idx is None else self.bars[idx]

    def index_after(self, day: date) -> int:
        """First bar strictly after ``day`` (the earliest executable session)."""
        return bisect_right(self._dates, day)

    def index_on_or_after(self, day: date) -> int:
        """First bar on or after ``day`` (for benchmark alignment)."""
        return bisect_left(self._dates, day)

    def atr(self, index: int, period: int = 14) -> float:
        """Average True Range ending at ``index`` (inclusive)."""
        if index < 1:
            return 0.0
        start = max(1, index - period + 1)
        total = 0.0
        count = 0
        for i in range(start, index + 1):
            bar, prev = self.bars[i], self.bars[i - 1]
            tr = max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
            total += tr
            count += 1
        return total / count if count else 0.0

    def avg_dollar_volume(self, index: int, period: int = 20) -> float:
        start = max(0, index - period + 1)
        window = self.bars[start:index + 1]
        if not window:
            return 0.0
        return sum(b.close * b.volume for b in window) / len(window)


def weekdays_ending(end: date, count: int) -> List[date]:
    days: List[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


class SyntheticMarket:
    """Deterministic multi-asset market used by the demo and the tests."""

    def __init__(self, series: Dict[str, PriceSeries], trading_days: List[date]) -> None:
        self.series = series
        self.trading_days = trading_days

    @property
    def spy(self) -> PriceSeries:
        return self.series["SPY"]

    def bars_for(self, day: date) -> Dict[str, Bar]:
        out: Dict[str, Bar] = {}
        for ticker, series in self.series.items():
            bar = series.bar_on(day)
            if bar is not None:
                out[ticker] = bar
        return out

    @classmethod
    def generate(
        cls,
        tickers: Sequence[str],
        days: int = 260,
        end: Optional[date] = None,
        seed: int = 7,
    ) -> "SyntheticMarket":
        end = end or date.today()
        calendar = weekdays_ending(end, days)
        rng = random.Random(seed)

        all_tickers = ["SPY"] + [t for t in tickers if t != "SPY"]
        meta: Dict[str, Tuple[float, float, float, float]] = {}
        for i, ticker in enumerate(all_tickers):
            if ticker == "SPY":
                meta[ticker] = (1.0, 0.0105, 0.0, 300.0)
            else:
                beta = rng.uniform(0.7, 1.9) if ticker not in {"TLT", "GLD"} else rng.uniform(-0.2, 0.2)
                sigma = rng.uniform(0.013, 0.032)
                drift = rng.uniform(-0.0002, 0.0002)
                base = rng.uniform(45.0, 420.0)
                meta[ticker] = (beta, sigma, drift, base)

        series: Dict[str, PriceSeries] = {}
        for ticker in all_tickers:
            beta, sigma, drift, price = meta[ticker]
            tick_rng = random.Random(rng.randrange(1 << 30))
            bars: List[Bar] = []
            # Slow regime shifts keep the series from looking like pure noise.
            regime = 0.0
            for i, day in enumerate(calendar):
                if i % 30 == 0:
                    regime = tick_rng.gauss(0.0, 0.0005)
                market_ret = tick_rng.gauss(0.0, 0.0095)
                idio = tick_rng.gauss(0.0, sigma)
                if ticker == "SPY":
                    ret = market_ret
                else:
                    ret = beta * market_ret + idio + drift + regime
                gap = tick_rng.gauss(0.0, 0.0035)
                open_price = max(1.0, price * (1.0 + gap))
                close_price = max(1.0, open_price * (1.0 + ret))
                span = abs(tick_rng.gauss(0.0, sigma * 0.7)) + 0.004
                high = max(open_price, close_price) * (1.0 + span * 0.6)
                low = min(open_price, close_price) * (1.0 - span * 0.6)
                base_volume = 8_000_000 if ticker == "SPY" else tick_rng.uniform(2_000_000, 45_000_000)
                volume = base_volume * math.exp(tick_rng.gauss(0.0, 0.35))
                bars.append(
                    Bar(
                        date=day,
                        open=round(open_price, 2),
                        high=round(high, 2),
                        low=round(low, 2),
                        close=round(close_price, 2),
                        volume=round(volume),
                    )
                )
                price = close_price
            series[ticker] = PriceSeries(ticker, bars)

        return cls(series=series, trading_days=calendar)

    def forward_excess(
        self,
        ticker: str,
        signal_day: date,
        horizon_days: int,
    ) -> Optional[Tuple[float, float, float]]:
        """Direction-agnostic forward move vs SPY.

        Returns ``(ticker_return, spy_return, excess)`` from the next session's
        open to the close ``horizon_days - 1`` sessions later. ``None`` when the
        window falls outside the generated history.
        """
        series = self.series.get(ticker)
        spy = self.series.get("SPY")
        if series is None or spy is None:
            return None
        entry = series.index_after(signal_day)
        exit_idx = entry + horizon_days - 1
        if entry >= len(series) or exit_idx >= len(series):
            return None
        spy_entry = spy.index_after(signal_day)
        spy_exit = spy_entry + horizon_days - 1
        if spy_entry >= len(spy) or spy_exit >= len(spy):
            return None
        entry_open = series.bars[entry].open
        exit_close = series.bars[exit_idx].close
        spy_ret = spy.bars[spy_exit].close / spy.bars[spy_entry].open - 1.0
        ret = exit_close / entry_open - 1.0
        return ret, spy_ret, ret - spy_ret




class MarketData(Protocol):
    """Anything that can price a forward window for credibility scoring."""

    def forward_excess(
        self, ticker: str, signal_day: date, horizon_days: int
    ) -> Optional[Tuple[float, float, float]]:
        ...


class BarMarket:
    """Adapter that turns loaded daily bars into the scorer's market interface."""

    def __init__(self, series: Dict[str, PriceSeries], benchmark: str = "SPY") -> None:
        self.series = series
        self.benchmark = benchmark

    def forward_excess(
        self, ticker: str, signal_day: date, horizon_days: int
    ) -> Optional[Tuple[float, float, float]]:
        series = self.series.get(ticker)
        spy = self.series.get(self.benchmark)
        if series is None or spy is None or horizon_days < 1:
            return None
        entry = series.index_after(signal_day)
        exit_idx = entry + horizon_days - 1
        if entry >= len(series) or exit_idx >= len(series):
            return None
        spy_entry = spy.index_after(signal_day)
        spy_exit = spy_entry + horizon_days - 1
        if spy_entry >= len(spy) or spy_exit >= len(spy):
            return None
        ret = series.bars[exit_idx].close / series.bars[entry].open - 1.0
        spy_ret = spy.bars[spy_exit].close / spy.bars[spy_entry].open - 1.0
        return ret, spy_ret, ret - spy_ret

class YFinancePrices:
    """Thin adapter used once real prices are wired in (requires yfinance)."""

    def __init__(self) -> None:
        try:
            import yfinance as yf  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "yfinance no está instalado: pip install 'alphaconsensus[prices]'"
            ) from exc
        self._yf = yf

    def fetch(self, tickers: Sequence[str], start: date, end: date) -> Dict[str, PriceSeries]:
        out: Dict[str, PriceSeries] = {}
        for ticker in tickers:
            frame = self._yf.download(
                ticker, start=start.isoformat(), end=end.isoformat(),
                progress=False, auto_adjust=True,
            )
            bars: List[Bar] = []
            for idx, row in frame.iterrows():
                day = idx.date() if hasattr(idx, "date") else idx
                bars.append(
                    Bar(
                        date=day,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]),
                    )
                )
            out[ticker] = PriceSeries(ticker, bars)
        return out

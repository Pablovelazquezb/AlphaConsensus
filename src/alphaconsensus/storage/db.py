"""SQLite persistence for tweets, signals, scores, consensus and trades.

A single file keeps local runs reproducible and makes it trivial to inspect
what the pipeline saw. Production would swap this for Postgres/Timescale
without changing the repository interface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..models import AccountScore, ConsensusSignal, Trade, TradingSignal, Tweet

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets (
    id TEXT PRIMARY KEY,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    is_retweet INTEGER NOT NULL DEFAULT 0,
    is_reply INTEGER NOT NULL DEFAULT 0,
    url TEXT DEFAULT '',
    lang TEXT DEFAULT 'en'
);
CREATE INDEX IF NOT EXISTS idx_tweets_author_time ON tweets(author, created_at);

CREATE TABLE IF NOT EXISTS signals (
    tweet_id TEXT NOT NULL,
    author TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    confidence REAL NOT NULL,
    actionable INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    rationale TEXT DEFAULT '',
    parser TEXT DEFAULT 'rules',
    PRIMARY KEY (tweet_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(created_at);

CREATE TABLE IF NOT EXISTS account_scores (
    handle TEXT PRIMARY KEY,
    n_calls INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    hit_rate REAL NOT NULL,
    shrunk_hit_rate REAL NOT NULL,
    mean_excess_return REAL NOT NULL,
    weight REAL NOT NULL,
    provisional INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consensus_signals (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    score REAL NOT NULL,
    n_accounts INTEGER NOT NULL,
    accounts TEXT NOT NULL,
    avg_confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    pnl REAL NOT NULL DEFAULT 0,
    return_pct REAL NOT NULL DEFAULT 0,
    exit_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS equity_curve (
    date TEXT PRIMARY KEY,
    equity REAL NOT NULL
);
"""


class Repository:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def reset(self) -> None:
        for table in ("tweets", "signals", "account_scores", "consensus_signals", "trades", "equity_curve"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- writers ---------------------------------------------------------
    def save_tweet(self, tweet: Tweet) -> None:
        row = tweet.to_row()
        self.conn.execute(
            "INSERT OR REPLACE INTO tweets (id, author, created_at, text, is_retweet, is_reply, url, lang)"
            " VALUES (:id, :author, :created_at, :text, :is_retweet, :is_reply, :url, :lang)",
            row,
        )

    def save_signal(self, signal: TradingSignal) -> None:
        row = signal.to_row()
        self.conn.execute(
            "INSERT OR REPLACE INTO signals (tweet_id, author, ticker, direction, horizon_days, confidence,"
            " actionable, created_at, rationale, parser)"
            " VALUES (:tweet_id, :author, :ticker, :direction, :horizon_days, :confidence,"
            " :actionable, :created_at, :rationale, :parser)",
            row,
        )

    def save_score(self, score: AccountScore) -> None:
        row = score.to_row()
        self.conn.execute(
            "INSERT OR REPLACE INTO account_scores (handle, n_calls, hits, hit_rate, shrunk_hit_rate,"
            " mean_excess_return, weight, provisional, computed_at)"
            " VALUES (:handle, :n_calls, :hits, :hit_rate, :shrunk_hit_rate, :mean_excess_return,"
            " :weight, :provisional, :computed_at)",
            row,
        )

    def save_consensus(self, signal: ConsensusSignal) -> None:
        row = signal.to_row()
        self.conn.execute(
            "INSERT OR REPLACE INTO consensus_signals (id, ticker, direction, score, n_accounts, accounts,"
            " avg_confidence, created_at, window_start, window_end)"
            " VALUES (:id, :ticker, :direction, :score, :n_accounts, :accounts, :avg_confidence,"
            " :created_at, :window_start, :window_end)",
            row,
        )

    def save_trade(self, trade: Trade) -> None:
        self.conn.execute(
            "INSERT INTO trades (signal_id, ticker, side, qty, entry_time, entry_price, exit_time, exit_price,"
            " pnl, return_pct, exit_reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade.signal_id, trade.ticker, trade.side, trade.qty,
                trade.entry_time.isoformat(), trade.entry_price,
                trade.exit_time.isoformat() if trade.exit_time else None,
                trade.exit_price, trade.pnl, trade.return_pct, trade.exit_reason,
            ),
        )

    def save_equity(self, day: str, equity: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO equity_curve (date, equity) VALUES (?, ?)", (day, equity)
        )

    def commit(self) -> None:
        self.conn.commit()

    # -- readers ---------------------------------------------------------
    def count(self, table: str) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"])

    def trades(self) -> list:
        return list(self.conn.execute("SELECT * FROM trades ORDER BY entry_time"))

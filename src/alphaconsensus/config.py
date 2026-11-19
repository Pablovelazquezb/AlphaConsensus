"""Typed configuration loading plus a tiny .env reader.

No third-party dependencies: the pipeline must bootstrap on a clean machine
with only Python installed. YAML was deliberately avoided for the same reason.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class AccountConfig:
    handle: str
    enabled: bool = True
    cluster: str = "general"
    category: str = ""
    note: str = ""
    weight_override: Optional[float] = None


@dataclass(frozen=True)
class ConsensusConfig:
    window_minutes: int = 1440
    min_accounts: int = 3
    min_weight: float = 0.9
    min_agreement: float = 0.65
    cooldown_minutes: int = 2880
    default_author_weight: float = 0.15


@dataclass(frozen=True)
class RiskConfig:
    equity: float = 100_000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 12.0
    max_open_positions: int = 6
    stop_atr_mult: float = 2.0
    take_profit_atr_mult: float = 4.0
    max_drawdown_pct: float = 15.0
    min_price: float = 5.0
    max_atr_pct: float = 8.0
    min_dollar_volume: float = 20_000_000.0
    allow_shorts: bool = True
    allow_fractional: bool = False
    fractional_shorts: bool = False
    min_notional: float = 0.0


@dataclass(frozen=True)
class ExecutionConfig:
    slippage_bps: float = 5.0
    commission_per_share: float = 0.0


@dataclass(frozen=True)
class NLPConfig:
    mode: str = "rules"  # rules | llm | hybrid
    min_confidence: float = 0.5
    default_horizon_days: int = 5
    max_tickers_per_tweet: int = 3


@dataclass(frozen=True)
class FilterConfig:
    min_tweet_chars: int = 25
    exclude_retweets: bool = True
    exclude_replies: bool = True
    exclude_promos: bool = True


@dataclass(frozen=True)
class BacktestConfig:
    price_days: int = 260
    history_days: int = 200
    live_days: int = 40
    seed: int = 7


@dataclass
class Settings:
    consensus: ConsensusConfig = field(default_factory=ConsensusConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    nlp: NLPConfig = field(default_factory=NLPConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    accounts: List[AccountConfig] = field(default_factory=list)
    universe: Set[str] = field(default_factory=set)
    blacklist: Set[str] = field(default_factory=set)
    root: Path = field(default_factory=Path.cwd)
    config_dir: Path = field(default_factory=lambda: Path.cwd() / "config")

    # -- convenience -----------------------------------------------------
    @property
    def enabled_handles(self) -> List[str]:
        return [a.handle for a in self.accounts if a.enabled]

    @property
    def weight_overrides(self) -> Dict[str, float]:
        return {
            a.handle: float(a.weight_override)
            for a in self.accounts
            if a.enabled and a.weight_override is not None
        }


def load_dotenv(path: Optional[Path] = None) -> None:
    """Minimal .env loader; does not overwrite already-exported variables."""
    path = path or (Path.cwd() / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _section(data: Dict[str, Any], key: str, cls: Any) -> Any:
    raw = data.get(key) or {}
    if not isinstance(raw, dict):
        return cls()
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in valid})


def _resolve_root(root: Optional[Path]) -> Path:
    if root is not None:
        return Path(root).resolve()
    env_root = os.environ.get("ALPHACONSENSUS_HOME")
    if env_root:
        return Path(env_root).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "config" / "settings.json").exists():
            return candidate
    return cwd


def load_settings(root: Optional[Path] = None) -> Settings:
    load_dotenv()
    root = _resolve_root(root)
    config_dir = root / "config"

    data = _read_json(config_dir / "settings.json", {})
    universe_data = _read_json(config_dir / "universe.json", {})
    accounts_data = _read_json(config_dir / "accounts.json", {})

    accounts: List[AccountConfig] = []
    for raw in accounts_data.get("accounts", []):
        if not isinstance(raw, dict) or not raw.get("handle"):
            continue
        accounts.append(
            AccountConfig(
                handle=str(raw["handle"]).lstrip("@").lower(),
                enabled=bool(raw.get("enabled", True)),
                cluster=str(raw.get("cluster", "general")),
                category=str(raw.get("category", "")),
                note=str(raw.get("note", "")),
                weight_override=raw.get("weight_override"),
            )
        )

    universe = {t.upper() for t in universe_data.get("tickers", [])}
    blacklist = {t.upper() for t in universe_data.get("blacklist", [])}

    return Settings(
        consensus=_section(data, "consensus", ConsensusConfig),
        risk=_section(data, "risk", RiskConfig),
        execution=_section(data, "execution", ExecutionConfig),
        nlp=_section(data, "nlp", NLPConfig),
        filters=_section(data, "filters", FilterConfig),
        backtest=_section(data, "backtest", BacktestConfig),
        accounts=accounts,
        universe=universe,
        blacklist=blacklist,
        root=root,
        config_dir=config_dir,
    )


@dataclass(frozen=True)
class XAccount:
    handle: str
    role: str = "voter"
    category: str = ""
    enabled: bool = True


def load_x_accounts(path: Optional[Path] = None) -> List[XAccount]:
    path = path or (Path.cwd() / "config" / "x_accounts.json")
    if not path.exists():
        return []
    data = _read_json(path, {})
    out: List[XAccount] = []
    for raw in data.get("accounts", []):
        if not isinstance(raw, dict) or not raw.get("handle"):
            continue
        out.append(
            XAccount(
                handle=str(raw["handle"]).lstrip("@").lower(),
                role=str(raw.get("role", "voter")),
                category=str(raw.get("category", "")),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return out

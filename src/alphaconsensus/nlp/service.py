"""NLP facade: one entry point, pluggable parser, per-tweet cache."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..config import NLPConfig, Settings
from ..models import TradingSignal, Tweet
from .llm import LLMParser
from .rules import RulesParser

log = logging.getLogger(__name__)


class SignalExtractor:
    def __init__(
        self,
        settings: Settings,
        mode: Optional[str] = None,
        llm: Optional[LLMParser] = None,
    ) -> None:
        self.settings = settings
        self.config: NLPConfig = settings.nlp
        self.mode = (mode or self.config.mode).lower()
        self.rules = RulesParser(settings.universe, settings.blacklist, self.config)
        self.llm = llm if llm is not None else LLMParser(self.config)
        self._cache: Dict[str, List[TradingSignal]] = {}
        if self.mode in {"llm", "hybrid"} and not self.llm.available:
            log.warning("NLP mode=%s pero no hay LLM_API_KEY; se usará el parser de reglas", self.mode)
            self.mode = "rules"

    @property
    def parser_name(self) -> str:
        return "llm" if self.mode in {"llm", "hybrid"} else "rules"

    def parse(self, tweet: Tweet) -> List[TradingSignal]:
        cached = self._cache.get(tweet.id)
        if cached is not None:
            return cached

        signals: Optional[List[TradingSignal]] = None
        if self.mode in {"llm", "hybrid"}:
            signals = self.llm.parse(tweet)
        if signals is None:
            signals = self.rules.parse(tweet)

        signals = signals or []
        if len(self._cache) > 50_000:
            self._cache.clear()
        self._cache[tweet.id] = signals
        return signals

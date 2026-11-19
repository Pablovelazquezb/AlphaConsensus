"""LLM-backed signal extraction with structured JSON output.

Defaults to a generic OpenAI-compatible chat-completions endpoint, which covers
DeepSeek, OpenAI, Together, Groq and local vLLM/Ollama gateways. Configure with
LLM_API_KEY / LLM_BASE_URL / LLM_MODEL.

Any failure returns ``None`` so the caller can fall back to the rule parser;
the trading pipeline must never stall because an LLM is down.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..config import NLPConfig
from ..models import Direction, TradingSignal, Tweet

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a financial-NLP extractor for a trading research system.
Extract every actionable trading call from a tweet.

Rules:
- Only extract tickers explicitly mentioned as cashtags or unambiguous symbols.
- "direction" must be bullish or bearish. If the tweet is not a directional call,
  return an empty signals array.
- "confidence" is 0..1 based on how explicit and decisive the call is. Hedged
  language ("might", "could", "watching") must score below 0.6.
- "horizon_days" is the holding horizon implied by the tweet: intraday 1,
  swing 5, month ~21, long term 60. Default to 5 when unclear.
- Never invent a ticker, a direction or a price target.
- Retweets, questions, jokes and promo spam produce no signals.

Return ONLY JSON: {"signals":[{"ticker":"NVDA","direction":"bullish","horizon_days":5,"confidence":0.8,"actionable":true,"rationale":"short reason"}]}"""

USER_TEMPLATE = """Author: @{author}
Posted: {created_at}
Tweet: {text}"""


class LLMParser:
    name = "llm"

    def __init__(
        self,
        config: Optional[NLPConfig] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.config = config or NLPConfig()
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.timeout = timeout
        self.failures = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _chat(self, tweet: Tweet) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        author=tweet.author,
                        created_at=tweet.created_at.isoformat(),
                        text=tweet.text,
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)

    def parse(self, tweet: Tweet) -> Optional[List[TradingSignal]]:
        """Return None on transport/parse failure (caller falls back to rules)."""
        if not self.available:
            return None
        try:
            data = self._chat(tweet)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            self.failures += 1
            log.warning("LLM parse failed for %s: %s", tweet.id, exc)
            return None

        signals: List[TradingSignal] = []
        for raw in data.get("signals", [])[: self.config.max_tickers_per_tweet]:
            try:
                ticker = str(raw["ticker"]).upper().lstrip("$")
                if not re.fullmatch(r"[A-Z]{1,5}", ticker):
                    continue
                direction = Direction(str(raw["direction"]).lower())
                if direction is Direction.NEUTRAL:
                    continue
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
                horizon = int(raw.get("horizon_days", self.config.default_horizon_days))
                horizon = max(1, min(horizon, 60))
                actionable = bool(raw.get("actionable", confidence >= self.config.min_confidence))
                signals.append(
                    TradingSignal(
                        tweet_id=tweet.id,
                        author=tweet.author,
                        ticker=ticker,
                        direction=direction,
                        horizon_days=horizon,
                        confidence=confidence,
                        created_at=tweet.created_at,
                        actionable=actionable,
                        rationale=str(raw.get("rationale", ""))[:200],
                        parser="llm",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return signals

"""Official X API v2 adapter (recent search only).

The free/Basic tiers cap search at ~7 days and ~10k reads/month, so this
adapter is fine for near-real-time signal generation but NOT for the historical
backtest that feeds credibility scoring. Use Apify (or a licensed dataset) for
history, and this adapter for the live loop once you have a paid tier.

Docs: https://developer.x.com/en/docs/x-api
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..models import Tweet

log = logging.getLogger(__name__)

X_API_BASE = "https://api.x.com/2"


class XApiSource:
    name = "x_api"

    def __init__(self, bearer_token: Optional[str] = None, timeout: int = 30) -> None:
        self.bearer_token = bearer_token or os.environ.get("X_BEARER_TOKEN", "")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.bearer_token)

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.bearer_token:
            raise RuntimeError("Falta X_BEARER_TOKEN (ver .env.example)")
        url = f"{X_API_BASE}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.bearer_token}"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch(
        self,
        handles: Sequence[str],
        since: datetime,
        until: datetime,
        limit_per_account: int = 100,
    ) -> List[Tweet]:
        query = "(" + " OR ".join(f"from:{h.lstrip('@')}" for h in handles) + ")"
        query += " -is:retweet -is:reply"
        max_results = max(10, min(limit_per_account * max(1, len(handles)), 100))

        tweets: List[Tweet] = []
        next_token: Optional[str] = None
        while len(tweets) < limit_per_account * len(handles):
            params: Dict[str, Any] = {
                "query": query,
                "max_results": max_results,
                "tweet.fields": "created_at,author_id,lang,conversation_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            if next_token:
                params["next_token"] = next_token
            try:
                payload = self._get("/tweets/search/recent", params)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                log.warning("X API HTTP %s: %s", exc.code, detail)
                break
            except urllib.error.URLError as exc:
                log.warning("X API inaccesible: %s", exc.reason)
                break

            users = {
                u["id"]: u.get("username", "")
                for u in payload.get("includes", {}).get("users", [])
            }
            for item in payload.get("data", []):
                author = users.get(item.get("author_id", ""), "")
                if not author:
                    continue
                tweets.append(
                    Tweet(
                        id=str(item["id"]),
                        author=author,
                        text=item.get("text", ""),
                        created_at=datetime.fromisoformat(
                            item["created_at"].replace("Z", "+00:00")
                        ),
                        lang=item.get("lang", "en"),
                    )
                )
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                break

        # Client-side window filter: the API ignores since/until on this tier.
        return [t for t in tweets if since <= t.created_at <= until]

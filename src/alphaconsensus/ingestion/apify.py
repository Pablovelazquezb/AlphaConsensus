"""Apify ingestion adapter.

Apify Actors are third-party scrapers of X/Twitter. They are the pragmatic way
to get *historical* tweets: the official X API's cheap tiers only expose a
~7-day search window, which is useless for backtesting an account's track
record.

Cost reference (Apify Store, checked 2026-11):
  * ``apidojo/tweet-scraper`` (V2): ~$0.40 / 1,000 tweets, flat.
  * ``apidojo/twitter-scraper-lite``: ~$0.016/query + ~$0.0004/item.
  * ``kaitoeasyapi/...``: ~$0.18–0.25 / 1,000 tweets depending on plan.

Caveats: scraping X violates its ToS and Actors break when X changes its
frontend. Treat this as a research bridge, keep the actor configurable, and
budget for outages. The actor input is overridable via ``APIFY_INPUT_JSON``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..models import Tweet, ensure_utc

log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    pass


class ApifySource:
    name = "apify"

    def __init__(
        self,
        token: Optional[str] = None,
        actor: Optional[str] = None,
        timeout: int = 300,
        extra_input: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.token = token or os.environ.get("APIFY_TOKEN", "")
        self.actor = actor or os.environ.get("APIFY_ACTOR", "apidojo/twitter-profile-scraper")
        self.timeout = timeout
        raw_extra = extra_input or {}
        if not raw_extra and os.environ.get("APIFY_INPUT_JSON"):
            try:
                raw_extra = json.loads(os.environ["APIFY_INPUT_JSON"])
            except json.JSONDecodeError as exc:
                raise ApifyError("APIFY_INPUT_JSON no es JSON válido") from exc
        self.extra_input = raw_extra

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _run_actor(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.token:
            raise ApifyError("Falta APIFY_TOKEN (ver .env.example)")
        actor_path = self.actor.replace("/", "~")
        query = urllib.parse.urlencode(
            {"token": self.token, "format": "json", "clean": "true", "timeout": self.timeout}
        )
        url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items?{query}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout + 30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ApifyError(f"Apify HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApifyError(f"No se pudo conectar a Apify: {exc.reason}") from exc
        if not isinstance(data, list):
            raise ApifyError(f"Respuesta inesperada de Apify: {type(data).__name__}")
        return data

    def fetch(
        self,
        handles: Sequence[str],
        since: datetime,
        until: datetime,
        limit_per_account: int = 100,
    ) -> List[Tweet]:
        tweets: List[Tweet] = []
        for handle in handles:
            clean = handle.lstrip("@").lower()
            payload: Dict[str, Any] = {
                "searchTerms": [f"from:{clean} since:{since.date()} until:{until.date()}"],
                "maxItems": int(limit_per_account),
                "sort": "Latest",
            }
            payload.update(self.extra_input)
            log.info("Apify: %s (%s → %s, max %d)", clean, since.date(), until.date(), limit_per_account)
            try:
                items = self._run_actor(payload)
            except ApifyError as exc:
                log.warning("Apify falló para @%s: %s", clean, exc)
                continue
            for item in items:
                tweet = self._normalize(item)
                if tweet is not None:
                    tweets.append(tweet)
            time.sleep(0.2)
        return tweets


    def fetch_profiles(
        self,
        handles: Sequence[str],
        limit_per_account: int = 1000,
        workers: int = 1,
    ) -> List[Tweet]:
        """Scrape each account's timeline (historical tweets, newest first).

        Timeline scraping is the practical way to get 12-24 months of history:
        X search is capped to ~7 days on cheap tiers, while a profile timeline
        returns up to the last ~3,200 posts.
        """
        def one(handle: str) -> List[Tweet]:
            clean = handle.lstrip("@").lower()
            payload: Dict[str, Any] = {
                "startUrls": [{"url": f"https://x.com/{clean}"}],
                "maxItems": int(limit_per_account),
                "sort": "Latest",
            }
            payload.update(self.extra_input)
            log.info("Apify perfil: %s (max %d)", clean, limit_per_account)
            try:
                items = self._run_actor(payload)
            except ApifyError as exc:
                log.warning("Apify falló para @%s: %s", clean, exc)
                return []
            out: List[Tweet] = []
            for item in items:
                tweet = self._normalize(item)
                if tweet is not None:
                    out.append(tweet)
            return out

        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=workers) as pool:
                batches = list(pool.map(one, handles))
            return [tweet for batch in batches for tweet in batch]

        tweets: List[Tweet] = []
        for handle in handles:
            tweets.extend(one(handle))
            time.sleep(0.2)
        return tweets


    def search(self, terms: Sequence[str], max_items: int = 200, sort: str = "Latest") -> List[Tweet]:
        """Run a search query (or several) and return normalised tweets."""
        payload: Dict[str, Any] = {
            "searchTerms": list(terms),
            "maxItems": int(max_items),
            "sort": sort,
        }
        payload.update(self.extra_input)
        items = self._run_actor(payload)
        out: List[Tweet] = []
        for item in items:
            tweet = self._normalize(item)
            if tweet is not None:
                out.append(tweet)
        return out


    def fetch_history(
        self,
        handles: Sequence[str],
        since: datetime,
        until: datetime,
        limit_per_chunk: int = 300,
        chunk_days: int = 180,
        workers: int = 1,
    ) -> List[Tweet]:
        """Fetch historical tweets by date range (X search, chunked).

        Timeline scraping only returns recent posts; search with
        ``from:handle since:... until:...`` reaches older windows.
        """
        jobs = []
        for handle in handles:
            cursor = since
            while cursor < until:
                chunk_end = min(cursor + timedelta(days=chunk_days), until)
                jobs.append((handle, cursor, chunk_end))
                cursor = chunk_end + timedelta(seconds=1)

        def one(job):
            handle, start, end = job
            try:
                return self.fetch([handle], start, end, limit_per_account=limit_per_chunk)
            except ApifyError as exc:
                log.warning("Apify histórico falló para @%s %s: %s", handle, start.date(), exc)
                return []

        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=workers) as pool:
                batches = list(pool.map(one, jobs))
        else:
            batches = [one(job) for job in jobs]

        deduped: Dict[str, Tweet] = {}
        for batch in batches:
            for tweet in batch:
                deduped.setdefault(tweet.id, tweet)
        return sorted(deduped.values(), key=lambda t: t.created_at)

    # -- normalisation ---------------------------------------------------
    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
        return ensure_utc(parsed)

    @staticmethod
    def _author(item: Dict[str, Any]) -> str:
        author = item.get("author") or {}
        if isinstance(author, dict):
            for key in ("userName", "screen_name", "username"):
                if author.get(key):
                    return str(author[key]).lstrip("@").lower()
        for key in ("username", "screenName", "userName", "authorUsername"):
            if item.get(key):
                return str(item[key]).lstrip("@").lower()
        return ""

    def _normalize(self, item: Dict[str, Any]) -> Optional[Tweet]:
        if not isinstance(item, dict):
            return None
        text = item.get("text") or item.get("full_text") or item.get("fullText") or ""
        if not text:
            return None
        author = self._author(item)
        if not author:
            return None
        created = self._parse_dt(
            item.get("createdAt") or item.get("created_at") or item.get("timestamp")
        )
        if created is None:
            return None
        tweet_id = str(item.get("id") or item.get("id_str") or item.get("tweetId") or "")
        if not tweet_id:
            digest = hashlib.sha1(f"{author}|{created.isoformat()}|{text}".encode("utf-8")).hexdigest()
            tweet_id = f"apify-{digest[:16]}"
        return Tweet(
            id=tweet_id,
            author=author,
            text=text,
            created_at=created,
            is_retweet=bool(item.get("isRetweet", text.startswith("RT @"))),
            is_reply=bool(item.get("isReply", text.startswith("@"))),
            url=str(item.get("url") or item.get("twitterUrl") or ""),
            lang=str(item.get("lang") or "en"),
        )

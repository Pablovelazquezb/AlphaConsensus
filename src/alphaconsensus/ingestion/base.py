"""Source interface shared by mock, Apify and the official X API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Protocol, Sequence

from ..models import Tweet


class TweetSource(Protocol):
    """Anything that can hand us tweets for a set of accounts and a window."""

    name: str

    def fetch(
        self,
        handles: Sequence[str],
        since: datetime,
        until: datetime,
        limit_per_account: int = 100,
    ) -> List[Tweet]:
        ...

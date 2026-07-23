"""Low-level twitterapi.io client — fetch an account's recent tweets.

Per the twitterapi.io guide ("how-to-monitor-twitter-accounts-for-new-tweets-in-
real-time") the recommended pattern is advanced search with a ``from:<user>``
operator plus ``since_time``/``until_time`` unix-second bounds, paginated by
cursor. This module is HTTP-only and stores nothing — the monitor service turns
the returned tweets into ``TweetCandidate`` rows.

The API key is read from the ``twitterapi_API_KEY`` environment variable
(Django loads the project-root ``.env`` at startup) or passed explicitly.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Iterable

import requests

BASE_URL = "https://api.twitterapi.io"
ADVANCED_SEARCH_PATH = "/twitter/tweet/advanced_search"

# advanced_search returns ~20 tweets/page; bound total pages per account/window.
_MAX_PAGES = 25


class TwitterApiError(RuntimeError):
    """Raised when the twitterapi.io request fails after retries."""


@dataclass
class Tweet:
    """A minimal, storage-agnostic view of one tweet."""

    id: str
    text: str
    created_at: str
    url: str
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    view_count: int = 0

    @classmethod
    def from_api(cls, raw: dict, username: str) -> "Tweet":
        tweet_id = str(raw.get("id") or raw.get("id_str") or "")
        url = raw.get("url") or (
            f"https://x.com/{username}/status/{tweet_id}" if tweet_id else ""
        )
        return cls(
            id=tweet_id,
            text=raw.get("text", ""),
            created_at=raw.get("createdAt") or raw.get("created_at") or "",
            url=url,
            like_count=raw.get("likeCount", 0) or 0,
            retweet_count=raw.get("retweetCount", 0) or 0,
            reply_count=raw.get("replyCount", 0) or 0,
            view_count=raw.get("viewCount", 0) or 0,
        )


def resolve_api_key(explicit: str | None = None) -> str:
    key = (explicit or os.environ.get("twitterapi_API_KEY") or "").strip()
    if not key:
        raise TwitterApiError(
            "twitterapi.io API key not set. Add twitterapi_API_KEY to the "
            "project-root .env (the value from twitterapi.io)."
        )
    return key


@dataclass
class TwitterClient:
    api_key: str
    timeout: int = 20
    request_delay: float = 1.0  # seconds between paginated / per-account calls
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update({"X-API-Key": self.api_key})

    def fetch_recent_tweets(
        self, username: str, hours: int = 24, include_retweets: bool = False
    ) -> list[Tweet]:
        """Return tweets by ``username`` posted in the last ``hours`` hours."""
        now = int(time.time())
        since = now - hours * 3600
        username = username.lstrip("@")

        rt = "include:nativeretweets " if include_retweets else ""
        query = f"from:{username} {rt}since_time:{since} until_time:{now}".strip()

        tweets: list[Tweet] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            params = {"query": query, "queryType": "Latest"}
            if cursor:
                params["cursor"] = cursor

            payload = self._get_with_retry(params)
            for raw in payload.get("tweets", []) or []:
                tweets.append(Tweet.from_api(raw, username))

            if not payload.get("has_next_page"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
            time.sleep(self.request_delay)

        return tweets

    def fetch_many(
        self, usernames: Iterable[str], hours: int = 24
    ) -> dict[str, list[Tweet]]:
        """Fetch recent tweets for several accounts, keyed by username."""
        out: dict[str, list[Tweet]] = {}
        for i, u in enumerate(usernames):
            if i:
                time.sleep(self.request_delay)
            out[u.lstrip("@")] = self.fetch_recent_tweets(u, hours)
        return out

    def _get_with_retry(self, params: dict, max_retries: int = 4) -> dict:
        """GET advanced_search, backing off on 429 rate-limit responses."""
        url = f"{BASE_URL}{ADVANCED_SEARCH_PATH}"
        for attempt in range(max_retries + 1):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 429 and attempt < max_retries:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s
                continue
            if resp.status_code >= 400:
                raise TwitterApiError(
                    f"twitterapi.io {resp.status_code}: {resp.text[:200]}"
                )
            return resp.json()
        raise TwitterApiError("twitterapi.io: exhausted retries on 429")

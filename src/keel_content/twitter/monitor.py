"""Job 1 (fetch) — pull recent tweets for the active watchlist into staging.

Reads the ``TwitterSource`` watchlist, fetches each account's last-N-hours tweets
via :mod:`.client`, and upserts them as ``TweetCandidate`` rows (dedup on
``tweet_id``). Stores nothing beyond the staging row; triage is a separate stage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from keel_content.models import TweetCandidate, TwitterSource

from .client import Tweet, TwitterClient, resolve_api_key

logger = logging.getLogger(__name__)

# Twitter's classic createdAt format, e.g. "Mon Jul 20 10:14:25 +0000 2026".
_CREATED_AT_FMT = "%a %b %d %H:%M:%S %z %Y"


def _parse_created_at(value: str):
    try:
        return datetime.strptime(value, _CREATED_AT_FMT)
    except (ValueError, TypeError):
        # Fall back to "now" so a malformed timestamp never drops a tweet.
        return dj_timezone.now().astimezone(timezone.utc)


def fetch_and_store(
    *, hours: int = 24, usernames: list[str] | None = None, api_key: str | None = None
) -> dict:
    """Fetch + stage recent tweets. Returns a small stats dict."""
    if usernames:
        sources = list(
            TwitterSource.objects.filter(username__in=[u.lstrip("@") for u in usernames])
        )
    else:
        sources = list(TwitterSource.objects.filter(is_active=True))

    if not sources:
        return {"sources": 0, "fetched": 0, "new": 0, "skipped": 0}

    client = TwitterClient(api_key=resolve_api_key(api_key))
    stats = {"sources": len(sources), "fetched": 0, "new": 0, "skipped": 0}

    for source in sources:
        tweets: list[Tweet] = client.fetch_recent_tweets(source.username, hours=hours)
        stats["fetched"] += len(tweets)
        for tw in tweets:
            if not tw.id:
                continue
            _plan, created = TweetCandidate.objects.get_or_create(
                tweet_id=tw.id,
                defaults={
                    "source": source,
                    "author_username": source.username,
                    "text": tw.text,
                    "tweet_url": tw.url,
                    "tweet_created_at": _parse_created_at(tw.created_at),
                    "like_count": tw.like_count,
                    "retweet_count": tw.retweet_count,
                    "reply_count": tw.reply_count,
                    "view_count": tw.view_count,
                },
            )
            stats["new" if created else "skipped"] += 1

    logger.info("twitter.monitor fetched=%(fetched)s new=%(new)s", stats)
    return stats

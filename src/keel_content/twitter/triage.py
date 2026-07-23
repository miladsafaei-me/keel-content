"""Job 1 (quality gate) — score, classify, and route each fetched tweet.

Two layers, cheap-first (mirrors the reconcile normalize→adjudicate ethos):

1. **Deterministic pre-filter** — drops obvious noise (self-promo, below the
   view floor) with zero LLM cost.
2. **LLM classify** — the survivors go to a batched classifier that judges market
   relevance, evergreen-vs-ephemeral, a 0..1 quality score, and the destination
   route (embed / idea / both / discard). The model only PROPOSES a route; caps
   and matching are enforced downstream in code.
"""

from __future__ import annotations

import json
import logging

from keel_content import host
from keel_content.core.claude_client import ClaudeClient
from keel_content.models import TweetCandidate

from . import constants as C

logger = logging.getLogger(__name__)

Market = host.market_model()

_VALID_ROUTES = {
    TweetCandidate.Route.EMBED,
    TweetCandidate.Route.IDEA,
    TweetCandidate.Route.BOTH,
    TweetCandidate.Route.DISCARD,
}

_SYSTEM = """You are the quality gate for a finance/markets education blog. You \
triage tweets from the accounts on the project's watchlist for two downstream uses:

- EMBED: a self-contained, quotable data point / stat / chart-worthy fact that \
would enrich an EXISTING article as a supporting "related from X" card.
- IDEA: a tweet that opens a user QUESTION or PROBLEM worth a whole new article.

For each tweet decide:
- markets: which of these market slugs it is genuinely relevant to (subset, may \
be empty): {markets}. Only include a market if the tweet is really about it.
- evergreen: true if the point stays useful for months; false if it is breaking/ \
ephemeral news that dates quickly.
- quality: 0..1 — substance, credibility, usefulness to a trader audience.
- route: one of "embed", "idea", "both", "discard".
  * "discard" anything off-topic (sports, politics, human-interest), pure house \
ads, or low-substance chatter — even from a finance account.
  * "embed" a solid standalone fact/stat that supports existing content.
  * "idea" a genuine question/problem/theme for a new article.
  * "both" when it works as a supporting card AND could seed an article.
- reason: one short clause.

Return ONLY a JSON array, one object per input tweet, each:
{"tweet_id": "...", "markets": [...], "evergreen": true|false, \
"quality": 0.0, "route": "embed|idea|both|discard", "reason": "..."}"""


def _deterministic_discard(cand: TweetCandidate) -> str | None:
    """Return a discard reason if the tweet is obvious noise, else None."""
    lowered = cand.text.lower()
    if any(marker in lowered for marker in C.PROMO_MARKERS):
        return "self-promo / house ad"
    if C.MIN_VIEW_COUNT and cand.view_count < C.MIN_VIEW_COUNT:
        return f"below view floor ({cand.view_count} < {C.MIN_VIEW_COUNT})"
    return None


def _build_user_payload(batch: list[TweetCandidate]) -> str:
    rows = [
        {
            "tweet_id": c.tweet_id,
            "author": c.author_username,
            "text": c.text,
            "likes": c.like_count,
            "retweets": c.retweet_count,
            "views": c.view_count,
        }
        for c in batch
    ]
    return "Triage these tweets:\n" + json.dumps(rows, ensure_ascii=False, indent=2)


def _classify_batch(batch: list[TweetCandidate], market_slugs: list[str]) -> dict[str, dict]:
    client = ClaudeClient()
    system = _SYSTEM.replace("{markets}", ", ".join(market_slugs) or "(none seeded)")
    reply = client.call(
        step="twitter_triage",
        model=C.TRIAGE_MODEL,
        max_tokens=4000,
        system_text=system,
        user_text=_build_user_payload(batch),
        expect_json=True,
    )
    out: dict[str, dict] = {}
    for item in reply.json or []:
        if isinstance(item, dict) and item.get("tweet_id"):
            out[str(item["tweet_id"])] = item
    return out


def triage_pending(*, batch_size: int = 40, limit: int | None = None) -> dict:
    """Triage all FETCHED candidates. Returns a stats dict."""
    qs = TweetCandidate.objects.filter(status=TweetCandidate.Status.FETCHED).order_by(
        "tweet_created_at"
    )
    if limit:
        qs = qs[:limit]
    pending = list(qs)
    stats = {"seen": len(pending), "discarded": 0, "embed": 0, "idea": 0, "both": 0}
    if not pending:
        return stats

    market_slugs = list(Market.objects.values_list("slug", flat=True))

    # Layer 1 — deterministic discards.
    survivors: list[TweetCandidate] = []
    for cand in pending:
        reason = _deterministic_discard(cand)
        if reason:
            cand.route = TweetCandidate.Route.DISCARD
            cand.status = TweetCandidate.Status.DISCARDED
            cand.quality_score = 0.0
            cand.triage_reason = reason
            cand.save(update_fields=["route", "status", "quality_score", "triage_reason", "updated_at"])
            stats["discarded"] += 1
        else:
            survivors.append(cand)

    # Layer 2 — LLM classify, in batches.
    for start in range(0, len(survivors), batch_size):
        batch = survivors[start : start + batch_size]
        try:
            verdicts = _classify_batch(batch, market_slugs)
        except Exception:  # noqa: BLE001 -- a batch failure must not crash the run
            logger.exception("twitter.triage: batch classify failed; leaving batch FETCHED")
            continue

        valid_markets = set(market_slugs)
        for cand in batch:
            v = verdicts.get(cand.tweet_id)
            if not v:
                # Model dropped it — leave FETCHED so a re-run retries.
                continue
            route = str(v.get("route", "")).strip().lower()
            if route not in _VALID_ROUTES:
                route = TweetCandidate.Route.DISCARD
            cand.route = route
            cand.quality_score = _clamp01(v.get("quality"))
            cand.is_evergreen = bool(v.get("evergreen"))
            cand.markets = [m for m in (v.get("markets") or []) if m in valid_markets]
            cand.triage_reason = str(v.get("reason", ""))[:500]
            cand.status = (
                TweetCandidate.Status.DISCARDED
                if route == TweetCandidate.Route.DISCARD
                else TweetCandidate.Status.SCORED
            )
            cand.save()
            if route == TweetCandidate.Route.DISCARD:
                stats["discarded"] += 1
            else:
                stats[route] += 1

    logger.info("twitter.triage %s", stats)
    return stats


def _clamp01(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

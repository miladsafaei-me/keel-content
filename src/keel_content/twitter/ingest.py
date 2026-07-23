"""Job 2 (idea sink) — turn IDEA/BOTH tweets into ContentPlan rows.

A tweet rarely IS a whole article; it is a seed. The LLM drafts a one-line user
NEED + a working title/entity for each idea tweet, and the row is upserted via
the SHARED :func:`upsert_content_plan_spec` with ``source_type=twitter``. From
there it lands as ``planned`` and must pass the SAME reconcile / anti-
cannibalization gate as every other route — so a tweet idea can never cannibalize
an existing article; reconcile decides "new spoke" vs "merge into an existing
plan row".
"""

from __future__ import annotations

import json
import logging

from keel_content import host
from keel_content.adapters import get_adapter

# Resolve the configured publisher adapter (default: the reference SignalBots adapter).
upsert_content_plan_spec = get_adapter().upsert_content_plan_spec
from keel_content.core.claude_client import ClaudeClient
from keel_content.models import TweetCandidate

from . import constants as C

logger = logging.getLogger(__name__)

ContentPlan = host.content_plan_model()
Market = host.market_model()

_SYSTEM = """You turn a finance tweet into a blog ARTICLE IDEA spec for a finance/ \
markets education site. The tweet is a \
SEED, not the article. Draft the user-need-first angle a full evergreen guide would \
answer — never just restate the tweet or its breaking news.

For each tweet return:
- title: a working article title (a durable how/what/why guide, not a headline).
- h1: same or a close on-page variant.
- intent: ONE sentence naming the reader NEED the article satisfies.
- intent_frame: a short frame label (e.g. "how-to", "explainer", "comparison", \
"analysis").
- entity: the core subject entity (<=6 words).
- markets: subset of these market slugs the article targets: {markets}.

Return ONLY a JSON array, one object per input tweet:
{"tweet_id": "...", "title": "...", "h1": "...", "intent": "...", \
"intent_frame": "...", "entity": "...", "markets": [...]}"""


def _idea_candidates(limit: int | None) -> list[TweetCandidate]:
    qs = (
        TweetCandidate.objects.filter(
            route__in=[TweetCandidate.Route.IDEA, TweetCandidate.Route.BOTH],
            content_plan__isnull=True,
        )
        .exclude(status=TweetCandidate.Status.DISCARDED)
        .order_by("-quality_score", "-tweet_created_at")
    )
    if limit:
        qs = qs[:limit]
    return list(qs)


def _draft_specs(batch: list[TweetCandidate], market_slugs: list[str]) -> dict[str, dict]:
    client = ClaudeClient()
    system = _SYSTEM.replace("{markets}", ", ".join(market_slugs) or "(none seeded)")
    rows = [{"tweet_id": c.tweet_id, "author": c.author_username, "text": c.text} for c in batch]
    reply = client.call(
        step="twitter_idea_spec",
        model=C.REASONING_MODEL,
        max_tokens=4000,
        system_text=system,
        user_text="Draft idea specs for:\n" + json.dumps(rows, ensure_ascii=False, indent=2),
        expect_json=True,
    )
    out: dict[str, dict] = {}
    for item in reply.json or []:
        if isinstance(item, dict) and item.get("tweet_id"):
            out[str(item["tweet_id"])] = item
    return out


def ingest_ideas(*, batch_size: int = 20, limit: int | None = None, dry_run: bool = False) -> dict:
    """Push IDEA/BOTH tweets into the ContentPlan roadmap. Returns stats."""
    candidates = _idea_candidates(limit)
    stats = {"seen": len(candidates), "created": 0, "updated": 0, "skipped": 0}
    if not candidates:
        return stats

    valid_markets = set(Market.objects.values_list("slug", flat=True))
    market_slugs = list(valid_markets)

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        try:
            specs = _draft_specs(batch, market_slugs)
        except Exception:  # noqa: BLE001 -- a batch failure must not crash the run
            logger.exception("twitter.ingest: idea-spec draft failed for a batch")
            continue

        for cand in batch:
            spec = specs.get(cand.tweet_id)
            if not spec or not (spec.get("title") or "").strip():
                stats["skipped"] += 1
                continue
            spec = {
                "title": spec["title"],
                "h1": spec.get("h1") or spec["title"],
                "intent": spec.get("intent") or "",
                "intent_frame": spec.get("intent_frame") or "",
                "entity": spec.get("entity") or "",
                "role": "spoke",
                "target": "blog",
                "markets": [m for m in (spec.get("markets") or []) if m in valid_markets] or cand.markets,
            }
            if dry_run:
                stats["skipped"] += 1
                continue

            plan, outcome = upsert_content_plan_spec(
                spec,
                source_type=ContentPlan.Source.TWITTER.value,
                source_ref=cand.tweet_url[:500],
            )
            if plan is None:
                stats["skipped"] += 1
                continue
            cand.content_plan = plan
            # Pure-idea rows advance to PLANNED; BOTH rows keep their embed status.
            if cand.route == TweetCandidate.Route.IDEA:
                cand.status = TweetCandidate.Status.PLANNED
            cand.save(update_fields=["content_plan", "status", "updated_at"])
            stats["created" if outcome == "created" else "updated" if outcome == "updated" else "skipped"] += 1

    logger.info("twitter.ingest %s", stats)
    return stats

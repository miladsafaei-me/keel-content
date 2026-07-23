"""Job 3 (embed sink) — attach EMBED/BOTH tweets to a genuinely related post.

The matching direction is REVERSED on purpose: existing content is the anchor,
not the tweet. A tweet only embeds when it truly complements an existing
published post's DECLARED intent + brief (never a surface-topic guess) — the same
principle the internal-linker uses. Two guards keep it from becoming patchwork:

- **Intent gate:** below :data:`MIN_EMBED_RELEVANCE` the tweet has no real home,
  so it is rerouted to the idea sink (a content-gap signal), not force-fitted.
- **Per-post cap + rolling window:** at most :data:`TWEETS_PER_POST_CAP` active
  tweets per post, enforced in code. A better-matching tweet evicts the weakest;
  surplus that can't beat the incumbents is dropped. The LLM never controls the
  cap — it only proposes the match + relevance.
"""

from __future__ import annotations

import json
import logging
import re

from keel_content import host
from keel_content.core.claude_client import ClaudeClient
from keel_content.models import TweetCandidate

from . import constants as C

logger = logging.getLogger(__name__)

Post = host.post_model()

_WORD_RE = re.compile(r"[a-z0-9]{4,}")
_STOP = {
    "this", "that", "with", "from", "have", "will", "your", "about", "into",
    "than", "then", "they", "them", "just", "over", "more", "most", "been",
    "what", "when", "which", "there", "their", "would", "could", "these",
    "those", "https", "amp",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def _post_market_slugs(post: Post) -> set[str]:
    plan = getattr(post, "content_plan", None)
    if plan is None:
        return set()
    return {m.slug for m in plan.markets.all()}


def _post_intent(post: Post) -> str:
    plan = getattr(post, "content_plan", None)
    if plan is None:
        return ""
    brief = plan.brief if isinstance(plan.brief, dict) else {}
    return " ".join(
        str(x) for x in (plan.intent, brief.get("intent"), brief.get("intent_statement")) if x
    )


def _published_posts() -> list[Post]:
    return list(
        Post.objects.filter(status=Post.Status.PUBLISHED, is_deleted=False)
        .select_related("content_plan")
        .prefetch_related("content_plan__markets")
    )


def _shortlist(cand: TweetCandidate, posts: list[Post], k: int = 6) -> list[Post]:
    """Cheap lexical + market pre-rank; the LLM makes the final call over top-k."""
    tw_tokens = _tokens(cand.text)
    tw_markets = set(cand.markets or [])
    scored: list[tuple[float, Post]] = []
    for post in posts:
        overlap = len(tw_tokens & _tokens(f"{post.title} {post.excerpt} {_post_intent(post)}"))
        market_boost = 2.0 if (tw_markets & _post_market_slugs(post)) else 0.0
        score = overlap + market_boost
        if score > 0:
            scored.append((score, post))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [p for _s, p in scored[:k]]


def _match(cand: TweetCandidate, shortlist: list[Post]) -> dict | None:
    """LLM picks the best-fitting post (or none) from the shortlist."""
    client = ClaudeClient()
    posts_payload = [
        {"slug": p.slug, "title": p.title, "intent": _post_intent(p) or p.excerpt[:200]}
        for p in shortlist
    ]
    system = (
        "You decide whether a finance tweet genuinely COMPLEMENTS one of a list of "
        "existing blog posts, to embed as a supporting 'related from X' card. Match "
        "on the post's declared INTENT — what reader need it serves — not on shared "
        "surface words. Only match if a reader of that post would find the tweet a "
        "relevant, on-topic supporting data point. If none fit well, return null.\n\n"
        'Return ONLY JSON: {"post_slug": "<slug>"|null, "relevance": 0.0, '
        '"note": "<one clause on why it complements that post>"}'
    )
    user = (
        f"TWEET (@{cand.author_username}): {cand.text}\n\n"
        f"CANDIDATE POSTS:\n{json.dumps(posts_payload, ensure_ascii=False, indent=2)}"
    )
    reply = client.call(
        step="twitter_embed_match",
        model=C.REASONING_MODEL,
        max_tokens=600,
        system_text=system,
        user_text=user,
        expect_json=True,
    )
    return reply.json if isinstance(reply.json, dict) else None


def _attach_or_evict(cand: TweetCandidate, post: Post, relevance: float, note: str) -> str:
    """Enforce the per-post cap with a rolling window. Returns an outcome string."""
    active = list(
        TweetCandidate.objects.filter(
            linked_post=post, status=TweetCandidate.Status.EMBEDDED
        ).order_by("embed_rank")
    )
    if len(active) < C.TWEETS_PER_POST_CAP:
        _do_attach(cand, post, relevance, note)
        return "embedded"

    weakest = active[0]
    if relevance > (weakest.embed_rank or 0.0):
        weakest.status = TweetCandidate.Status.EVICTED
        weakest.linked_post = None
        weakest.save(update_fields=["status", "linked_post", "updated_at"])
        _do_attach(cand, post, relevance, note)
        return "evicted-weakest"

    # Surplus: post is full of stronger tweets — drop rather than flood.
    cand.status = TweetCandidate.Status.DISCARDED
    cand.triage_reason = (cand.triage_reason + " | surplus: post embed cap full").strip(" |")[:500]
    cand.save(update_fields=["status", "triage_reason", "updated_at"])
    return "surplus-dropped"


def _do_attach(cand: TweetCandidate, post: Post, relevance: float, note: str) -> None:
    cand.linked_post = post
    cand.embed_rank = relevance
    cand.embed_note = (note or "")[:500]
    cand.status = TweetCandidate.Status.EMBEDDED
    cand.save(update_fields=["linked_post", "embed_rank", "embed_note", "status", "updated_at"])


def _reroute_to_idea(cand: TweetCandidate, reason: str) -> None:
    """No good home → treat as a content-gap idea seed (ingest picks it up)."""
    cand.route = TweetCandidate.Route.IDEA
    cand.triage_reason = (cand.triage_reason + f" | {reason}").strip(" |")[:500]
    cand.save(update_fields=["route", "triage_reason", "updated_at"])


def embed_pending(*, limit: int | None = None, dry_run: bool = False) -> dict:
    """Match EMBED/BOTH tweets to posts. Returns stats."""
    qs = (
        TweetCandidate.objects.filter(
            route__in=[TweetCandidate.Route.EMBED, TweetCandidate.Route.BOTH],
            status=TweetCandidate.Status.SCORED,
            linked_post__isnull=True,
        )
        .order_by("-quality_score", "-tweet_created_at")
    )
    if limit:
        qs = qs[:limit]
    pending = list(qs)
    stats = {"seen": len(pending), "embedded": 0, "evicted": 0, "surplus": 0, "rerouted": 0, "nomatch": 0}
    if not pending:
        return stats

    posts = _published_posts()
    if not posts:
        return stats

    for cand in pending:
        shortlist = _shortlist(cand, posts)
        if not shortlist:
            _handle_no_home(cand, stats, dry_run)
            continue
        try:
            verdict = _match(cand, shortlist)
        except Exception:  # noqa: BLE001 -- a match failure must not crash the run
            logger.exception("twitter.embed: match failed for tweet %s", cand.tweet_id)
            continue

        slug = (verdict or {}).get("post_slug")
        relevance = _clamp01((verdict or {}).get("relevance"))
        if not slug or relevance < C.MIN_EMBED_RELEVANCE:
            _handle_no_home(cand, stats, dry_run)
            continue

        post = next((p for p in shortlist if p.slug == slug), None)
        if post is None:
            _handle_no_home(cand, stats, dry_run)
            continue
        if dry_run:
            stats["embedded"] += 1
            continue

        outcome = _attach_or_evict(cand, post, relevance, (verdict or {}).get("note", ""))
        if outcome == "embedded":
            stats["embedded"] += 1
        elif outcome == "evicted-weakest":
            stats["embedded"] += 1
            stats["evicted"] += 1
        else:
            stats["surplus"] += 1

    logger.info("twitter.embed %s", stats)
    return stats


def _handle_no_home(cand: TweetCandidate, stats: dict, dry_run: bool) -> None:
    if cand.route == TweetCandidate.Route.EMBED:
        if not dry_run:
            _reroute_to_idea(cand, "no related post → content-gap idea")
        stats["rerouted"] += 1
    else:  # BOTH already gets an idea via the ingest stage; just record no embed.
        stats["nomatch"] += 1


def _clamp01(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

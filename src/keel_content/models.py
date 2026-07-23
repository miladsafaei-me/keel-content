"""Twitter/X intake models — the staging spine for the Twitter Content-Pipeline route.

Twitter is a fourth intake route (alongside top-pages, keyword-clustering, and
YouTube-transcript). A tweet enters as a :class:`TweetCandidate`, passes the
quality gate (triage), and forks into one of two sinks:

- **Idea** → an :class:`~blog.models.ContentPlan` row (``source_type=twitter``)
  that runs the SAME reconcile/anti-cannibalization gate as every other route.
- **Embed** → attached to an existing published :class:`~blog.models.Post` and
  rendered as a self-hosted "Related from X" card (no external widget JS).

``TweetCandidate`` is the dedup + state spine: one row per tweet (unique
``tweet_id``), so a tweet is never re-processed and the per-post embed cap is
enforceable in code, never trusted to the LLM.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

# The content-queue and article models live in the host CMS (keel-cms in a Keel
# stack, or the host's own ``blog`` app). keel-content references them as swappable
# targets so it never hard-couples to one app label; a host overrides these settings
# to point at ``keel_cms.ContentPlan`` / ``keel_cms.Post`` (or its own models).
CONTENT_PLAN_MODEL = getattr(settings, "KEEL_CONTENT_CONTENT_PLAN_MODEL", "blog.ContentPlan")
POST_MODEL = getattr(settings, "KEEL_CONTENT_POST_MODEL", "blog.Post")


class TwitterSource(models.Model):
    """A monitored X/Twitter account. The watchlist the monitor pulls from."""

    username = models.CharField(
        max_length=100,
        unique=True,
        help_text="Handle without the leading @ (e.g. 'KobeissiLetter').",
    )
    display_name = models.CharField(max_length=200, blank=True, default="")
    market_focus = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Free-text note on which markets this account is useful for.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Only active sources are pulled by the monitor.",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_pipeline_twitter_source"
        ordering = ["username"]
        verbose_name = "Twitter source"
        verbose_name_plural = "Twitter sources"

    def __str__(self) -> str:
        return f"@{self.username}"


class TweetCandidate(models.Model):
    """One extracted tweet + its triage verdict + its destination link.

    The whole Twitter funnel is queryable from this one table: what was fetched,
    what survived the quality gate, which route it took, and which Post it landed
    on (embed) or which ContentPlan row it seeded (idea).
    """

    class Route(models.TextChoices):
        UNCLASSIFIED = "unclassified", "Not yet triaged"
        DISCARD = "discard", "Discard (low value / off-topic)"
        EMBED = "embed", "Embed in an existing post"
        IDEA = "idea", "Seed a new ContentPlan idea"
        BOTH = "both", "Embed candidate AND idea seed"

    class Status(models.TextChoices):
        FETCHED = "fetched", "Fetched (raw, not triaged)"
        SCORED = "scored", "Scored (route assigned)"
        EMBEDDED = "embedded", "Embedded in a post"
        PLANNED = "planned", "Pushed to ContentPlan as an idea"
        DISCARDED = "discarded", "Discarded"
        EVICTED = "evicted", "Was embedded, displaced by a better tweet"

    tweet_id = models.CharField(
        max_length=40,
        unique=True,
        help_text="The X status id — the dedup spine; a tweet is processed once.",
    )
    source = models.ForeignKey(
        TwitterSource,
        on_delete=models.CASCADE,
        related_name="tweets",
    )
    author_username = models.CharField(max_length=100)
    text = models.TextField()
    tweet_url = models.URLField(max_length=500)
    tweet_created_at = models.DateTimeField(db_index=True)

    like_count = models.PositiveIntegerField(default=0)
    retweet_count = models.PositiveIntegerField(default=0)
    reply_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)

    # --- Triage (job 1) outputs ---
    quality_score = models.FloatField(
        null=True,
        blank=True,
        help_text="0..1 quality/relevance score from the triage stage.",
    )
    route = models.CharField(
        max_length=16,
        choices=Route.choices,
        default=Route.UNCLASSIFIED,
        db_index=True,
    )
    markets = models.JSONField(
        default=list,
        blank=True,
        help_text="Market slugs the triage stage judged this tweet relevant to.",
    )
    is_evergreen = models.BooleanField(default=False)
    triage_reason = models.TextField(blank=True, default="")

    # --- Idea sink (job 2) ---
    content_plan = models.ForeignKey(
        CONTENT_PLAN_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_tweets",
        help_text="The ContentPlan row this tweet seeded (idea route).",
    )

    # --- Embed sink (job 3) ---
    linked_post = models.ForeignKey(
        POST_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="related_tweets",
        help_text="The published Post this tweet is embedded in (embed route).",
    )
    embed_rank = models.FloatField(
        null=True,
        blank=True,
        help_text="Relevance of this tweet to linked_post; the rolling-window "
        "eviction key (a better-matching tweet displaces the weakest).",
    )
    embed_note = models.TextField(
        blank=True,
        default="",
        help_text="Short reason this tweet complements linked_post (from the matcher).",
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.FETCHED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_pipeline_tweet_candidate"
        ordering = ["-tweet_created_at"]
        verbose_name = "Tweet candidate"
        verbose_name_plural = "Tweet candidates"
        indexes = [
            models.Index(fields=["status", "route"]),
            models.Index(fields=["linked_post", "status"]),
        ]

    def __str__(self) -> str:
        return f"@{self.author_username}: {self.text[:60]}"

    @property
    def display_text(self) -> str:
        """Tweet text cleaned for card display — t.co / trailing media links removed."""
        import re

        text = re.sub(r"https?://t\.co/\S+", "", self.text)
        return re.sub(r"[ \t]+\n", "\n", text).strip()

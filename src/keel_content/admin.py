"""Admin for the Twitter/X intake route.

These two models expose the Twitter watchlist and the tweet staging table so the
funnel is inspectable (what was fetched, how it was routed, where it landed).

The admin base class prefers ``unfold.admin.ModelAdmin`` when django-unfold is
installed (the theme most Keel hosts use) and falls back to Django's stock
``admin.ModelAdmin`` otherwise, so this module never hard-requires unfold.
"""

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin
except Exception:
    from django.contrib.admin import ModelAdmin

from .models import TweetCandidate, TwitterSource


@admin.register(TwitterSource)
class TwitterSourceAdmin(ModelAdmin):
    list_display = ("username", "display_name", "market_focus", "is_active")
    list_filter = ("is_active",)
    search_fields = ("username", "display_name")
    list_editable = ("is_active",)


@admin.register(TweetCandidate)
class TweetCandidateAdmin(ModelAdmin):
    list_display = (
        "author_username",
        "short_text",
        "route",
        "status",
        "quality_score",
        "linked_post",
        "tweet_created_at",
    )
    list_filter = ("status", "route", "is_evergreen", "source")
    search_fields = ("text", "author_username", "tweet_id")
    readonly_fields = (
        "tweet_id",
        "source",
        "author_username",
        "text",
        "tweet_url",
        "tweet_created_at",
        "like_count",
        "retweet_count",
        "reply_count",
        "view_count",
        "created_at",
        "updated_at",
    )
    raw_id_fields = ("content_plan", "linked_post")
    date_hierarchy = "tweet_created_at"

    @admin.display(description="Tweet")
    def short_text(self, obj):
        return obj.text[:70]

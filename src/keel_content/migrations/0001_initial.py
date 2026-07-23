"""Initial schema for keel-content's own tables: the Twitter/X intake spine.

keel-content owns only the Twitter intake models (``TwitterSource`` +
``TweetCandidate``). The content-queue and article models it references
(``content_plan`` / ``linked_post``) live in the host CMS and are reached as
swappable targets, so this migration depends on whichever apps the host points
``KEEL_CONTENT_CONTENT_PLAN_MODEL`` / ``KEEL_CONTENT_POST_MODEL`` at.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

CONTENT_PLAN_MODEL = getattr(settings, "KEEL_CONTENT_CONTENT_PLAN_MODEL", "blog.ContentPlan")
POST_MODEL = getattr(settings, "KEEL_CONTENT_POST_MODEL", "blog.Post")


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(CONTENT_PLAN_MODEL),
        migrations.swappable_dependency(POST_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TwitterSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(help_text="Handle without the leading @ (e.g. 'KobeissiLetter').", max_length=100, unique=True)),
                ("display_name", models.CharField(blank=True, default="", max_length=200)),
                ("market_focus", models.CharField(blank=True, default="", help_text="Free-text note on which markets this account is useful for.", max_length=200)),
                ("is_active", models.BooleanField(db_index=True, default=True, help_text="Only active sources are pulled by the monitor.")),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Twitter source",
                "verbose_name_plural": "Twitter sources",
                "db_table": "content_pipeline_twitter_source",
                "ordering": ["username"],
            },
        ),
        migrations.CreateModel(
            name="TweetCandidate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tweet_id", models.CharField(help_text="The X status id — the dedup spine; a tweet is processed once.", max_length=40, unique=True)),
                ("author_username", models.CharField(max_length=100)),
                ("text", models.TextField()),
                ("tweet_url", models.URLField(max_length=500)),
                ("tweet_created_at", models.DateTimeField(db_index=True)),
                ("like_count", models.PositiveIntegerField(default=0)),
                ("retweet_count", models.PositiveIntegerField(default=0)),
                ("reply_count", models.PositiveIntegerField(default=0)),
                ("view_count", models.PositiveIntegerField(default=0)),
                ("quality_score", models.FloatField(blank=True, help_text="0..1 quality/relevance score from the triage stage.", null=True)),
                ("route", models.CharField(choices=[("unclassified", "Not yet triaged"), ("discard", "Discard (low value / off-topic)"), ("embed", "Embed in an existing post"), ("idea", "Seed a new ContentPlan idea"), ("both", "Embed candidate AND idea seed")], db_index=True, default="unclassified", max_length=16)),
                ("markets", models.JSONField(blank=True, default=list, help_text="Market slugs the triage stage judged this tweet relevant to.")),
                ("is_evergreen", models.BooleanField(default=False)),
                ("triage_reason", models.TextField(blank=True, default="")),
                ("embed_rank", models.FloatField(blank=True, help_text="Relevance of this tweet to linked_post; the rolling-window eviction key (a better-matching tweet displaces the weakest).", null=True)),
                ("embed_note", models.TextField(blank=True, default="", help_text="Short reason this tweet complements linked_post (from the matcher).")),
                ("status", models.CharField(choices=[("fetched", "Fetched (raw, not triaged)"), ("scored", "Scored (route assigned)"), ("embedded", "Embedded in a post"), ("planned", "Pushed to ContentPlan as an idea"), ("discarded", "Discarded"), ("evicted", "Was embedded, displaced by a better tweet")], db_index=True, default="fetched", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("content_plan", models.ForeignKey(blank=True, help_text="The ContentPlan row this tweet seeded (idea route).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="source_tweets", to=CONTENT_PLAN_MODEL)),
                ("linked_post", models.ForeignKey(blank=True, help_text="The published Post this tweet is embedded in (embed route).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="related_tweets", to=POST_MODEL)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tweets", to="keel_content.twittersource")),
            ],
            options={
                "verbose_name": "Tweet candidate",
                "verbose_name_plural": "Tweet candidates",
                "db_table": "content_pipeline_tweet_candidate",
                "ordering": ["-tweet_created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="tweetcandidate",
            index=models.Index(fields=["status", "route"], name="content_pip_status_route_idx"),
        ),
        migrations.AddIndex(
            model_name="tweetcandidate",
            index=models.Index(fields=["linked_post", "status"], name="content_pip_linked_status_idx"),
        ),
    ]

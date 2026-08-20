"""Create keel-content's own two tables on a host that does not already have them.

``0001_initial`` is deliberately state-only: it ADOPTS the ``content_pipeline_*``
tables a SignalBots-shaped host already owns, so no DDL runs and the deploy
``migrate`` can never fail with "table already exists". Its docstring notes that
"a genuinely fresh project seeds these two tables out-of-band" — but the package
shipped no way to do that, so a fresh adopter ended up with two models and no
tables. Nothing surfaces it until something cascades through
``TweetCandidate.linked_post`` (deleting a Post does), which then dies with
``relation "content_pipeline_tweet_candidate" does not exist``.

This migration closes that: it introspects the live connection and creates each
table only when it is missing. On a host that adopted existing tables it is a
no-op, so it stays safe for the adoption path 0001 was written for.

Hit on Binary Option Trading's adoption, 2026-08-21.
"""

from django.db import migrations


def _create_missing_tables(apps, schema_editor):
    existing = set(schema_editor.connection.introspection.table_names())
    for model_name in ("TwitterSource", "TweetCandidate"):
        model = apps.get_model("keel_content", model_name)
        if model._meta.db_table not in existing:
            schema_editor.create_model(model)


def _noop_reverse(apps, schema_editor):
    """Reversing does NOT drop the tables — they may hold a host's real data."""


class Migration(migrations.Migration):

    dependencies = [("keel_content", "0001_initial")]

    operations = [migrations.RunPython(_create_missing_tables, _noop_reverse)]

"""``./manage.py contentplan_backfill`` — seed ContentPlan rows from existing Posts.

Makes the roadmap (``blog.ContentPlan``) reflect content that already exists, so the
production queue never re-plans a page that is already produced/published and the
intent registry can dedup future plans against shipped content. The plan rows are
back-filled as ``source_type=manual`` (we cannot know the original planning path) and
their ``canonical_key`` is left blank — honoring the registry's "not seeded from
published content" rule (a future reconcile pass keys them lazily if it touches them).

Also links QUEUED GLOSSARY-TERM rows (``target=glossary_term``) to their live
``Tag`` once the term's data migration has run: the persist step flips the row to
``drafted`` before the Tag exists, so this is where ``produced_term`` gets set —
run it (on prod) after a deploy that shipped new terms.

Idempotent: an existing plan row is left alone unless ``--resync`` is passed (which
refreshes its status + facets from the live Post). A standard step — safe to run
anytime; a no-op when every Post already has a plan row.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from keel_content import host

ContentPlan = host.content_plan_model()
Post = host.post_model()
Tag = host.tag_model()


def _role_for(post: Post) -> str:
    cluster = post.topic_cluster
    if cluster is None:
        return ""
    if cluster.pillar_id == post.pk:
        return ContentPlan.Role.PILLAR
    return ContentPlan.Role.SPOKE


def _status_for(post: Post) -> str:
    if post.status == Post.Status.PUBLISHED:
        return ContentPlan.Status.PUBLISHED
    # draft / archived: produced but not live -> drafted (it IS produced).
    return ContentPlan.Status.DRAFTED


def _apply_post_facets(plan: ContentPlan, post: Post) -> None:
    """Mirror a Post's facets + production state onto its plan row."""
    plan.topic_cluster = post.topic_cluster
    plan.role = _role_for(post)
    plan.status = _status_for(post)
    plan.produced_post = post
    plan.save()
    plan.categories.set(post.categories.all())
    plan.markets.set(post.markets.all())
    plan.audience_roles.set(post.audience_roles.all())
    plan.audience_levels.set(post.audience_levels.all())
    plan.glossary_terms.set(post.related_terms.all())


class Command(BaseCommand):
    help = "Seed/refresh ContentPlan rows from existing blog Posts (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--resync",
            action="store_true",
            help="Update existing plan rows' status + facets from the live Post.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing to the DB.",
        )

    def handle(self, *args, **opts):
        resync = opts["resync"]
        dry = opts["dry_run"]
        created = updated = skipped = 0

        posts = (
            Post.objects.all()
            .select_related("topic_cluster")
            .prefetch_related(
                "categories", "markets", "audience_roles", "audience_levels", "related_terms"
            )
        )
        for post in posts:
            plan = ContentPlan.objects.filter(slug=post.slug).first()
            if plan is None:
                if dry:
                    self.stdout.write(f"  ~ would create {post.slug}")
                    created += 1
                    continue
                plan = ContentPlan(
                    slug=post.slug,
                    title=post.title,
                    h1=post.h1 or "",
                    target=ContentPlan.Target.BLOG,
                    source_type=ContentPlan.Source.MANUAL,
                )
                _apply_post_facets(plan, post)
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + create {post.slug}"))
            elif resync:
                if dry:
                    self.stdout.write(f"  ~ would resync {post.slug}")
                    updated += 1
                    continue
                _apply_post_facets(plan, post)
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"  * resync {post.slug}"))
            else:
                skipped += 1

        linked = self._link_produced_terms(dry)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {created} created, {updated} resynced, {skipped} skipped "
                f"(of {len(posts)} live post(s)); {linked} term row(s) linked to "
                "their live Tag"
            )
        )

    def _link_produced_terms(self, dry: bool) -> int:
        """Attach ``produced_term`` to glossary_term rows whose Tag now exists."""
        linked = 0
        rows = ContentPlan.objects.filter(
            target=ContentPlan.Target.GLOSSARY_TERM, produced_term__isnull=True
        ).exclude(status=ContentPlan.Status.REJECTED)
        for plan in rows:
            tag = Tag.objects.filter(is_term=True, slug=slugify(plan.title)).first()
            if tag is None:
                continue
            if dry:
                self.stdout.write(f"  ~ would link term row {plan.slug} -> {tag.slug}")
                linked += 1
                continue
            plan.produced_term = tag
            if plan.status not in (
                ContentPlan.Status.DRAFTED,
                ContentPlan.Status.PUBLISHED,
            ):
                plan.status = ContentPlan.Status.DRAFTED
            plan.save()
            linked += 1
            self.stdout.write(self.style.SUCCESS(f"  + link {plan.slug} -> {tag.slug}"))
        return linked

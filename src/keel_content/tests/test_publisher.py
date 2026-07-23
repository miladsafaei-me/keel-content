"""Publisher adapter: creates a Post with the pipeline flag + visual blocks intact."""

from __future__ import annotations

import uuid

from django.test import TestCase

from blog.models import Author, Post
from keel_content.adapters.signalbots import publish
from keel_content.core.types import PublishPayload


def _make_payload(slug: str, *, author_slug: str, reviewer_slug: str | None = None):
    return PublishPayload(
        slug=slug,
        title="Test Article",
        h1="Test Article Heading",
        meta_title="Test Article",
        meta_description="Test meta description.",
        excerpt="A short excerpt.",
        key_takeaways_markdown="- one\n- two",
        final_markdown=(
            "## Intro {#intro}\n\n"
            "Some body.\n\n"
            '<figure class="cp-figure-mermaid"><pre class="mermaid">\nflowchart LR\nA --> B\n</pre></figure>\n'
        ),
        target="blog",
        author_slug=author_slug,
        reviewer_slug=reviewer_slug,
        initial_status="draft",
    )


class PublisherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(
            name="Test Author", slug=f"test-author-{uuid.uuid4().hex[:6]}",
        )

    def test_creates_post_with_pipeline_flag(self):
        slug = f"test-post-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(slug, author_slug=self.author.slug)
        admin_url = publish(payload)
        self.assertIn(slug, [p.slug for p in Post.all_objects.all()])
        post = Post.all_objects.get(slug=slug)
        self.assertTrue(post.is_pipeline_generated)
        self.assertEqual(post.status, "draft")
        self.assertEqual(post.author, self.author)
        self.assertIsNotNone(admin_url)

    def test_mermaid_survives_render(self):
        slug = f"test-mermaid-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(slug, author_slug=self.author.slug)
        publish(payload)
        post = Post.all_objects.get(slug=slug)
        self.assertIn('<pre class="mermaid">', post.content_raw)
        self.assertIn('<pre class="mermaid">', post.content_rendered or "")

    def test_heading_anchor_in_rendered_html(self):
        slug = f"test-anchor-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(slug, author_slug=self.author.slug)
        publish(payload)
        post = Post.all_objects.get(slug=slug)
        self.assertIn('id="intro"', post.content_rendered or "")

    def test_missing_author_raises_helpful_error(self):
        payload = _make_payload(
            f"test-{uuid.uuid4().hex[:6]}", author_slug="definitely-not-a-real-slug",
        )
        with self.assertRaises(RuntimeError) as ctx:
            publish(payload)
        self.assertIn("not found", str(ctx.exception).lower())

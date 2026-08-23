"""The two guards that stand between a misconfigured host and a half-rewritten corpus.

Both exist because of live incidents, and both are cheap only because they run
BEFORE the first row: a hook that cannot import, and a body that has no Markdown to
link into.
"""

from __future__ import annotations

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from keel_content import host
from keel_content.core.preflight import require_write_hooks
from keel_content.management.commands.content_relink import _guard_empty_bodies

_GOOD = "keel_cms.markdown_convert.markdown_to_blog_html"


class PreflightHookTests(SimpleTestCase):
    @override_settings(KEEL_CONTENT={"markdown_html_hook": _GOOD})
    def test_a_reachable_hook_passes(self):
        self.assertIsNone(host.preflight_hooks("markdown_html_hook"))

    @override_settings(KEEL_CONTENT={"refresh_rendered_hook": "nowhere.at.all"})
    def test_an_unreachable_hook_is_refused_by_name(self):
        with self.assertRaises(host.HookResolutionError) as ctx:
            host.preflight_hooks("refresh_rendered_hook")
        self.assertIn("refresh_rendered_hook", str(ctx.exception))
        self.assertIn("nowhere.at.all", str(ctx.exception))

    @override_settings(KEEL_CONTENT={"refresh_rendered_hook": "nowhere.at.all",
                                     "prepare_storage_hook": "also.nowhere"})
    def test_every_broken_hook_is_reported_not_just_the_first(self):
        with self.assertRaises(host.HookResolutionError) as ctx:
            host.preflight_hooks("refresh_rendered_hook", "prepare_storage_hook")
        self.assertIn("refresh_rendered_hook", str(ctx.exception))
        self.assertIn("prepare_storage_hook", str(ctx.exception))

    def test_an_unknown_hook_name_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            host.resolve_hook("not_a_hook")

    @override_settings(KEEL_CONTENT={"refresh_rendered_hook": "nowhere.at.all"})
    def test_commands_see_a_command_error(self):
        with self.assertRaises(CommandError):
            require_write_hooks("refresh_rendered_hook")

    @override_settings(KEEL_CONTENT={"markdown_html_hook": _GOOD})
    def test_the_legacy_resolver_still_returns_the_callable(self):
        self.assertTrue(callable(host.resolve_hook("markdown_html_hook")))


class EmptyBodyGuardTests(SimpleTestCase):
    def setUp(self):
        self.reported: list[str] = []

    def _rows(self):
        return [
            {"slug": "has-body", "body_markdown": "## text"},
            {"slug": "html-only", "body_markdown": ""},
            {"slug": "whitespace-only", "body_markdown": "   \n"},
        ]

    def test_a_fully_converted_set_passes_and_excludes_nothing(self):
        rows = [{"slug": "a", "body_markdown": "x"}]
        self.assertEqual(_guard_empty_bodies(rows, False, self.reported.append), set())
        self.assertEqual(self.reported, [])

    def test_an_empty_body_is_refused_by_default(self):
        with self.assertRaises(CommandError) as ctx:
            _guard_empty_bodies(self._rows(), False, self.reported.append)
        message = str(ctx.exception)
        self.assertIn("html-only", message)
        self.assertIn("whitespace-only", message)
        # The way out is named, or the operator has no reason to suspect one exists.
        self.assertIn("backfill_markdown_source", message)

    def test_skip_empty_bodies_excludes_them_and_says_so(self):
        excluded = _guard_empty_bodies(self._rows(), True, self.reported.append)
        self.assertEqual(excluded, {"html-only", "whitespace-only"})
        self.assertIn("excluded 2 of 3", self.reported[0])

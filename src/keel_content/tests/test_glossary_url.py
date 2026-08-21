"""``host.glossary_url`` — the host owns its glossary route, the package never guesses.

Pure resolution logic (no DB, no URLconf), so ``SimpleTestCase``. The three
branches under test are the three real host shapes: a project that wires a hook
(Binary Option Trading), a project whose term model reverses its own URL
(SignalBots), and a project that does neither — which must yield ``""`` rather
than a fabricated path.
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from keel_content import host


class FakeTerm:
    def __init__(self, slug, url=None, raises=False):
        self.slug = slug
        self._url = url
        self._raises = raises

    def get_absolute_url(self):
        if self._raises:
            raise RuntimeError("no URLconf wired")
        return self._url


class TermWithoutUrlMethod:
    def __init__(self, slug):
        self.slug = slug


def _hook(term):
    return f"/tag/{term.slug}"


def _blank_hook(term):
    return ""


class GlossaryUrlTests(SimpleTestCase):
    def test_hook_wins_over_the_model_method(self):
        term = FakeTerm("payout-percentage", url="/trading-glossary/payout-percentage")
        with override_settings(KEEL_CONTENT={"glossary_url_hook": f"{__name__}._hook"}):
            self.assertEqual(host.glossary_url(term), "/tag/payout-percentage")

    def test_model_method_used_when_no_hook_configured(self):
        term = FakeTerm("copy-trading", url="/trading-glossary/copy-trading")
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.glossary_url(term), "/trading-glossary/copy-trading")

    def test_empty_model_url_is_not_replaced_by_a_guess(self):
        # keel_cms.Tag.get_absolute_url returns "" when the host registers no
        # keel_cms: route names. The old code substituted /trading-glossary/<slug>
        # here and shipped 673 dead links on Binary Option Trading.
        term = FakeTerm("15-minute-block-expiry", url="")
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.glossary_url(term), "")

    def test_model_method_raising_yields_empty_not_an_exception(self):
        term = FakeTerm("expiry-time", raises=True)
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.glossary_url(term), "")

    def test_term_without_the_method_yields_empty(self):
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.glossary_url(TermWithoutUrlMethod("delta")), "")

    def test_hook_returning_blank_yields_empty(self):
        term = FakeTerm("delta", url="/trading-glossary/delta")
        with override_settings(KEEL_CONTENT={"glossary_url_hook": f"{__name__}._blank_hook"}):
            self.assertEqual(host.glossary_url(term), "")

    def test_unimportable_hook_yields_empty_not_a_crash(self):
        term = FakeTerm("delta", url="/trading-glossary/delta")
        with override_settings(KEEL_CONTENT={"glossary_url_hook": "nope.missing.callable"}):
            self.assertEqual(host.glossary_url(term), "")


def _post_hook(post):
    return f"/academy/{post.slug}"


class PostUrlTests(SimpleTestCase):
    """``host.post_url`` — same contract as ``glossary_url``, for articles.

    Worth its own suite because ``keel_cms.Post`` implements no
    ``get_absolute_url`` at all, so for every keel-cms host the hook is the ONLY
    working path — and these URLs are written into published article bodies.
    """

    def test_hook_wins_over_the_model_method(self):
        post = FakeTerm("a-b-book-brokers", url="/blog/a-b-book-brokers")
        with override_settings(KEEL_CONTENT={"post_url_hook": f"{__name__}._post_hook"}):
            self.assertEqual(host.post_url(post), "/academy/a-b-book-brokers")

    def test_model_method_used_when_no_hook_configured(self):
        post = FakeTerm("payout-basics", url="/blog/payout-basics")
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.post_url(post), "/blog/payout-basics")

    def test_no_hook_and_no_method_yields_empty_not_a_guess(self):
        # The keel-cms shape: Post has no get_absolute_url. The old code emitted
        # f"/blog/{slug}" here, which is a 404 on any host routing articles
        # elsewhere (Revenika serves /academy/<slug>).
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.post_url(TermWithoutUrlMethod("payout-basics")), "")

    def test_unimportable_hook_yields_empty_not_a_crash(self):
        post = FakeTerm("payout-basics", url="/blog/payout-basics")
        with override_settings(KEEL_CONTENT={"post_url_hook": "nope.missing.callable"}):
            self.assertEqual(host.post_url(post), "")


class GlossaryShotDirTests(SimpleTestCase):
    def test_defaults_to_the_reference_host_layout(self):
        with override_settings(KEEL_CONTENT={}):
            self.assertEqual(host.glossary_shot_dir(), "/app/tools/glossary-viz/out")

    def test_host_override_applies_per_call_not_at_import(self):
        # It used to be a module-level constant, frozen at import — the same
        # import-time-freeze defect TODO.md records for the hero palette.
        with override_settings(KEEL_CONTENT={"glossary_shot_dir": "/srv/shots"}):
            self.assertEqual(host.glossary_shot_dir(), "/srv/shots")

"""Rule-based em-dash replacement: each job an em dash does gets its plain replacement."""

from __future__ import annotations

import os
import tempfile

from django.test import SimpleTestCase

from keel_content.core import em_dash_files
from keel_content.core.em_dash import AMBIGUOUS, build_view, classify, replace_em_dashes
from keel_content.core.text_normalize import normalize_bundle


class ReplaceEmDashesTests(SimpleTestCase):
    def assertReplaced(self, before: str, after: str) -> None:
        self.assertEqual(replace_em_dashes(before), after)

    def test_label_takes_a_colon(self):
        self.assertReplaced("CySEC — investor warnings", "CySEC: investor warnings")

    def test_soft_continuation_takes_a_comma(self):
        self.assertReplaced("OTC never closes — so the signals run", "OTC never closes, so the signals run")

    def test_new_clause_takes_a_full_stop_and_capital(self):
        self.assertReplaced(
            "It separates real moves from noise — it reads your trend.",
            "It separates real moves from noise. It reads your trend.",
        )

    def test_answer_word_takes_a_comma(self):
        self.assertReplaced("No — it never connects.", "No, it never connects.")

    def test_aside_pair_takes_commas(self):
        self.assertReplaced("Ours — connector included — is free.", "Ours, connector included, is free.")

    def test_aside_with_its_own_comma_takes_brackets(self):
        self.assertReplaced(
            "no result — historical, backtested or otherwise — is guaranteed.",
            "no result (historical, backtested or otherwise) is guaranteed.",
        )

    def test_placeholder_becomes_hyphen(self):
        self.assertReplaced("<td>—</td>", "<td>-</td>")

    def test_brand_separator_becomes_pipe(self):
        self.assertReplaced("Pricing — SignalBots", "Pricing | SignalBots")

    def test_entity_spelling_is_replaced(self):
        self.assertReplaced("CySEC &mdash; investor warnings", "CySEC: investor warnings")

    def test_markup_is_kept_and_capital_lands_inside_it(self):
        self.assertReplaced(
            'Trading carries substantial risk — review our <a href="/r">warning</a>.',
            'Trading carries substantial risk. Review our <a href="/r">warning</a>.',
        )

    def test_no_em_dash_left_after_default_resolution(self):
        text = "The firm's account — the payoff for clearing the challenge inside the limit."
        self.assertNotIn("—", replace_em_dashes(text))

    def test_short_title_defaults_to_a_colon(self):
        self.assertReplaced("FTMO EA rules — what an EA can and cannot do", "FTMO EA rules: what an EA can and cannot do")

    def test_idempotent_and_empty_safe(self):
        once = replace_em_dashes("Fast — so you never miss a call.")
        self.assertEqual(replace_em_dashes(once), once)
        self.assertEqual(replace_em_dashes(""), "")

    def test_unplaceable_dash_is_reported_ambiguous(self):
        dashes = classify(build_view("and the account grows — the payoff for clearing the challenge inside the limit.").text)
        self.assertEqual(dashes[0].kind, AMBIGUOUS)


class NormalizeBundleEmDashTests(SimpleTestCase):
    def test_off_by_default(self):
        bundle = normalize_bundle({"title": "A — B"})
        self.assertEqual(bundle["title"], "A — B")

    def test_opt_in_rewrites_prose_but_not_fenced_blocks(self):
        body = "Fast — so you never miss.\n\n```cp-component\n{\"t\": \"a — b\"}\n```\n"
        bundle = normalize_bundle({"body_markdown": body}, replace_em_dash=True)
        self.assertIn("Fast, so you never miss.", bundle["body_markdown"])
        self.assertIn('{"t": "a — b"}', bundle["body_markdown"])


class SourceFileTests(SimpleTestCase):
    def _write(self, name: str, content: str) -> str:
        d = tempfile.mkdtemp()
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_python_strings_change_but_docstrings_and_comments_do_not(self):
        src = (
            '"""Module — docstring."""\n'
            "# comment — stays\n"
            'X = ("Ours — connector included "\n'
            '     "— is free.")\n'
        )
        path = self._write("m.py", src)
        em_dash_files.apply_file(path, {})
        out = open(path, encoding="utf-8").read()
        self.assertIn('"""Module — docstring."""', out)
        self.assertIn("# comment — stays", out)
        self.assertIn('X = ("Ours, connector included"\n     ", is free.")', out)

    def test_template_comments_are_left_alone(self):
        src = "{% comment %}note — here{% endcomment %}<p>CySEC — investor warnings</p>"
        path = self._write("t.html", src)
        em_dash_files.apply_file(path, {})
        out = open(path, encoding="utf-8").read()
        self.assertEqual(out, "{% comment %}note — here{% endcomment %}<p>CySEC: investor warnings</p>")

    def test_js_comments_are_left_alone(self):
        src = "// helper — note\nel.textContent = '—';\n"
        path = self._write("a.js", src)
        em_dash_files.apply_file(path, {}, skip_literal_only=False)
        self.assertEqual(open(path, encoding="utf-8").read(), "// helper — note\nel.textContent = '-';\n")

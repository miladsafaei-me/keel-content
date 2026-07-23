"""Prompt template rendering: dotted-path resolution + graceful missing-key handling."""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from keel_content.core.config import render_prompt


class RenderPromptTests(SimpleTestCase):
    def test_simple_substitution(self):
        out = render_prompt("Hello {{name}}!", {"name": "Milad"})
        self.assertEqual(out, "Hello Milad!")

    def test_nested_dotted_path(self):
        ctx = {"a": {"b": {"c": "deep"}}}
        self.assertEqual(render_prompt("{{a.b.c}}", ctx), "deep")

    def test_missing_path_yields_empty_string(self):
        # Avoids the pipeline crashing when a key is added to a prompt but
        # not yet to config.json; warning is preferable to a hard fail.
        self.assertEqual(render_prompt("[{{a.b.c}}]", {"a": {}}), "[]")

    def test_dict_value_serialized_as_json(self):
        ctx = {"data": {"x": 1, "y": "two"}}
        out = render_prompt("{{data}}", ctx)
        self.assertEqual(json.loads(out), {"x": 1, "y": "two"})

    def test_list_value_serialized_as_json(self):
        out = render_prompt("{{xs}}", {"xs": ["a", "b"]})
        self.assertEqual(json.loads(out), ["a", "b"])

    def test_multiple_occurrences(self):
        out = render_prompt("{{x}} and {{x}}", {"x": "y"})
        self.assertEqual(out, "y and y")

    def test_whitespace_inside_braces_tolerated(self):
        self.assertEqual(render_prompt("{{ name }}", {"name": "ok"}), "ok")

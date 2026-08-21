"""``./manage.py author_glossary_terms`` — author backlog glossary terms end to
end: draft the content, author a comprehension-gated visual, validate it, load
it noindex, then screenshot + vision-judge it, regenerating the visual until it
passes the gate.

This is the engine behind ``docs/glossary/term-pipeline-design.md``. The judge is
not optional here: a term is only ever *staged* (content + a passing visual) by
this command; turning the staged set into ship-able migrations is the separate
``persist_glossary_terms`` command, which **refuses** any term lacking a pass
verdict. So "the pipeline suggested these terms -> generate them" always yields a
judged visual, with no manual judge step to forget.

Authoring uses ``ClaudeClient`` directly (deterministic, sequential) — the same
client ``glossary_gap`` uses. Screenshots run in-container via
``render_glossary_shots`` (Chromium is baked into the web image), so the whole
flow is host-independent.

    ./manage.py author_glossary_terms --from-backlog --limit 5
    ./manage.py author_glossary_terms --terms "Trailing Stop,Slippage"
    ./manage.py author_glossary_terms --terms "Foo" --dry-run   # author+validate, no DB, no judge
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from keel_content import host
from keel_content.core import glossary_backlog, term_match
from keel_content.core.claude_client import ClaudeClient
from keel_content.core.config import read_prompt, render_prompt
from keel_ui import iter_components, render as library_render
from keel_ui.renderer import SpecValidationError

Tag = host.tag_model()

STAGING_SUBDIR = "glossary-staging"
DRAFT_MODEL = "claude-opus-4-8"
VISUAL_MODEL = "claude-opus-4-8"


def _staging_dir() -> Path:
    from keel_content.core import paths
    d = paths.pipeline_root() / STAGING_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _existing_terms_block() -> str:
    rows = Tag.objects.filter(is_term=True).order_by("name").values_list("name", "slug")
    return "\n".join(f"- {name}  ->  {slug}" for name, slug in rows) or "(glossary is empty)"


def _category_block() -> str:
    return "\n".join(f"- {c}" for c in host.glossary_category_order())


def _surface_block() -> str:
    return "\n".join(
        f"- {url}  ({label})" for url, label in host.glossary_surface_labels().items()
    )


def _catalog_block() -> str:
    """Every component: id, category, when-to-pick, schema, example — for the picker."""
    parts: list[str] = []
    for c in sorted(iter_components(), key=lambda c: (c.category, c.id)):
        parts.append(
            f"### {c.id}  ({c.category})\n"
            f"when: {c.when_to_pick}\n"
            f"schema: {json.dumps(c.schema, ensure_ascii=False)}\n"
            f"example: {json.dumps(c.example, ensure_ascii=False)}"
        )
    return "\n\n".join(parts)


class Command(BaseCommand):
    help = "Author backlog glossary terms (content + judged visual), staged for persist."

    def add_arguments(self, parser):
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument("--from-backlog", action="store_true",
                        help="Author the pending candidates in the glossary backlog.")
        src.add_argument("--terms", default=None,
                        help='Comma-separated term names to author (e.g. "Trailing Stop,Slippage").')
        parser.add_argument("--limit", type=int, default=None, help="Cap how many terms to author.")
        parser.add_argument("--max-rounds", type=int, default=3,
                            help="Max visual regen rounds before giving up on the gate.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Author + validate the spec only; no DB write, no judge.")
        parser.add_argument("--no-judge", action="store_true",
                            help="Stage to DB but SKIP the judge gate (loud warning; not the default).")

    def _candidates(self, opts) -> list[dict[str, Any]]:
        """Resolve the term worklist from the backlog or the explicit --terms list."""
        if opts["from_backlog"]:
            items = glossary_backlog.pending()
        else:
            items = [{"term": t.strip()} for t in opts["terms"].split(",") if t.strip()]
        if opts["limit"]:
            items = items[: opts["limit"]]
        if not items:
            raise CommandError("No candidate terms to author.")
        return items

    def _draft(self, client: ClaudeClient, cand: dict[str, Any]) -> dict[str, Any]:
        """Claude step 07 — write the term content record."""
        ctx = {
            "term": cand.get("term", ""),
            "anchor": cand.get("anchor") or cand.get("reason") or cand.get("term", ""),
            "reason": cand.get("reason", ""),
            "example_sentence": cand.get("example_sentence", ""),
            "existing_terms_block": _existing_terms_block(),
            "surface_urls_block": _surface_block(),
            "category_block": _category_block(),
        }
        reply = client.call(
            step="glossary_author_term", model=DRAFT_MODEL, max_tokens=4000,
            system_text=render_prompt(read_prompt("07-author-term"), ctx),
            user_text="Write the term record JSON now.", expect_json=True,
        )
        if not isinstance(reply.json, dict) or not reply.json.get("term"):
            raise CommandError(f"draft for {cand.get('term')!r} did not return a valid record")
        return reply.json

    def _visual(self, client: ClaudeClient, record: dict[str, Any],
                *, repair_msg: str | None = None) -> dict[str, Any]:
        """Claude step 08 — pick a component and author its data spec."""
        ctx = {
            "term": record.get("term", ""),
            "what_is": record.get("what_is", ""),
            "why_it_matters": record.get("why_it_matters", ""),
            "formula": record.get("formula") or "none",
            "real_world_example": record.get("real_world_example", ""),
            "catalog_block": _catalog_block(),
        }
        user = "Pick a component and write the visual JSON now."
        if repair_msg:
            user += f"\n\nYour previous spec FAILED schema validation:\n{repair_msg}\nFix it and return valid JSON."
        reply = client.call(
            step="glossary_author_visual", model=VISUAL_MODEL, max_tokens=2500,
            system_text=render_prompt(read_prompt("08-author-visual"), ctx),
            user_text=user, expect_json=True,
        )
        if not isinstance(reply.json, dict) or not reply.json.get("component_id"):
            raise CommandError(f"visual for {record.get('term')!r} did not return a valid spec")
        return reply.json

    def _revise(self, client: ClaudeClient, record: dict[str, Any],
                rejected: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
        """Claude step 09 — re-author a rejected visual against the judge verdict."""
        ctx = {
            "term": record.get("term", ""),
            "what_is": record.get("what_is", ""),
            "why_it_matters": record.get("why_it_matters", ""),
            "formula": record.get("formula") or "none",
            "real_world_example": record.get("real_world_example", ""),
            "rejected_component_id": rejected.get("component_id", ""),
            "rejected_spec": json.dumps(rejected.get("spec") or {}, ensure_ascii=False),
            "misses": "; ".join(verdict.get("misses") or []) or "(none stated)",
            "suggested_fix": verdict.get("suggested_fix") or "(none stated)",
            "catalog_block": _catalog_block(),
        }
        reply = client.call(
            step="glossary_revise_visual", model=VISUAL_MODEL, max_tokens=2500,
            system_text=render_prompt(read_prompt("09-revise-visual"), ctx),
            user_text="Write the revised visual JSON now.", expect_json=True,
        )
        if not isinstance(reply.json, dict) or not reply.json.get("component_id"):
            raise CommandError(f"revise for {record.get('term')!r} did not return a valid spec")
        return reply.json

    def _validate_visual(self, visual: dict[str, Any]) -> str | None:
        """Return None if the spec renders, else the validation message."""
        try:
            library_render(visual["component_id"], visual.get("spec") or {})
            return None
        except SpecValidationError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001 - any render failure is a reject
            return f"render error: {exc}"

    def _to_visuals_field(self, visual: dict[str, Any]) -> list[dict[str, Any]]:
        """Assemble the Tag.visuals one-item list, keeping a single (top-level) caption."""
        item: dict[str, Any] = {"component_id": visual["component_id"], "spec": visual.get("spec") or {}}
        cap = visual.get("caption") or item["spec"].pop("caption", None)
        if cap:
            item["caption"] = cap
        if visual.get("eyebrow"):
            item["eyebrow"] = visual["eyebrow"]
        return [item]

    def _stage_load(self, record: dict[str, Any], visuals: list[dict[str, Any]]) -> str:
        """Upsert the term into the DB as a noindex page so it can be rendered + judged."""
        Landing = host.landing_model()
        slug = slugify(record["term"])
        faq = [
            {"question": (f.get("q") or "").strip(), "answer": (f.get("a") or "").strip()}
            for f in record.get("faq") or []
            if (f.get("q") and f.get("a"))
        ]
        tag, _ = Tag.objects.update_or_create(
            slug=slug,
            defaults={
                "name": record["term"].strip(),
                "abbreviation": (record.get("abbreviation") or "").strip(),
                "is_term": True,
                "aka": record.get("aka") or [],
                "what_is": record.get("what_is") or "",
                "why_it_matters": record.get("why_it_matters") or "",
                "formula": record.get("formula"),
                "real_world_example": record.get("real_world_example") or "",
                "pro_tip": record.get("pro_tip") or "",
                "common_pitfalls": record.get("common_pitfalls") or "",
                "trade_impact": record.get("trade_impact") or [],
                "signalbots_context": record.get("signalbots_context") or "",
                "related_surfaces": record.get("related_surfaces") or [],
                "risk_warning_required": bool(record.get("risk_warning_required")),
                "faq": faq,
                "experience_level": (record.get("experience_level") or "").strip(),
                "parent_category": (record.get("category") or "").strip(),
                "child_category": "",
                "visuals": visuals,
            },
        )
        related_slugs = record.get("related_term_slugs") or record.get("related_terms") or []
        related = list(Tag.objects.filter(is_term=True, slug__in=related_slugs))
        tag.related_terms.set(related)
        # The glossary route is the host's — see host.glossary_url. Hardcoding
        # /trading-glossary/<slug> here would write a Landing row (a real URL) at a
        # path that does not exist on any host but the first two adopters.
        term_url = host.glossary_url(tag)
        if not term_url:
            raise CommandError(
                f"cannot resolve a public URL for term {slug!r}. Set KEEL_CONTENT"
                '["glossary_url_hook"] to a dotted "(term) -> str" callable in the '
                "host adapter. Refusing to create a Landing at a guessed path."
            )
        Landing.objects.get_or_create(
            url=term_url,
            defaults={"is_indexable": False},
        )
        return slug

    def _read_verdict(self, slug: str) -> dict[str, Any]:
        p = Path(host.glossary_shot_dir()) / f"{slug}.verdict.json"
        if not p.is_file():
            return {"verdict": "missing"}
        return json.loads(p.read_text(encoding="utf-8"))

    def handle(self, *args, **opts):
        from django.core.cache import cache
        client = ClaudeClient()
        candidates = self._candidates(opts)
        staging = _staging_dir()
        results: list[tuple[str, str]] = []

        for cand in candidates:
            name = cand.get("term", "?")
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {name} =="))

            existing_sets = term_match.existing_token_sets(
                [{"name": t.name, "abbreviation": t.abbreviation, "aka": t.aka}
                 for t in Tag.objects.filter(is_term=True)]
            )
            if term_match.already_covered(name, existing_sets):
                self.stdout.write(self.style.WARNING(f"  SKIP — already covered: {name}"))
                results.append((name, "duplicate"))
                continue

            record = self._draft(client, cand)
            visual = self._visual(client, record)

            msg = self._validate_visual(visual)
            if msg:
                self.stdout.write(self.style.WARNING(f"  spec invalid, repairing: {msg.splitlines()[0]}"))
                visual = self._visual(client, record, repair_msg=msg)
                msg = self._validate_visual(visual)
                if msg:
                    self.stdout.write(self.style.ERROR(f"  FAIL — spec still invalid: {msg.splitlines()[0]}"))
                    results.append((name, "invalid-spec"))
                    continue

            slug = slugify(record["term"])
            visuals = self._to_visuals_field(visual)
            (staging / f"{slug}.json").write_text(
                json.dumps({"record": record, "visuals": visuals}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if opts["dry_run"]:
                self.stdout.write(self.style.SUCCESS(
                    f"  DRY-RUN — staged {slug} (content + valid visual); no DB, no judge"))
                results.append((name, "dry-run"))
                continue

            self._stage_load(record, visuals)
            cache.clear()

            if opts["no_judge"]:
                self.stdout.write(self.style.WARNING(
                    f"  --no-judge: staged {slug} WITHOUT the comprehension gate"))
                results.append((name, "staged-unjudged"))
                continue

            verdict = {"verdict": "missing"}
            for rnd in range(1, opts["max_rounds"] + 1):
                call_command("render_glossary_shots", slug, verbosity=0)
                call_command("judge_glossary_viz", slug, verbosity=0)
                verdict = self._read_verdict(slug)
                v = verdict.get("verdict")
                sc = verdict.get("scores") or {}
                score = (f"c{sc.get('comprehension','-')} l{sc.get('legibility','-')} "
                         f"m{sc.get('mental_model','-')} b{sc.get('on_brand','-')}")
                self.stdout.write(f"  round {rnd}: {v}  {score}")
                if v == "pass":
                    break
                if rnd < opts["max_rounds"]:
                    visual = self._revise(client, record, visual, verdict)
                    if self._validate_visual(visual):
                        visual = self._visual(client, record)
                    visuals = self._to_visuals_field(visual)
                    Tag.objects.filter(slug=slug).update(visuals=visuals)
                    (staging / f"{slug}.json").write_text(
                        json.dumps({"record": record, "visuals": visuals}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    cache.clear()

            results.append((name, "pass" if verdict.get("verdict") == "pass" else "revise"))

        self.stdout.write("")
        for name, status in results:
            style = self.style.SUCCESS if status in ("pass", "dry-run") else self.style.WARNING
            self.stdout.write(style(f"  {status:18} {name}"))
        passed = sum(1 for _, s in results if s == "pass")
        self.stdout.write(
            f"\nAuthored {len(results)} term(s): {passed} passed the gate. "
            f"Staged in {staging}/. Next: ./manage.py persist_glossary_terms <slug>… "
            f"(it requires a pass verdict)."
        )

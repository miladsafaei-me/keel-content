"""``./manage.py persist_glossary_terms <slug>…`` — turn staged glossary terms
into ship-able artifacts: append each record to ``trading_glossary.json`` and
emit the two data migrations (terms + visuals), mirroring ``0041``/``0042``.

**Hard judge gate:** a staged term is persisted ONLY if it has a recorded
``out/<slug>.verdict.json`` with ``verdict == "pass"``. Any term without one is
skipped and the command exits non-zero. This is what makes the comprehension
gate structural rather than a discipline step — the failure mode that shipped the
26 unjudged Category-2 visuals (migration 0033) cannot recur through this path.

Run after ``author_glossary_terms`` has staged + judged the terms. Persisted
terms are dropped from the glossary backlog. The emitted migrations are
data-only; run ``makemigrations --check`` afterwards (it stays clean) and ship
via the normal accumulate-on-main flow. New term Landings ship
``is_indexable=False`` — indexing stays a deliberate ``/admin-os/landings/`` flip.

    ./manage.py persist_glossary_terms trailing-stop slippage
    ./manage.py persist_glossary_terms --all          # every staged slug with a pass verdict
"""

from __future__ import annotations

import json
import pprint
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keel_content.core import glossary_backlog

STAGING_SUBDIR = "glossary-staging"
SHOT_DIR = "/app/tools/glossary-viz/out"


def _staging_dir() -> Path:
    from keel_content.core import paths
    return paths.pipeline_root() / STAGING_SUBDIR


def _glossary_json_path() -> Path:
    return Path(settings.BASE_DIR) / "core" / "data" / "trading_glossary.json"


def _migrations_dir() -> Path:
    return Path(settings.BASE_DIR) / "blog" / "migrations"


def _next_migration_number() -> int:
    nums = []
    for p in _migrations_dir().glob("[0-9][0-9][0-9][0-9]_*.py"):
        try:
            nums.append(int(p.name[:4]))
        except ValueError:
            continue
    return (max(nums) + 1) if nums else 1


def _latest_pkg_migration(app_label: str) -> str:
    """Latest migration name of an installed-package app (keel_cms / keel_seo).

    The generated glossary migration lives in the host's ``blog/migrations`` but
    upserts models the Keel move relocated out of the host apps — Tag now lives in
    keel-cms, Landing in keel-seo — so it must declare a dependency on those apps'
    current state (otherwise ``apps.get_model`` for them raises at ``migrate`` time).
    Scans the installed package's ``migrations`` package rather than a host path.
    """
    import pkgutil
    from importlib import import_module
    try:
        mod = import_module(f"{app_label}.migrations")
    except Exception:  # noqa: BLE001 — app not installed; fall back to initial
        return "0001_initial"
    names = sorted(n for _, n, _ in pkgutil.iter_modules(mod.__path__) if n[:4].isdigit())
    return names[-1] if names else "0001_initial"


class Command(BaseCommand):
    help = "Persist staged glossary terms (gate: pass verdict required) into JSON + migrations."

    def add_arguments(self, parser):
        parser.add_argument("slugs", nargs="*", help="Staged term slugs to persist.")
        parser.add_argument("--all", action="store_true", dest="all_staged",
                            help="Persist every staged slug that has a pass verdict.")
        parser.add_argument("--batch-name", default="authored",
                            help="Label used in the migration filenames (default: authored).")

    def _staged_slugs(self, opts) -> list[str]:
        staging = _staging_dir()
        if opts["all_staged"]:
            return sorted(p.stem for p in staging.glob("*.json"))
        if not opts["slugs"]:
            raise CommandError("Pass staged slugs, or --all.")
        return opts["slugs"]

    def _verdict_passes(self, slug: str) -> bool:
        p = Path(SHOT_DIR) / f"{slug}.verdict.json"
        if not p.is_file():
            return False
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("verdict") == "pass"
        except Exception:  # noqa: BLE001
            return False

    def _record_to_json_term(self, staged: dict[str, Any], new_id: int,
                            slug_to_id: dict[str, int]) -> dict[str, Any]:
        """Map a staged author record onto the trading_glossary.json term shape."""
        r = staged["record"]
        related_ids = [slug_to_id[s] for s in (r.get("related_term_slugs") or []) if s in slug_to_id]
        return {
            "id": new_id,
            "slug": _slug(r["term"]),
            "term": r["term"].strip(),
            "abbreviation": (r.get("abbreviation") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "aka": r.get("aka") or [],
            "what_is": r.get("what_is") or "",
            "why_it_matters": r.get("why_it_matters") or "",
            "formula": r.get("formula"),
            "trade_impact": r.get("trade_impact") or [],
            "real_world_example": r.get("real_world_example") or "",
            "signalbots_context": r.get("signalbots_context") or "",
            "pro_tip": r.get("pro_tip") or "",
            "common_pitfalls": r.get("common_pitfalls") or "",
            "faq": r.get("faq") or [],
            "related_terms": related_ids,
            "related_surfaces": r.get("related_surfaces") or [],
            "experience_level": (r.get("experience_level") or "").strip(),
            "risk_warning_required": bool(r.get("risk_warning_required")),
        }

    def handle(self, *args, **opts):
        slugs = self._staged_slugs(opts)
        staging = _staging_dir()

        staged: dict[str, dict[str, Any]] = {}
        gated_out: list[str] = []
        for slug in slugs:
            f = staging / f"{slug}.json"
            if not f.is_file():
                raise CommandError(f"no staged file for {slug!r} ({f})")
            if not self._verdict_passes(slug):
                gated_out.append(slug)
                continue
            staged[slug] = json.loads(f.read_text(encoding="utf-8"))

        for slug in gated_out:
            self.stderr.write(self.style.ERROR(
                f"GATE   {slug}  — no pass verdict; refusing to persist. "
                f"Run author_glossary_terms (or judge_glossary_viz) until it passes."))

        if not staged:
            raise CommandError("Nothing to persist (no staged term has a pass verdict).")

        gpath = _glossary_json_path()
        data = json.loads(gpath.read_text(encoding="utf-8"))
        terms = data.get("terms", [])
        slug_to_id = {t["slug"]: t["id"] for t in terms if t.get("slug")}
        max_id = max((t.get("id", 0) for t in terms), default=0)

        new_ids: list[int] = []
        batch_visuals: dict[str, list] = {}
        for slug in sorted(staged):
            max_id += 1
            slug_to_id[_slug(staged[slug]["record"]["term"])] = max_id
            new_ids.append(max_id)
        for slug in sorted(staged):
            new_id = slug_to_id[_slug(staged[slug]["record"]["term"])]
            record = self._record_to_json_term(staged[slug], new_id, slug_to_id)
            terms.append(record)
            batch_visuals[record["slug"]] = staged[slug]["visuals"]

        data["terms"] = terms
        gpath.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        n1 = _next_migration_number()
        terms_mig = f"{n1:04d}_load_{opts['batch_name']}_terms.py"
        vis_mig = f"{n1 + 1:04d}_load_{opts['batch_name']}_visuals.py"
        prev = self._latest_migration_name(exclude={terms_mig, vis_mig})

        km = _latest_pkg_migration("keel_cms")
        ks = _latest_pkg_migration("keel_seo")
        (_migrations_dir() / terms_mig).write_text(
            _render_terms_migration(new_ids, prev, km, ks), encoding="utf-8")
        (_migrations_dir() / vis_mig).write_text(
            _render_visuals_migration(batch_visuals, terms_mig[:-3], km), encoding="utf-8")

        for slug in staged:
            glossary_backlog.remove(staged[slug]["record"]["term"])

        self.stdout.write(self.style.SUCCESS(
            f"\nPersisted {len(staged)} term(s) (ids {new_ids[0]}–{new_ids[-1]}):"))
        for slug in sorted(staged):
            self.stdout.write(f"  + {slug}")
        self.stdout.write(
            f"\nWrote {gpath}\n  {terms_mig}\n  {vis_mig}\n"
            f"Run `makemigrations --check` (stays clean) and ship. "
            f"Terms are noindex until flipped in /admin-os/landings/.")
        if gated_out:
            raise CommandError(f"{len(gated_out)} staged term(s) were gated out (no pass verdict).")

    def _latest_migration_name(self, *, exclude: set[str]) -> str:
        names = sorted(p.name for p in _migrations_dir().glob("[0-9][0-9][0-9][0-9]_*.py")
                       if p.name not in exclude)
        return names[-1][:-3] if names else "0001_initial"


def _slug(term: str) -> str:
    from django.utils.text import slugify
    return slugify(term)


def _render_terms_migration(
    new_ids: list[int], prev_migration: str, keel_cms_migration: str, keel_seo_migration: str
) -> str:
    lo, hi = min(new_ids), max(new_ids)
    return f'''"""Load authored glossary terms (ids {lo}-{hi}) into blog_tag.

Emitted by ``persist_glossary_terms`` (see docs/glossary/term-pipeline-design.md).
Mirrors 0041: upserts the new terms from backend/core/data/trading_glossary.json,
wires related_terms by slug, and registers a keel_seo.Landing per URL with
is_indexable=False (default) so each page stays noindex until flipped in
/admin-os/landings/. Each term's visual passed the vision-judge gate at author
time; the companion visuals migration loads the specs. Tag/Landing moved to
keel-cms/keel-seo in the Keel migration, so the models are looked up there.
"""

import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

NEW_IDS = set(range({lo}, {hi + 1}))


def _data_path() -> Path:
    return Path(settings.BASE_DIR) / "core" / "data" / "trading_glossary.json"


def _normalize_faq(faq):
    out = []
    for item in faq or []:
        if not isinstance(item, dict):
            continue
        q = (item.get("q") or item.get("question") or "").strip()
        a = (item.get("a") or item.get("answer") or "").strip()
        if q and a:
            out.append({{"question": q, "answer": a}})
    return out


def load_terms(apps, schema_editor):
    path = _data_path()
    if not path.is_file():
        return
    Tag = apps.get_model("keel_cms", "Tag")
    Landing = apps.get_model("keel_seo", "Landing")
    data = json.loads(path.read_text(encoding="utf-8"))
    all_terms = data.get("terms", [])
    id_to_slug = {{t["id"]: t["slug"] for t in all_terms if t.get("slug")}}
    new_terms = [t for t in all_terms if t.get("id") in NEW_IDS]

    for t in new_terms:
        slug = (t.get("slug") or "").strip()
        name = (t.get("term") or "").strip()
        if not slug or not name:
            continue
        Tag.objects.update_or_create(
            slug=slug,
            defaults={{
                "name": name,
                "abbreviation": (t.get("abbreviation") or "").strip(),
                "is_term": True,
                "aka": t.get("aka") or [],
                "what_is": t.get("what_is") or "",
                "why_it_matters": t.get("why_it_matters") or "",
                "formula": t.get("formula"),
                "real_world_example": t.get("real_world_example") or "",
                "pro_tip": t.get("pro_tip") or "",
                "common_pitfalls": t.get("common_pitfalls") or "",
                "trade_impact": t.get("trade_impact") or [],
                "signalbots_context": t.get("signalbots_context") or "",
                "related_surfaces": t.get("related_surfaces") or [],
                "risk_warning_required": bool(t.get("risk_warning_required")),
                "faq": _normalize_faq(t.get("faq")),
                "experience_level": (t.get("experience_level") or "").strip(),
                "parent_category": (t.get("category") or "").strip(),
                "child_category": "",
            }},
        )

    by_slug = {{tag.slug: tag for tag in Tag.objects.filter(is_term=True)}}
    for t in new_terms:
        tag = by_slug.get(t.get("slug"))
        if tag is None:
            continue
        related_slugs = [id_to_slug.get(rid) for rid in (t.get("related_terms") or [])]
        related = [by_slug[s] for s in related_slugs if s and s in by_slug]
        tag.related_terms.set(related)

    for t in new_terms:
        slug = (t.get("slug") or "").strip()
        name = (t.get("term") or "").strip()
        if not slug or not name:
            continue
        Landing.objects.update_or_create(
            url=f"/trading-glossary/{{slug}}",
            defaults={{"title": f"{{name}} | Trading Glossary"}},
        )


def unload_terms(apps, schema_editor):
    path = _data_path()
    slugs = []
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        slugs = [t["slug"] for t in data.get("terms", []) if t.get("id") in NEW_IDS]
    if not slugs:
        return
    Tag = apps.get_model("keel_cms", "Tag")
    Landing = apps.get_model("keel_seo", "Landing")
    Tag.objects.filter(slug__in=slugs, is_term=True).delete()
    Landing.objects.filter(url__in=[f"/trading-glossary/{{s}}" for s in slugs]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "{prev_migration}"),
        ("keel_cms", "{keel_cms_migration}"),
        ("keel_seo", "{keel_seo_migration}"),
    ]

    operations = [
        migrations.RunPython(load_terms, unload_terms),
    ]
'''


def _render_visuals_migration(
    batch_visuals: dict[str, list], terms_migration: str, keel_cms_migration: str
) -> str:
    body = pprint.pformat(batch_visuals, width=98, sort_dicts=True)
    return f'''"""Attach the vision-judged visual spec to each authored glossary term.

Emitted by ``persist_glossary_terms``. Companion to {terms_migration}. Each spec
selects a keel_ui component, validates against that component's
JSON Schema, and passed the judge_glossary_viz vision gate at author time. Each
value is a one-item list, matching Tag.visuals.
"""

from django.db import migrations

BATCH_VISUALS = {body}


def load_visuals(apps, schema_editor):
    Tag = apps.get_model("keel_cms", "Tag")
    for slug, visuals in BATCH_VISUALS.items():
        Tag.objects.filter(slug=slug, is_term=True).update(visuals=visuals)


def unload_visuals(apps, schema_editor):
    Tag = apps.get_model("keel_cms", "Tag")
    Tag.objects.filter(slug__in=list(BATCH_VISUALS)).update(visuals=[])


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "{terms_migration}"),
        ("keel_cms", "{keel_cms_migration}"),
    ]

    operations = [
        migrations.RunPython(load_visuals, unload_visuals),
    ]
'''

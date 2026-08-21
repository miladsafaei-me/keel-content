"""``./manage.py contentplan_export_registry --out <path>`` — project committed
ContentPlan rows into an intent-registry.json the stdlib reconcile engine reads.

The ContentPlan table is the single source of truth; the registry FILE is now a
regenerated projection of it, not a hand-maintained store. Each committed row (one with
a ``canonical_key``, in ``reconciled`` / ``drafted`` / ``published`` status) becomes one
registry entry keyed on ``canonical_key``, so a fresh reconcile run dedups new plans
against every need already committed in past runs (decision #4 in
CANNIBALIZATION-PREVENTION-PLAN.md). The hand-curated ``entity_families`` synonym net is
carried over verbatim from the canonical registry file (the only part still authored by
hand).

Glossary terms are ALSO projected (``--skip-glossary`` to omit): every
``Tag(is_term=True)`` is a pre-owned ``what-is`` need whose owner is its
own public page (resolved through ``host.glossary_url``, never guessed),
and every QUEUED term — a ContentPlan row with
``target=glossary_term`` still pending — owns its need too (``owner_status=planned``:
a what-is blog must not be planned for a term already queued for authoring). Both
sets are queried at export time, so the projection always reflects the current
glossary + queue. A keyword cluster asking "what is <term>" therefore collides in
reconcile and becomes an ENRICHMENT opportunity (optimize the glossary page with
that keyword demand, up to full what-is-blog depth) instead of a duplicate blog
post. The reverse does not hold — a surviving what-is spec never auto-creates a term.

Pipe into: ``intent_registry.py bucket <worklist> --registry <this output>``.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from keel_content import host

ContentPlan = host.content_plan_model()
Tag = host.tag_model()

# backend/content_pipeline/management/commands/<this> -> repo root is parents[4].
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CANONICAL_REGISTRY = _REPO_ROOT / "content-pipeline" / "intent-registry.json"
_COMMITTED = (
    ContentPlan.Status.RECONCILED,
    ContentPlan.Status.DRAFTED,
    ContentPlan.Status.PUBLISHED,
)
CROSS_MARKET = "cross-market"


def _market_axes(market_names):
    """Mirror intent_registry.py ``_markets``: (is_cross, primary_specific_market)."""
    raw = [(m or "").strip().lower() for m in market_names if (m or "").strip()]
    specifics = [m for m in raw if "cross" not in m]
    is_cross = (not specifics) or any("cross" in m for m in raw)
    primary = specifics[0] if specifics else CROSS_MARKET
    return is_cross, primary


class Command(BaseCommand):
    help = "Project committed ContentPlan rows into a reconcile-engine registry.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--families-from",
            default=str(_CANONICAL_REGISTRY),
            help="registry .json to copy entity_families from (default: the canonical file).",
        )
        parser.add_argument("--out", default="", help="Write registry JSON here (default: stdout).")
        parser.add_argument(
            "--skip-glossary",
            action="store_true",
            help="Do not project glossary terms (live or queued) as pre-owned "
            "what-is needs.",
        )

    def handle(self, *args, **opts):
        families_path = Path(opts["families_from"]).expanduser()
        families, note, version = [], "", 1
        if families_path.is_file():
            base = json.loads(families_path.read_text(encoding="utf-8"))
            families = base.get("entity_families", [])
            note = base.get("note", "")
            version = base.get("version", 1)

        entries = []
        qs = (
            ContentPlan.objects.filter(status__in=_COMMITTED)
            .exclude(canonical_key="")
            # Term rows are projected as glossary owners below (owner_kind=
            # glossary_term), never as plan entries — one owner per need.
            .exclude(target=ContentPlan.Target.GLOSSARY_TERM)
            .prefetch_related("markets")
            # produced_post is dereferenced per row for its public URL — without
            # this the export fires one extra query per produced plan.
            .select_related("produced_post")
        )
        for plan in qs:
            is_cross, primary = _market_axes([m.name for m in plan.markets.all()])
            frame = (plan.intent_frame or "").strip().lower()
            entries.append({
                "canonical_key": plan.canonical_key,
                "canonical_intent": plan.observed_intent or plan.intent or "",
                "need_signature": f"{primary} | {frame} | {plan.entity}",
                "market": primary,
                "cross_market": is_cross,
                "intent_frame": frame,
                "entity": plan.entity or "",
                "entity_family": None,
                "owner": plan.title or "",
                "owner_content_id": plan.slug,
                "owner_kind": "plan",
                "owner_status": plan.status,
                # The article route is the host's, same as the glossary route above
                # — never f"/blog/{slug}", which was only ever right on the first
                # two adopters.
                "owner_url": host.post_url(plan.produced_post) if plan.produced_post_id else "",
                "evidence": list(plan.competitor_urls or []),
                "scope_includes": list(plan.scope_includes or []),
                "scope_excludes": list(plan.scope_excludes or []),
            })

        glossary_count = backlog_count = unresolved_urls = 0
        if not opts["skip_glossary"]:
            # Every live glossary term already OWNS its what-is need. cross_market=True
            # so the collision fires from any market's keyword set (a term's meaning is
            # not market-scoped), and the enrichment ledger routes the demand to the
            # term page instead of a duplicate what-is blog. Queried at export time —
            # the projection always reflects the CURRENT glossary, never a snapshot.
            for term in Tag.objects.filter(is_term=True).order_by("slug"):
                # The host owns its glossary route — see host.glossary_url. An
                # unresolvable URL is exported empty, never guessed: reconcile
                # verdicts quote these URLs, so a guess sends a human to a 404.
                url = host.glossary_url(term)
                if not url:
                    unresolved_urls += 1
                entries.append(self._glossary_entry(
                    term.name, term.slug, status="published", url=url,
                ))
                glossary_count += 1
            # Terms QUEUED for authoring (ContentPlan target=glossary_term rows
            # still pending) own their what-is need too: a what-is blog planned
            # today would cannibalize the term page authored next week.
            # owner_status=planned marks them. DB-queried at export time — the
            # unified queue is the single source, no backlog file.
            from django.utils.text import slugify

            live_slugs = {e["owner_content_id"] for e in entries}
            queued = ContentPlan.objects.filter(
                target=ContentPlan.Target.GLOSSARY_TERM,
                produced_term__isnull=True,
                status__in=(
                    ContentPlan.Status.PLANNED,
                    ContentPlan.Status.RECONCILED,
                    ContentPlan.Status.GENERATING,
                ),
            ).order_by("slug")
            for plan in queued:
                name = plan.title.strip()
                if not name:
                    continue
                slug = slugify(name)
                if f"glossary:{slug}" in live_slugs:
                    continue
                entries.append(self._glossary_entry(name, slug, status="planned", url=""))
                backlog_count += 1
        entries.sort(key=lambda e: (e["intent_frame"], e["canonical_key"], e["market"]))

        registry = {
            "version": version,
            "updated_at": "",
            "note": note,
            "entity_families": families,
            "entries": entries,
        }
        if unresolved_urls:
            # Not fatal — the registry is still correct for dedup, which keys on
            # need signatures, not URLs. But every verdict quoting one of these
            # owners will carry no link, so say it loudly once.
            self.stderr.write(self.style.WARNING(
                f"{unresolved_urls} glossary term(s) exported with NO owner_url: "
                "this host's term model does not reverse its own public URL. Set "
                'KEEL_CONTENT["glossary_url_hook"] to a dotted "(term) -> str" '
                "callable in the host adapter."
            ))
        text = json.dumps(registry, indent=2, ensure_ascii=False)
        if opts["out"]:
            Path(opts["out"]).expanduser().write_text(text + "\n", encoding="utf-8")
            self.stderr.write(
                self.style.SUCCESS(
                    f"Wrote {len(entries)} registry entr(y/ies) "
                    f"({glossary_count} live + {backlog_count} queued glossary "
                    f"what-is owner(s)) -> {opts['out']}"
                )
            )
        else:
            self.stdout.write(text)

    @staticmethod
    def _glossary_entry(name, slug, *, status, url):
        return {
            "canonical_key": f"what-is-{slug}",
            "canonical_intent": f"Understand what {name} means in trading",
            "need_signature": f"cross-market | what-is | {name}",
            "market": CROSS_MARKET,
            "cross_market": True,
            "intent_frame": "what-is",
            "entity": name,
            "entity_family": None,
            "owner": f"{name} (glossary term)",
            "owner_content_id": f"glossary:{slug}",
            "owner_kind": "glossary_term",
            "owner_status": status,
            "owner_url": url,
            "evidence": [],
            "scope_includes": [],
            "scope_excludes": [],
        }

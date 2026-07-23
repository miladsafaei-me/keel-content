"""``./manage.py content_import <path>`` — create draft Posts from generation bundles.

``<path>`` is either a single bundle ``.json`` or a directory of them. Each bundle
is the portable output of the generation Workflow (article body + SEO meta +
facets). Idempotent: a slug that already exists is **skipped** by default so a
human's edits in ``/admin-os/`` are never clobbered; pass ``--regenerate`` to
overwrite.

Four gates run here, in two tiers:

- **Always on (no bypass flag):** facet resolution against the controlled
  vocabulary, the internal-link allowlist contract (indexable targets only, no
  hand-written ``/blog/`` links, no trailing slash, one link per target), the
  intent-gate verdict (an ``intent_gate.satisfied == false`` bundle is blocked —
  ``--allow-unsatisfied`` imports it anyway, surfaced as a warning), and figure
  integrity (marker ↔ entry ↔ file ↔ alt/caption coherence; the separate
  at-least-one-figure floor on blog bundles is bypassed by ``--allow-no-figures``).
- **Skippable:** the deterministic content lint (``--no-lint``: meta lengths /
  takeaway count / inline style / trade-hex — plus the overlap>=75 batch block and
  the no-stats warnings) and the quality rubric (``--no-quality-gate``: R1–R6 hard
  rules from ``core.quality_rubric``, the same checks ``content_quality_gate``
  runs standalone).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.adapters import get_adapter

# Resolve the configured publisher adapter (default: the reference SignalBots adapter).
_adapter = get_adapter()
internal_link_violations = _adapter.internal_link_violations
publish_from_bundle = _adapter.publish_from_bundle
unresolved_required_facets = _adapter.unresolved_required_facets

Post = host.post_model()
from keel_content.core.bundle_lint import lint_bundle, lint_bundle_warnings
from keel_content.core.figures import figure_violations, normalize_figures
from keel_content.core.images import image_violations, normalize_images
from keel_content.core.quality_rubric import check_bundle, cross_checks
from keel_content.core.text_normalize import normalize_bundle


class Command(BaseCommand):
    help = "Import generation bundles as draft blog posts (with facets + SEO meta)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="A bundle .json file or a directory of bundles.")
        parser.add_argument(
            "--regenerate",
            action="store_true",
            help="Overwrite posts whose slug already exists (default: skip them).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing to the DB.",
        )
        parser.add_argument(
            "--no-lint",
            action="store_true",
            help="Skip the deterministic content lint (meta length / inline style / "
            "takeaway count / trade-hex), the overlap>=75 batch block, and the "
            "no-stats warnings. Facet, internal-link, and intent-gate checks still "
            "run — they have no bypass. Not recommended.",
        )
        parser.add_argument(
            "--no-quality-gate",
            action="store_true",
            help="Skip the deterministic quality rubric (R1-R6 hard rules: dropped "
            "visuals, clamped labels, empty hero pick, fabricated rating, missing "
            "risk-warning link, off-market links). Not recommended.",
        )
        parser.add_argument(
            "--allow-unsatisfied",
            action="store_true",
            help="Import a bundle whose intent_gate verdict is satisfied=false "
            "(blocked by default). The unsatisfied verdict is still surfaced as a "
            "warning for the reviewer.",
        )
        parser.add_argument(
            "--no-hero",
            action="store_true",
            help="Do not auto-generate featured hero images for newly-created posts.",
        )
        parser.add_argument(
            "--allow-no-figures",
            action="store_true",
            help="Import a blog bundle that carries no in-article figures (blocked by "
            "default: every article ships at least one explanatory image). Figure "
            "integrity checks (marker/entry/file/alt/caption) still run — a bundle "
            "that claims figures must have coherent ones.",
        )
        parser.add_argument(
            "--no-verify-sources",
            action="store_true",
            help="Skip the live HTTP-200 check on external sources (dedupe + allowlist "
            "still run). For re-importing already-gated bundles or offline/CI runs — a "
            "since-dead link can slip through, so leave it off for fresh imports.",
        )

    _OVERLAP_BLOCK_AT = 75

    def _overlap_blocked_slugs(self, path: Path) -> dict[str, str]:
        """Read the batch's overlap-audit.json (if present) and return
        ``{slug: partner_slug}`` for every article in a pair scoring >= 75 (or with
        ``block: true``). Both members of such a pair are blocked. Missing/garbled
        audit file = no blocks (best-effort; never fails the import)."""
        if not path.is_dir():
            return {}
        audit = path / "overlap-audit.json"
        if not audit.is_file():
            return {}
        try:
            data = json.loads(audit.read_text(encoding="utf-8"))
        except Exception:
            return {}
        blocked: dict[str, str] = {}
        for pair in data.get("pairs", []) or []:
            try:
                score = float(pair.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            if not (pair.get("block") is True or score >= self._OVERLAP_BLOCK_AT):
                continue
            a, b = pair.get("a"), pair.get("b")
            if a and b:
                blocked[a], blocked[b] = b, a
        return blocked

    def _bundles(self, path: Path) -> list[Path]:
        if path.is_dir():
            # The generator writes canonical bundles as ``<content_id>.bundle.json``.
            # Prefer those; they exclude the workflow's sidecar artifacts that share
            # the dir (``overlap-audit.json``, ``*.idmap.json``). Fall back to plain
            # ``*.json`` for legacy bundles, still skipping the known sidecars so an
            # audit/idmap file is never mis-imported as a (failing) bundle.
            bundles = sorted(path.glob("*.bundle.json"))
            if bundles:
                return bundles
            return sorted(
                p for p in path.glob("*.json")
                if not p.name.endswith((".idmap.json", "-audit.json"))
            )
        if path.is_file():
            return [path]
        raise CommandError(f"path not found: {path}")

    def handle(self, *args, **opts):
        path = Path(opts["path"]).expanduser()
        regenerate = opts["regenerate"]
        dry = opts["dry_run"]
        do_lint = not opts["no_lint"]
        do_quality = not opts["no_quality_gate"]
        allow_unsatisfied = opts["allow_unsatisfied"]
        allow_no_figures = opts["allow_no_figures"]
        do_hero = not opts["no_hero"]
        verify_external = not opts["no_verify_sources"]
        files = self._bundles(path)
        if not files:
            raise CommandError(f"no bundle .json files under {path}")

        # Layer 4 at import: a pair scoring >=75 in the batch's overlap-audit.json
        # hard-blocks BOTH its articles (the human merges/differentiates, then
        # re-imports). Only when importing a directory + linting; bypassed by --no-lint.
        overlap_blocked = self._overlap_blocked_slugs(path) if do_lint else {}

        # Parse every bundle up front: the quality rubric's R9 cross-check needs the
        # whole batch, and one unreadable file must not silence the others' verdicts.
        loaded: list[tuple[Path, dict]] = []
        created = updated = skipped = failed = gate_blocked = 0
        for f in files:
            try:
                bundle = json.loads(f.read_text(encoding="utf-8"))
                bundle["slug"]
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  ! {f.name}: unreadable bundle ({exc})"))
                failed += 1
                continue
            loaded.append((f, bundle))

        # Deterministic quality rubric (same functions as `content_quality_gate`):
        # R1-R6 fails block a bundle below; R7-R10 warns are surfaced for the reviewer.
        rubric: dict[str, dict] = {}
        if do_quality and loaded:
            results = [check_bundle(b) for _, b in loaded]
            cross_checks([b for _, b in loaded], results)
            rubric = {r["slug"]: r for r in results}

        warn_count = 0
        hero_slugs: list[str] = []
        hero_specs: dict[str, dict] = {}  # slug -> bundle-authored hero spec (if any)
        for f, bundle in loaded:
            slug = bundle["slug"]

            exists = Post.all_objects.filter(slug=slug).exists()
            if exists and not regenerate:
                self.stdout.write(f"  = skip   {slug} (exists; --regenerate to overwrite)")
                skipped += 1
                continue

            # Deterministic typographic normalization runs before lint + publish so the
            # gate sees (and the DB stores) the canonicalized prose.
            normalize_bundle(bundle)

            violations: list[str] = []
            if do_lint:
                violations += lint_bundle(bundle)
                if slug in overlap_blocked:
                    violations.append(
                        f"overlap >=75 with {overlap_blocked[slug]} (resolve the duplicate, "
                        "then re-run the overlap audit or re-import with --no-lint)"
                    )
            # Safety gates below run regardless of --no-lint: a typo'd facet, an
            # off-allowlist internal link, or an unsatisfied-intent draft must never
            # slip in through the lint escape hatch.
            violations += [
                f"facet not resolvable: {e}"
                for e in unresolved_required_facets(bundle.get("facets"))
            ]
            violations += internal_link_violations(bundle)
            # Figures: integrity has no bypass (a bundle claiming figures must have
            # coherent ones); the >=1 floor applies to blog bundles and has its own
            # escape hatch for legacy/edge imports.
            violations += figure_violations(bundle, bundle_dir=f.parent)
            if (
                bundle.get("target", "blog") == "blog"
                and not normalize_figures(bundle.get("figures"))
                and not normalize_images(bundle.get("images"))
                and not allow_no_figures
            ):
                violations.append(
                    "no in-article visual — every article ships at least one "
                    "explanatory image (an NB2 photoreal image, preferred, or an "
                    "SVG figure; run the Images/Figures stage, or import anyway "
                    "with --allow-no-figures)"
                )
            # image-nb2: integrity has no bypass (markers ↔ entries, files, alt/caption)
            # and the whole-post NB2 word-budget is enforced here as a hard ceiling.
            # There is NO floor — NB2 photoreal images are optional per article.
            violations += image_violations(bundle, bundle_dir=f.parent)
            gate = bundle.get("intent_gate")
            if (
                isinstance(gate, dict)
                and gate.get("satisfied") is False
                and not allow_unsatisfied
            ):
                violations.append(
                    "intent gate UNSATISFIED — missing essentials: "
                    f"{gate.get('missing_essential') or '—'}; scope violations: "
                    f"{gate.get('scope_violations') or '—'} "
                    "(fix + re-gate, or import anyway with --allow-unsatisfied)"
                )
            r = rubric.get(slug)
            if r and r["fails"]:
                violations += [f"quality gate: {v}" for v in r["fails"]]
            if violations:
                self.stderr.write(self.style.ERROR(f"  ! {slug}: gate failed (not imported):"))
                for v in violations:
                    self.stderr.write(self.style.ERROR(f"      - {v}"))
                gate_blocked += 1
                continue

            if do_lint:
                for w in lint_bundle_warnings(bundle):
                    self.stdout.write(self.style.WARNING(f"  ! {slug}: {w}"))
                    warn_count += 1
            for w in (r["warns"] if r else []):
                self.stdout.write(self.style.WARNING(f"  ! {slug}: {w}"))
                warn_count += 1
            fig_gate = bundle.get("figure_gate")
            if isinstance(fig_gate, dict) and fig_gate.get("all_approved") is False:
                # Vision judge left figures unapproved after its one revision pass.
                # Drafts are human-reviewed anyway, so surface loudly but don't block.
                self.stdout.write(self.style.WARNING(
                    f"  ! {slug}: figure gate NOT fully approved — review the figures "
                    "in the draft preview"
                ))
                warn_count += 1

            if dry:
                self.stdout.write(f"  ~ would {'update' if exists else 'create'} {slug}")
                continue

            report_sink: dict = {}
            try:
                admin_url = publish_from_bundle(
                    bundle, report_sink, verify_external=verify_external, bundle_dir=f.parent
                )
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"  ! {slug}: publish failed: {type(exc).__name__}: {exc}")
                )
                failed += 1
                continue

            if exists:
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"  * update {slug}"))
            else:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + create {slug}"))
            # Both created and updated: --regenerate rewrites featured_image_url from
            # the bundle (blank), so a re-import can wipe a hero. attach_hero_to_post
            # is force=False (idempotent), so it only fills posts that lack one.
            hero_slugs.append(slug)
            if isinstance(bundle.get("hero"), dict):
                hero_specs[slug] = bundle["hero"]
            self.stdout.write(f"      admin: {admin_url}")
            warn_count += self._report_drops(slug, report_sink)

        if do_hero and hero_slugs and not dry:
            self._generate_heroes(hero_slugs, hero_specs)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {created} created, {updated} updated, {skipped} skipped, "
                f"{gate_blocked} gate-blocked, {failed} failed (of {len(files)} bundles)"
            )
        )
        if warn_count:
            self.stdout.write(
                self.style.WARNING(f"  ({warn_count} non-blocking warning(s) — review above)")
            )

    def _report_drops(self, slug: str, sink: dict) -> int:
        """Surface anything the publish silently dropped — external sources, internal
        links, or components — so a reviewer sees a post shipped with a gap. These were
        previously computed and discarded (logged only). Returns the count surfaced."""
        n = 0
        ext = sink.get("external")
        for d in getattr(ext, "dropped", []) or []:
            self.stdout.write(self.style.WARNING(f"      ! dropped source: {d.url or '(no url)'} — {d.reason}"))
            n += 1
        intr = sink.get("internal")
        for s in getattr(intr, "skipped", []) or []:
            self.stdout.write(self.style.WARNING(f"      ! internal link not placed: '{s.anchor}' — {s.reason}"))
            n += 1
        figs = sink.get("figures")
        for fid in getattr(figs, "unmatched_markers", []) or []:
            self.stdout.write(self.style.WARNING(
                f"      ! figure marker [[FIGURE:{fid}]] had no usable entry/file — stripped"
            ))
            n += 1
        for fid in getattr(figs, "unplaced_figures", []) or []:
            self.stdout.write(self.style.WARNING(
                f"      ! figure '{fid}' has no [[FIGURE:{fid}]] marker in the body"
            ))
            n += 1
        comp = sink.get("components") or {}
        for msg in comp.get("failed", []) or []:
            self.stdout.write(self.style.WARNING(f"      ! component dropped: {msg}"))
            n += 1
        for msg in comp.get("pruned", []) or []:
            self.stdout.write(self.style.WARNING(f"      ! component {msg}"))
            n += 1
        for msg in comp.get("clamped", []) or []:
            self.stdout.write(self.style.WARNING(f"      ! component {msg} — shorten the label at the source"))
            n += 1
        videos = sink.get("video_embeds")
        if videos is not None:
            for rid in getattr(videos, "kept_on_trust", []) or []:
                self.stdout.write(self.style.WARNING(
                    f"      ! video '{rid}' kept on trust (oEmbed unreachable) — "
                    "verify it plays in the draft preview"
                ))
                n += 1
            for rid, reason in getattr(videos, "downgraded", []) or []:
                self.stdout.write(self.style.WARNING(
                    f"      ! video '{rid}' downgraded to an asset request — {reason}"
                ))
                n += 1
        assets = sink.get("asset_requests")
        if assets is not None:
            if getattr(assets, "placed", None):
                self.stdout.write(self.style.WARNING(
                    f"      ! needs human assets: {len(assets.placed)} placeholder(s) in the "
                    "draft — filter 'Needs assets' in /admin-os/blog/"
                ))
                n += 1
            for rid in getattr(assets, "unmatched_markers", []) or []:
                self.stdout.write(self.style.WARNING(
                    f"      ! asset marker [[ASSET:{rid}]] has no asset_requests entry"
                ))
                n += 1
            for rid in getattr(assets, "unplaced_requests", []) or []:
                self.stdout.write(self.style.WARNING(
                    f"      ! asset request '{rid}' has no [[ASSET:{rid}]] marker in the body"
                ))
                n += 1
        return n

    def _generate_heroes(self, slugs: list[str], hero_specs: dict[str, dict] | None = None) -> None:
        """Auto-attach an SVG+WebP hero to each touched post (best-effort).

        Makes 'a draft is always delivered with its featured image' a property of
        ingest itself, not a step a human has to remember. When a bundle carried an
        author-designed ``hero`` spec, that bespoke, content-matched visual is used
        (force-overwrite); otherwise the deterministic ``derive_spec`` fills any post
        that lacks a hero. A hero failure never fails the import.
        """
        hero_specs = hero_specs or {}
        from keel_content.core.hero.pipeline import (
            attach_hero_to_post,
            render_and_store,
            spec_from_dict,
        )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"hero images ({len(slugs)} post(s)):"))
        for post in Post.all_objects.filter(slug__in=slugs):
            try:
                entry = hero_specs.get(post.slug)
                if entry:
                    spec = spec_from_dict(entry, title=post.title, category=getattr(post.category, "name", "") or "")
                    url = render_and_store(spec, post.slug)
                    post.featured_image_url = url
                    post.save(update_fields=["featured_image_url"])
                    kind = "freeform" if entry.get("svg_element") else f"{entry.get('style')}/{entry.get('motif')}"
                    self.stdout.write(self.style.SUCCESS(f"  hero  {post.slug}  ->  {kind}"))
                    continue
                url = attach_hero_to_post(post, force=False)
                if url:
                    self.stdout.write(self.style.SUCCESS(f"  hero  {post.slug}  ->  {url}"))
                else:
                    self.stdout.write(f"  skip  {post.slug} (already has a hero)")
            except Exception as exc:  # noqa: BLE001 -- hero is best-effort, never fatal
                self.stderr.write(self.style.WARNING(f"  ! hero {post.slug}: {type(exc).__name__}: {exc}"))

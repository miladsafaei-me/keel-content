"""``./manage.py anchor_registry_apply --verdicts <path>`` — resolve the anchor
conflicts ``anchor_registry_report`` found, by rewriting the minority links.

The report half of this pair (``core/anchor_registry.py``) is deliberately
read-only: it says which anchor phrases resolved to more than one target, and
stops. Choosing WHICH target an anchor belongs to is a judgement about search
intent that no scan can make, and rewriting anchors already live in published
bodies changes on-page signals — so the choice is made outside, reviewed, and
arrives here as a verdicts file. This command only applies it.

Verdicts shape (the report's conflict entry plus a chosen winner)::

    {"verdicts": [
      {"anchor": "خرید ملک در استانبول",
       "winner": "/sale/istanbul",
       "losers": [{"target_path": "/sale", "source_slugs": ["a-post", "b-post"]}]}
    ]}

Rules it enforces rather than trusts:

* **An anchor is matched by its NORMALIZED form**, through the same normalizer the
  registry scans with — so a verdict written against one orthographic variant still
  finds the others. Two of the consuming projects publish Persian, where the same
  phrase routinely differs by yeh/kaf encoding or a stray ZWNJ.
* **A rewrite that would point a post at itself unwraps the link instead.** When the
  winner IS the source article, the article is the target, not a link to it — and a
  self-link is the one edge every other pass in this package already refuses.
* **A link that is not there is reported, never invented.** A verdict naming a
  source/anchor pairing the body does not carry means the corpus moved since the
  report ran; that is worth seeing, not worth guessing at.

Same write posture as ``content_relink apply``: ``--backup`` is mandatory without
``--dry-run``, the host's write hooks are resolved before the first row, and
``content_raw`` is rebuilt and re-rendered exactly as the publish path does it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.anchor_registry import _target_key, normalize_anchor
from keel_content.core.preflight import require_write_hooks

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _rewrite(body: str, anchor_norm: str, loser_key: str, winner: str | None) -> tuple[str, int]:
    """Repoint (or, when ``winner`` is None, unwrap) matching links in ``body``.

    Returns ``(new_body, count)``. Only links whose normalized anchor AND whose
    normalized target both match are touched, so an unrelated link that happens to
    share one of the two is never rewritten.
    """
    hits = 0

    def repl(m):
        nonlocal hits
        anchor, target = m.group(1).strip(), m.group(2).strip()
        if normalize_anchor(anchor) != anchor_norm or _target_key(target) != loser_key:
            return m.group(0)
        hits += 1
        return anchor if winner is None else f"[{anchor}]({winner})"

    return _MD_LINK_RE.sub(repl, body or ""), hits


class Command(BaseCommand):
    help = "Apply adjudicated anchor-conflict verdicts onto published post bodies."

    def add_arguments(self, parser):
        parser.add_argument("--verdicts", required=True, help="Path to the verdicts JSON.")
        parser.add_argument("--backup", default="", help="Write originals here before mutating.")
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")

    def handle(self, *args, **opts):
        path = Path(opts["verdicts"]).expanduser()
        if not path.is_file():
            raise CommandError(f"verdicts file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"unreadable JSON: {exc}")
        verdicts = data.get("verdicts") if isinstance(data, dict) else data
        if not isinstance(verdicts, list) or not verdicts:
            raise CommandError('expected {"verdicts": [...]} with at least one entry')

        dry = opts["dry_run"]
        if not dry and not opts["backup"]:
            raise CommandError("--backup PATH is required (omit only with --dry-run)")
        if not dry:
            require_write_hooks("prepare_storage_hook", "refresh_rendered_hook")

        Post = host.post_model()
        # slug -> the edits that post needs, collected across every verdict first so
        # a post named by two verdicts is saved once, not twice.
        planned: dict[str, list[tuple[str, str, str]]] = {}
        for v in verdicts:
            winner = (v.get("winner") or "").strip()
            anchor = (v.get("anchor") or "").strip()
            if not anchor or not winner.startswith("/"):
                raise CommandError(f"verdict needs an anchor and a site-relative winner: {v!r}")
            for loser in v.get("losers") or []:
                loser_path = (loser.get("target_path") or "").strip()
                if not loser_path:
                    continue
                for slug in loser.get("source_slugs") or []:
                    planned.setdefault(slug, []).append((anchor, loser_path, winner))

        posts = {p.slug: p for p in Post.objects.filter(slug__in=list(planned))}
        missing = sorted(set(planned) - set(posts))
        for slug in missing:
            self.stderr.write(f"skip: no post for slug {slug!r}")

        backup: dict[str, str] = {}
        totals = {"posts": 0, "repointed": 0, "unwrapped": 0, "not_found": 0, "missing_posts": len(missing)}
        for slug, edits in sorted(planned.items()):
            post = posts.get(slug)
            if post is None:
                continue
            original = post.content_markdown_source or ""
            body, repointed, unwrapped = original, 0, 0
            for anchor, loser_path, winner in edits:
                self_link = _target_key(host.post_url(post)) == _target_key(winner)
                body, hits = _rewrite(
                    body, normalize_anchor(anchor), _target_key(loser_path),
                    None if self_link else winner,
                )
                if not hits:
                    totals["not_found"] += 1
                    self.stderr.write(
                        f"  {slug}: no live link for {anchor!r} -> {loser_path!r}; corpus "
                        "moved since the report ran"
                    )
                elif self_link:
                    unwrapped += hits
                else:
                    repointed += hits
            if body == original:
                continue
            totals["posts"] += 1
            totals["repointed"] += repointed
            totals["unwrapped"] += unwrapped
            self.stdout.write(
                f"{slug}: {repointed} repointed, {unwrapped} unwrapped"
                + (" [dry-run]" if dry else "")
            )
            if dry:
                continue
            backup[slug] = original
            post.content_markdown_source = body
            post.content_raw = host.prepare_pipeline_content_for_storage(body)
            post.save(update_fields=["content_markdown_source", "content_raw"])
            host.refresh_article_rendered(post)

        if backup:
            Path(opts["backup"]).expanduser().write_text(
                json.dumps(backup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self.stderr.write(f"originals -> {opts['backup']}")
        self.stdout.write(self.style.SUCCESS(json.dumps(totals)))

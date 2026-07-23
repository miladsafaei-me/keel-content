"""``./manage.py content_outbound_domains`` — site-wide outbound-domain histogram.

Counts the external domains linked from blog posts (further-reading sources plus
any other outbound anchor) and prints a concentration report. This is the
cross-run companion to the per-run ``externalDomains`` histogram the generate
workflow returns: run it on prod after importing a batch to watch the outbound
profile stay diverse instead of silently collapsing back onto one or two hosts.

Read-only — safe to run on prod at any time.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from django.core.management.base import BaseCommand

from keel_content import host

Post = host.post_model()

_MD_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_HREF_RE = re.compile(r"href=[\"'](https?://[^\"']+)")

# Above this share of all outbound links on one host, the profile reads as
# concentrated again — the state the diversity work exists to prevent.
_CONCENTRATION_WARN_PCT = 40.0


class Command(BaseCommand):
    help = "Print the outbound external-link domain histogram across blog posts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--published-only",
            action="store_true",
            help="Only count posts with status=published.",
        )

    def handle(self, *args, **opts):
        qs = Post.objects.filter(is_deleted=False)
        if opts["published_only"]:
            qs = qs.filter(status="published")

        counts: Counter[str] = Counter()
        scanned = posts_with_links = 0
        for post in qs.iterator():
            scanned += 1
            text = post.content_markdown_source or post.content_raw or ""
            urls = set(_MD_LINK_RE.findall(text)) | set(_HREF_RE.findall(text))
            hosts = []
            for url in urls:
                host = (urlparse(url).hostname or "").lower()
                host = host[4:] if host.startswith("www.") else host
                if host and "signalbot" not in host:
                    hosts.append(host)
            if hosts:
                posts_with_links += 1
            counts.update(hosts)

        total = sum(counts.values())
        self.stdout.write(f"posts scanned: {scanned} ({posts_with_links} with external links)")
        self.stdout.write(f"external links: {total} across {len(counts)} distinct domains")
        if not total:
            return
        self.stdout.write("")
        for host, cnt in counts.most_common():
            self.stdout.write(f"{cnt:5d}  {100 * cnt / total:5.1f}%  {host}")

        top_host, top_cnt = counts.most_common(1)[0]
        top_share = 100 * top_cnt / total
        if top_share > _CONCENTRATION_WARN_PCT:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"concentration: {top_host} carries {top_share:.0f}% of all outbound "
                    f"links (> {_CONCENTRATION_WARN_PCT:.0f}%) — steer upcoming batches "
                    "toward other authoritative domains"
                )
            )

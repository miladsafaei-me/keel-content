"""Count an images attempt against the posts it did not finish, and retire the hopeless.

The autopilot images ONE cluster per run and must not start the next cluster until
that one is clear. That rule is only safe if "clear" can be reached: a post the
machine cannot draw would otherwise hold the cycle forever — which is exactly how
a single unproducible glossary row once blocked all article production for five
hours.

So every images run ends here. Each post still owed visuals in the scope that was
just attempted gets one strike; a post that has used its budget is marked blocked,
leaves the queue, and is reported. Nothing is deleted and no body is touched — the
post keeps its work order and a human can put it back with ``--unblock``.

    manage.py flag_stuck_visuals --cluster crypto-trading-bots-automation --json
    manage.py flag_stuck_visuals --list
    manage.py flag_stuck_visuals --unblock some-post-slug

Run it ONLY after a run that actually attempted the scope. A run killed by a closed
token window attempted nothing, and charging it a strike would retire good posts.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from keel_content.core import visual_queue
from keel_content.host import content_plan_model, post_model


class Command(BaseCommand):
    help = "Charge an attempt to posts still missing visuals; block the ones out of budget."

    def add_arguments(self, parser):
        parser.add_argument("--cluster", help="only the posts produced by this topic cluster")
        parser.add_argument("--slug", action="append", default=[],
                            help="only these slugs (repeatable)")
        parser.add_argument("--max-attempts", type=int,
                            default=visual_queue.DEFAULT_MAX_ATTEMPTS,
                            help="attempts a post may burn before it is blocked "
                                 f"(default {visual_queue.DEFAULT_MAX_ATTEMPTS})")
        parser.add_argument("--reason", default="the images pass ran and did not finish this post",
                            help="recorded on the block marker, for the human who reads it later")
        parser.add_argument("--json", action="store_true", help="emit one JSON line, for the driver")
        parser.add_argument("--list", action="store_true",
                            help="report currently blocked posts and change nothing")
        parser.add_argument("--unblock", action="append", default=[],
                            help="clear the block on this slug and restore its attempt budget "
                                 "(repeatable); changes nothing else")

    def handle(self, *args, **opts):
        Post = post_model()

        if opts["unblock"]:
            restored = []
            for slug in opts["unblock"]:
                post = Post.all_objects.filter(slug=slug).first()
                if post is None:
                    raise CommandError(f"no post with slug {slug}")
                if visual_queue.unblock(post):
                    restored.append(slug)
            return self._report(opts, {"unblocked": restored})

        if opts["list"]:
            blocked = [
                {"slug": p.slug, **visual_queue.block_note(p)}
                for p in visual_queue.blocked_posts(Post).order_by("slug")
            ]
            return self._report(opts, {"blocked": blocked, "count": len(blocked)})

        qs = visual_queue.pending_posts(Post)
        if opts["slug"]:
            qs = qs.filter(slug__in=opts["slug"])
        if opts["cluster"]:
            ids = visual_queue.post_ids_for_cluster(content_plan_model(), opts["cluster"])
            qs = qs.filter(id__in=ids)

        charged, retired = [], []
        for post in qs.order_by("slug"):
            total = visual_queue.record_attempt(post, save=False)
            if total >= opts["max_attempts"]:
                visual_queue.block(
                    post, reason=opts["reason"], attempts_used=total, save=False
                )
                retired.append(post.slug)
            else:
                charged.append({"slug": post.slug, "attempts": total})
            post.save(update_fields=["pending_visuals"])

        payload = {
            "cluster": opts["cluster"],
            "attempted": len(charged) + len(retired),
            "retried_next_run": charged,
            "blocked_now": retired,
            "still_queued": visual_queue.pending_posts(Post).count(),
        }
        return self._report(opts, payload)

    def _report(self, opts, payload: dict):
        if opts["json"]:
            self.stdout.write(json.dumps(payload))
            return
        for key, value in payload.items():
            self.stdout.write(f"{key}: {value}")

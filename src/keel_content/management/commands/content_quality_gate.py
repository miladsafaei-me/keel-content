"""Cluster-quality acceptance gate — thin CLI over ``core.quality_rubric``.

The rubric itself (R1–R10, HARD vs SOFT, and why each rule exists) lives in
``content_pipeline/core/quality_rubric.py`` — the same functions ``content_import``
runs automatically at ingest, so this command and the import gate can never drift.
Use this standalone form to pre-check a bundle directory *before* shipping it to
prod (or to re-check after hand-edits):

    python manage.py content_quality_gate <bundle-dir> [--json out.json] [--strict]

FAILs exit non-zero (the same bundles ``content_import`` would block); WARNs are
advisory. ``--strict`` promotes every WARN to a FAIL.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core.quality_rubric import check_bundle, cross_checks


class Command(BaseCommand):
    help = "Deterministic cluster-quality acceptance gate over a bundle directory."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Directory of *.bundle.json files (or one bundle).")
        parser.add_argument("--json", default="", help="Write the full report JSON here.")
        parser.add_argument(
            "--strict", action="store_true", help="Promote every WARN to a FAIL."
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        bundles = self._load(path)
        if not bundles:
            raise CommandError(f"no bundles found under {path}")

        results = [check_bundle(b) for b in bundles]
        cross_checks(bundles, results)

        strict = opts["strict"]
        report = {"posts": [], "summary": {}}
        n_fail = n_warn = 0
        for r in results:
            fails = list(r["fails"])
            warns = list(r["warns"])
            if strict:
                fails += [f"(strict) {w}" for w in warns]
                warns = []
            status = "FAIL" if fails else ("WARN" if warns else "PASS")
            n_fail += bool(fails)
            n_warn += bool(warns)
            report["posts"].append(
                {"slug": r["slug"], "status": status, "fails": fails, "warns": warns}
            )

        report["summary"] = {
            "total": len(results),
            "failed": n_fail,
            "warned": n_warn,
            "passed": len(results) - n_fail - n_warn,
        }

        for p in report["posts"]:
            style = (
                self.style.ERROR if p["status"] == "FAIL"
                else self.style.WARNING if p["status"] == "WARN"
                else self.style.SUCCESS
            )
            self.stdout.write(style(f"[{p['status']}] {p['slug']}"))
            for f in p["fails"]:
                self.stdout.write(self.style.ERROR(f"    FAIL  {f}"))
            for w in p["warns"]:
                self.stdout.write(self.style.WARNING(f"    warn  {w}"))

        s = report["summary"]
        self.stdout.write(
            f"\nGATE: {s['passed']} pass · {s['warned']} warn · {s['failed']} FAIL "
            f"(of {s['total']})"
        )
        if opts["json"]:
            Path(opts["json"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.stdout.write(f"report → {opts['json']}")

        if n_fail:
            raise CommandError(f"{n_fail} post(s) failed the quality gate.")

    def _load(self, path: Path) -> list[dict]:
        files = (
            sorted(path.glob("*.bundle.json"))
            if path.is_dir()
            else [path] if path.is_file() else []
        )
        out = []
        for f in files:
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                out.append({"slug": f.name, "_load_error": str(exc)})
        return out

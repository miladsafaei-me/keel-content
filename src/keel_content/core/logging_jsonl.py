"""Per-article JSONL logger: one event per line, written to <content_id>/log.jsonl.

Used to record step-by-step progress, token usage, and errors so an article's
full provenance can be inspected after the fact.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths


def _path(content_id: str) -> Path:
    return paths.article_dir(content_id) / "log.jsonl"


def log_event(content_id: str, event: str, **payload: Any) -> None:
    p = _path(content_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

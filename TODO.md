# TODO

This file is the single source of truth for pending, follow-up, and deferred work on this project. See CLAUDE.md for the tracking rule.

Guidelines:
- Add a task here as soon as it's identified — with priority, prerequisites/dependencies, and enough context to pick it up cold.
- Group by priority: P0 (urgent / blocking / production risk), P1 (next up), P2 (backlog / nice-to-have).
- Note real dependencies explicitly ("Blocked by: ...", "Requires: ...").
- Delete a task from this file the moment it's done. This file only ever holds what's left.

## P1 — Next up
- [ ] README.md's "Status" section (bottom of the file) is frozen at v0.1.5 while `pyproject.toml` is at v0.1.49 (44 releases of drift, last touched commit 8553b66 on 2026-07-29). Rewrite it to describe current behavior instead of the v0.1.4/v0.1.5 changelog narrative. While there, re-verify the section's one open claim — that the default `agent-author-brief.md` and `cluster-internal-links.md` prompts still describe the pre-v0.1.4 linking flow — against the prompts as they exist today (they've been edited three times since: ee5adb4 modularized the brief, 0987e5c added component-fit discipline, ac38fbc added the external-links gate), and either resolve the misalignment or restate the follow-up accurately.

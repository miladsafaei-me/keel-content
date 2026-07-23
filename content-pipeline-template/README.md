# content-pipeline/ — per-project template

Copy this directory into your project (next to `backend/`, or anywhere and point
`CONTENT_PIPELINE_ROOT` at it). It holds the **project-specific** inputs keel-content
reads at runtime — everything the engine deliberately does not hardcode.

Fill in:

- **`config.json`** — the slim config governing the legacy glossary-gap API path
  (model / max-tokens / enabled). The generator workflow does not read it.
- **`prompts/`** — your project's agent briefs. keel-content ships a generic default set
  in the package (`keel_content/prompts_default/`); anything you place here overrides a
  default of the same name. This is where your brand voice, editorial rules, market list,
  and partner model live. Use the `{{PLACEHOLDER}}` tokens the defaults expect.
- **`EXTERNAL-DOMAINS.md`** — the human-readable mirror of your outbound fast-lane. The
  live list is configured via `KEEL_CONTENT["external_domains"]`; keep this doc in sync.
- **`content/`** — per-run artifact output (git-ignored). Created on demand.

Nothing in this directory is imported as code; it is data + prompts the engine consumes.

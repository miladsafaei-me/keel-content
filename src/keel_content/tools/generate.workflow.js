export const meta = {
  name: 'generate-blog-from-worklist',
  description:
    'Generate one project blog draft per worklist spec — one fresh agent each, each writing a self-contained bundle JSON for content_import. Then an independent link-relevance gate reviews every draft\'s external sources, and a cluster-linking pass wires blog→blog internal links within each topic cluster once all its articles exist. Independent contexts (no chaining) so every article gets a fresh strategist read.',
  phases: [
    { title: 'Generate', detail: 'one fresh agent per content spec' },
    { title: 'Intent gate', detail: 'adversarial reviewer checks each draft actually satisfies its search intent + scope; one revision on fail — runs FIRST so the prose is settled before it is polished and before links + visuals are judged against it' },
    { title: 'Editorial gate', detail: 'independent reader judges how the FINAL article READS (flow, cohesion, voice, seams from the stitched-together assembly); one flow-only revision on fail — runs after the intent gate so it polishes the settled prose' },
    { title: 'Relevance gate', detail: 'independent reviewer fetches + judges each draft\'s external links AGAINST THE FINAL body (after any intent-gate + editorial-gate revision)' },
    { title: 'Figures', detail: 'a separate agent draws each article\'s in-article figures (SVG -> WebP) from the author\'s figure_requests after the body is FINAL; a vision judge gates them, one revision on fail' },
    { title: 'Images', detail: 'a separate agent renders the OPTIONAL in-article image-nb2 photoreal images (Gemini scene + SVG text overlay -> WebP) from the author\'s image_requests, within the 2-per-1000-words budget; a vision judge gates them, one revision on fail' },
    { title: 'Hero', detail: 'a separate agent designs each article\'s bespoke featured-image SVG after the body is FINAL (post intent-gate revision)' },
    { title: 'Cluster links', detail: 'one planner per topic cluster wires blog→blog links across its finished articles' },
    { title: 'Overlap audit', detail: 'Layer 4 — flag near-duplicate article pairs; pairs >=75 hard-block at import' },
    { title: 'Glossary gap', detail: 'flag important terms the batch relies on that are missing from the glossary' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.contents  : the worklist "contents" array (read the worklist JSON in the
//                    session and hand the parsed array in — the workflow sandbox
//                    has no filesystem, so it cannot read the file itself).
//   args.outDir    : absolute dir to write <content_id>.bundle.json into.
//   args.briefPath : absolute path to content-pipeline/prompts/agent-author-brief.md.
//   args.repoRoot  : absolute repo/worktree root (for BLOG.md, prompts/, cp-* css).
//   args.indexableUrls : array of currently-indexable site paths (fetch fresh from
//                    prod: Landing.is_indexable=True). Agents may link ONLY to these
//                    (+ each other's slugs). REQUIRED for a real batch — content_import
//                    hard-blocks off-allowlist internal links, so generating without
//                    the live list wastes the whole run. Omittable only with
//                    args.dryRun: true (throwaway runs never imported to prod).
//   args.dryRun    : optional; allows an empty indexableUrls for a throwaway run.
//   args.gatePath  : optional absolute path to content-pipeline/prompts/link-relevance-gate.md
//                    (defaults to <repoRoot>/content-pipeline/prompts/link-relevance-gate.md).
//   args.limit     : optional cap on how many specs to run this batch.

// args should arrive as a live JSON object, but some callers/harnesses hand it in
// JSON-encoded as a string — accept either so the runbook is robust across sessions.
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const all = (A && Array.isArray(A.contents) && A.contents) || []
const outDir = (A && A.outDir) || ''
const briefPath = (A && A.briefPath) || ''
const repoRoot = (A && A.repoRoot) || ''
const indexableUrls = (A && Array.isArray(A.indexableUrls) && A.indexableUrls) || []
const gatePath = (A && A.gatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/link-relevance-gate.md` : '')
const heroPath = (A && A.heroPath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/author-hero.md` : '')
const intentGatePath = (A && A.intentGatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/intent-satisfaction-gate.md` : '')
const editorialGatePath = (A && A.editorialGatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/editorial-quality-gate.md` : '')
const figuresPath = (A && A.figuresPath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/author-figures.md` : '')
const figureJudgePath = (A && A.figureJudgePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/figure-judge.md` : '')
const figureStylePath = (A && A.figureStylePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/figure-style-guide.md` : '')
// Renders (figure_raster / nb2_image) run ON THE SERVER via this wrapper: it
// stages the bundle dir up, renders inside an isolated memory-capped container,
// and copies the rendered files back — so the box driving generation needs no
// local Linux render tooling (only ssh + scp). @W in the argv -> the staged dir.
const renderPath = (A && A.renderPath) || (repoRoot ? `${repoRoot}/tools/content_pipeline/render_on_server.sh` : '')
const imagesPath = (A && A.imagesPath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/author-images.md` : '')
const imageJudgePath = (A && A.imageJudgePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/image-judge.md` : '')
// Layer 3 (CANNIBALIZATION-PREVENTION-PLAN.md §3) rides on each spec itself: the
// reconcile pass writes scope_includes / scope_excludes / canonical_owner onto every
// row, and the author brief's "One intent, one post" section enforces them as a hard
// contract (explanation → one line + the cluster-link pass adds the link; tool → embed
// the one shared cp-* component inline). No separate cluster-level asset map is
// injected — the overlap audit (Layer 4) + import block remain the safety net.
if (!all.length) {
  throw new Error('args.contents is empty — read the worklist JSON and pass its "contents" array as args.contents')
}
if (!outDir || !briefPath || !repoRoot) {
  throw new Error('pass absolute args.outDir, args.briefPath and args.repoRoot')
}
if (!indexableUrls.length && !(A && A.dryRun)) {
  throw new Error(
    'args.indexableUrls is empty — agents would have no link allowlist and content_import ' +
    'hard-blocks off-allowlist internal links, wasting the whole batch. Fetch the live ' +
    'Landing.is_indexable=True paths from prod and pass them; for a throwaway run pass args.dryRun: true.'
  )
}
const contents = A.limit ? all.slice(0, A.limit) : all

phase('Generate')
log(`generating ${contents.length} blog draft(s) — one fresh, independent agent each`)

const buildPrompt = (spec) => {
  // YouTube-transcript route: when the spec carries a transcript, it is the PRIMARY
  // source the article is written from (not competitor URLs). Pull it out of the SPEC
  // dump (it can be thousands of words) and present it once, clearly delimited, at the
  // end — with the rewrite/compliance rules the author-brief expands on.
  const transcript = (spec.source_transcript || '').trim()
  // Large transcripts are passed by FILE PATH (source_transcript_path) instead of
  // inline, so the worklist/args stay small; the agent reads the file itself.
  const transcriptPath = (spec.source_transcript_path || '').trim()
  const hasTranscript = !!(transcript || transcriptPath)
  const specForDump = { ...spec }
  delete specForDump.source_transcript
  delete specForDump.source_transcript_path
  return [
    'Generate ONE project blog article from the spec below, following the author brief IN FULL.',
    '',
    `1. Read the author brief first: ${briefPath}`,
    `2. repoRoot for every other read (BLOG.md, BUSINESS.md, CLAUDE.md, and the component catalog at content-pipeline/components/CATALOG.md): ${repoRoot}.`,
    hasTranscript
      ? '3. THIS IS A YOUTUBE-SOURCED ARTICLE. Your PRIMARY source material is the video transcript ' + (transcriptPath ? `— READ it FIRST from this file: ${transcriptPath}` : 'at the END of this prompt') + '. Write the article FROM it. Read the author brief\'s "YouTube-transcript-sourced articles" section and follow it exactly: re-explain the ideas in ORIGINAL prose and project\' voice (NEVER republish the transcript verbatim or near-verbatim), keep only what is accurate, and DROP the creator\'s self-promotion, competitor products, affiliate pitches, and any unverifiable win-rate / "risk-free" / "guaranteed" claims (reframe such claims skeptically, in our voice). The source video is auto-attached to the post and embedded by the template, so do NOT add a [[VIDEO:...]] embed of the SOURCE video yourself. Any competitor_urls in the spec are only secondary SERP context for what readers expect.'
      : '3. Use your web-research tools to study the competitor URLs and the topic. If WebSearch/WebFetch are not already loaded, load them via ToolSearch first.',
    '4. Do the FULL job for THIS spec only, in your own fresh context: intent-first SERP research (discard off-intent competitor URLs into the report), strategist outline, a comprehensive draft (length follows the intent — NO word-count target, never padding), code-in-page visuals DERIVED from this article\'s intent (no fixed count, no one-of-each quota; legible in BOTH light and dark), self-critique, then engagement-formatted final assembly. Do NOT author the hero — a separate stage designs it after your draft exists.',
    `5. Write the bundle JSON to EXACTLY: ${outDir}/${spec.content_id}.bundle.json`,
    `   - slug MUST be "${spec.slug}" verbatim (stable identity).`,
    '   - Carry the facets through from the spec; extend facets.glossary_terms with any glossary terms you actually linked.',
    '   - Match the bundle shape in the author brief precisely (content_import depends on it).',
    '6. Return ONLY the compact one-line JSON status described in the brief — never the article body.',
    '',
    'INDEXABLE_URLS — internal links in the body may point ONLY to a path in this list',
    '(no trailing slash; each distinct target at most once). A path not in this list is',
    'noindex/nonexistent — do not link it. These are glossary + landing pages only.',
    'Do NOT link other blog posts (/blog/<slug>) yourself: you cannot see the sibling',
    'articles, so any blog slug you guess would be wrong. Blog→blog cross-links are added',
    'automatically by the cluster-linking pass after the whole cluster is generated.',
    indexableUrls.length ? indexableUrls.join('\n') : '(none provided — avoid internal links you cannot verify)',
    '',
    'SPEC:',
    JSON.stringify(specForDump, null, 2),
    ...(transcript
      ? [
          '',
          'SOURCE TRANSCRIPT — primary material to REWRITE into an original article (never copy verbatim):',
          '>>>>> TRANSCRIPT START',
          transcript,
          '<<<<< TRANSCRIPT END',
        ]
      : []),
  ].join('\n')
}

// Independent link-relevance reviewer for one already-written bundle: fetches each
// proposed external source, judges relevance to THIS article + anchor honesty, and
// rewrites the bundle's external_sources in place. The 200 gate at ingest still runs
// downstream — this stage adds the on-topic/honest-anchor judgement code can't make.
const buildGatePrompt = (spec) =>
  [
    'Review and tighten the EXTERNAL SOURCES of ONE already-generated project blog draft.',
    '',
    `1. Read the link-relevance gate brief IN FULL: ${gatePath}`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read it. The article = its title/h1/meta_description + body_markdown.',
    '   The proposed links = its "external_sources" array.',
    '3. For EACH item in external_sources: WebFetch the url (load WebFetch via ToolSearch',
    '   first if needed), then judge relevance to THIS article + anchor honesty per the brief.',
    '   Keep (anchor rewritten if it over-claims) or drop. Drop generic homepages/section hubs.',
    '4. Overwrite the bundle\'s "external_sources" with ONLY the kept (anchor-corrected) items.',
    '   Leave every other field untouched. Write the bundle back to the SAME path.',
    `   slug MUST stay "${spec.slug}".`,
    '5. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')

// Hero authoring for one already-written bundle: runs AFTER the intent gate (and its
// one revision pass) so the featured-image SVG is drawn to match the FINAL body, not a
// draft that may still be revised. Reads the bundle, designs the hero per
// author-hero.md, and patches a `hero` object into the bundle in place. Separated from
// generation so the writing agent never spends context on SVG geometry.
const buildHeroPrompt = (spec) =>
  [
    'Author the bespoke featured-image hero SVG for ONE already-generated project blog article.',
    '',
    `1. Read the hero-authoring brief IN FULL: ${heroPath}`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read it — its h1 + title + meta_description + body_markdown tell you what to draw.',
    '3. Design the hero per the brief, then patch a "hero" object ({svg_element, head}) into',
    '   that bundle, leaving every other field untouched. Write the bundle back to its SAME path.',
    `   slug MUST stay "${spec.slug}".`,
    '4. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')

// Figure authoring + vision gate for one already-written bundle: runs AFTER the
// intent gate (body FINAL) and BEFORE the hero, sequential in the same per-article
// chain (both patch the bundle file — never concurrently). The author agent draws
// every requested figure as an SVG, rasterizes to PNG+WebP via the tracked script,
// and self-checks the pixels; an independent vision judge then gates each figure
// (grounded / comprehension / legible / framework / earns-its-place) with ONE
// revision pass on fail. Separated from generation so the writing agent never
// spends context on geometry — mirrors the hero split.
const buildFiguresPrompt = (spec) =>
  [
    'Author the in-article figures for ONE already-generated project blog article.',
    '',
    `1. Read the figure-authoring brief IN FULL: ${figuresPath}`,
    `2. Read the figure style guide IN FULL: ${figureStylePath}`,
    `3. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read it — body_markdown is FINAL; figure_requests are the writer\'s contracts.',
    `4. Write each SVG to ${outDir}/${spec.content_id}.figures/<id>.svg, then rasterize it`,
    `   ON THE SERVER: bash ${renderPath} ${outDir} figure_raster --svg @W/${spec.content_id}.figures/<id>.svg`,
    '   The wrapper writes <id>.png + <id>.webp back next to the SVG locally.',
    '   Then LOOK at each rendered .png yourself (Read tool) and fix what you see.',
    '5. Patch the "figures" array into that bundle per the brief, leaving every other',
    '   field untouched (unless the fallback in the brief applies). Write the bundle',
    `   back to its SAME path. slug MUST stay "${spec.slug}".`,
    '6. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')

const buildFigureJudgePrompt = (spec) =>
  [
    'Vision-judge the in-article figures of ONE project blog article. Default to rejecting.',
    '',
    `1. Read the judge brief IN FULL: ${figureJudgePath}`,
    `2. Read the figure style guide IN FULL: ${figureStylePath}`,
    `3. The bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   View each figure\'s rendered .png (sibling of its .webp) with the Read tool.',
    '4. Patch the "figure_gate" verdict into the bundle (leave every other field',
    `   untouched; SAME path; slug stays "${spec.slug}"), then return the structured verdict.`,
  ].join('\n')

const buildFiguresRevisePrompt = (spec, verdict) => {
  const failed = ((verdict && verdict.figures) || []).filter((f) => f && f.approved === false)
  return [
    'REVISE specific in-article figures of ONE project blog article (judge follow-up).',
    '',
    `1. Read the figure-authoring brief IN FULL: ${figuresPath} (see "Revision mode").`,
    `2. Read the figure style guide IN FULL: ${figureStylePath}`,
    `3. The bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '4. The vision judge FAILED these figures — fix exactly these, nothing else:',
    JSON.stringify(failed, null, 2),
    `5. Re-rasterize ON THE SERVER (bash ${renderPath} ${outDir} figure_raster --svg @W/${spec.content_id}.figures/<id>.svg),`,
    `   LOOK at the new .png(s), update the bundle's`,
    `   "figures" entries, write back to the SAME path (slug stays "${spec.slug}").`,
    '6. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')
}

const FIGURE_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    all_approved: { type: 'boolean' },
    figures: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          id: { type: 'string' },
          approved: { type: 'boolean' },
          problems: { type: 'array', items: { type: 'string' } },
        },
        required: ['id', 'approved'],
      },
    },
  },
  required: ['all_approved'],
}

// image-nb2 stage: renders the per-paragraph photoreal images from the author's
// image_requests (Gemini scene + SVG text overlay -> WebP), within the whole-post
// 2-per-1000-words budget. NB2 is the preferred standalone-image engine, so most
// bundles carry image_requests; the agent no-ops fast when a bundle has none
// (it used a drawn figure instead), so the judge only runs when at least one
// image was rendered.
const buildImagesPrompt = (spec) =>
  [
    'Render the OPTIONAL in-article NB2 photoreal images for ONE already-generated project blog article.',
    '',
    `1. Read the images brief IN FULL: ${imagesPath}`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read it FIRST. If "image_requests" is missing or empty, do NOTHING else and return',
    `   {"slug":"${spec.slug}","images":0,"ok":true} — the writer used a drawn figure instead.`,
    '3. Otherwise, for each request within the 2-per-1000-words budget, render it ON THE SERVER:',
    `   bash ${renderPath} ${outDir} nb2_image --bundle @W/${spec.content_id}.bundle.json --id <id>`,
    '   The wrapper patches the bundle + writes the images back locally. Render one id at a time.',
    '   Then LOOK at each rendered <id>.png yourself (Read tool) and regenerate what is off.',
    '4. The command patches the "images" array itself; ensure markers ↔ entries match and the',
    `   total stays within budget. Leave every other field untouched. slug stays "${spec.slug}".`,
    '5. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')

const buildImageJudgePrompt = (spec) =>
  [
    'Vision-judge the in-article NB2 images of ONE project blog article. Default to rejecting.',
    '',
    `1. Read the judge brief IN FULL: ${imageJudgePath}`,
    `2. The bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   View each image\'s rendered .png (sibling of its .webp) with the Read tool.',
    `3. Patch the "image_gate" verdict into the bundle (leave every other field untouched;`,
    `   SAME path; slug stays "${spec.slug}"), then return the structured verdict.`,
  ].join('\n')

const buildImagesRevisePrompt = (spec, verdict) => {
  const failed = ((verdict && verdict.images) || []).filter((f) => f && f.approved === false)
  return [
    'REVISE specific in-article NB2 images of ONE project blog article (judge follow-up).',
    '',
    `1. Read the images brief IN FULL: ${imagesPath} (see "Revision mode").`,
    `2. The bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '3. The vision judge FAILED these images — fix exactly these, nothing else:',
    JSON.stringify(failed, null, 2),
    `4. Regenerate each ON THE SERVER (bash ${renderPath} ${outDir} nb2_image --bundle @W/${spec.content_id}.bundle.json --id <id>),`,
    '   or adjust its scene_brief/overlay_text in image_requests first, then regenerate; LOOK at the new .png(s).',
    `5. Write back to the SAME path (slug stays "${spec.slug}"); return the one-line JSON status.`,
  ].join('\n')
}

const IMAGE_AUTHOR_STATUS_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: { slug: { type: 'string' }, images: { type: 'number' }, ok: { type: 'boolean' } },
  required: ['ok'],
}

const IMAGE_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    all_approved: { type: 'boolean' },
    images: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          id: { type: 'string' },
          approved: { type: 'boolean' },
          problems: { type: 'array', items: { type: 'string' } },
        },
        required: ['id', 'approved'],
      },
    },
  },
  required: ['all_approved'],
}

// Intent-satisfaction gate for one already-written bundle: an ADVERSARIAL reviewer that
// checks the finished draft actually answers its search intent and stayed inside its
// scope fences — the one thing no other stage verifies. It patches an `intent_gate`
// verdict into the bundle. This is the load-bearing quality gate: a fluent draft that
// answers half the intent is caught here, not by zero traffic months later.
const intentFields = (spec) => ({
  intent: spec.intent || '',
  intent_frame: spec.intent_frame || '',
  entity: spec.entity || '',
  scope_includes: spec.scope_includes || [],
  scope_excludes: spec.scope_excludes || [],
  canonical_owner: spec.canonical_owner || {},
  // Keyword-route evidence: the gate checks the draft covers the brief's essential
  // elements and that keyword usage stays natural (stuffing = not satisfied).
  keywords: (spec.keywords || []).slice(0, 10),
  brief_essential_elements: ((spec.brief || {}).essential_elements || []),
  // The brief's planned product moment — the gate's promotion-balance check
  // (oversell/undersell) judges the draft against it symmetrically.
  brief_business_bridge: ((spec.brief || {}).business_bridge || null),
})
const buildIntentGatePrompt = (spec) =>
  [
    'Adversarially judge whether ONE already-generated project blog draft actually',
    'satisfies its search intent and stayed inside its scope. Default to NOT satisfied.',
    '',
    `1. Read the intent-satisfaction-gate brief IN FULL: ${intentGatePath}`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read ONLY its title/h1/meta_description + body_markdown. Ignore the bundle\'s',
    '   generation_report and self_flags — that is the author\'s self-assessment and',
    '   must not anchor your independent verdict.',
    '3. Judge essential-element coverage, intent-frame fit, and scope discipline per the brief',
    '   against the ORIGINAL INTENT below.',
    '4. Patch an "intent_gate" object into the bundle (leave every other field untouched;',
    `   write it back to the SAME path; slug stays "${spec.slug}").`,
    '5. Then return the structured verdict.',
    '',
    'ORIGINAL INTENT (the spec):',
    JSON.stringify(intentFields(spec), null, 2),
  ].join('\n')

// Shared visual-reconciliation contract for EVERY stage that rewrites the body
// (intent-revise + editorial-revise). A body edit can strand a visual: a
// figure_request pointing at deleted content, a new section illustrated nowhere
// while its neighbours carry visuals, or a marker with no matching entry. Figures
// are drawn and cp-components rendered downstream from these contracts, so a body
// rewrite that leaves them stale ships a wrong or missing visual. Defined once so
// both revise prompts enforce it identically.
const VISUAL_RECONCILE_STEPS =
  'RECONCILE the visuals with the body you just changed:\n' +
  '   - figure_requests: every [[FIGURE:<id>]] marker must have exactly one figure_requests\n' +
  '     entry and vice-versa, and >=1 must remain. If you ADDED a section that earns a drawn\n' +
  '     figure, add a matching entry + marker; if you REMOVED/rewrote what a figure pointed\n' +
  '     at, drop or repoint that entry + marker. Leave already-valid figure_requests untouched.\n' +
  '   - cp-component visuals: if you ADDED a section carrying a data structure a catalog\n' +
  '     component would illustrate (comparison, flow, steps, distribution), embed the fitting\n' +
  '     cp-component block inline so the new section is not prose-only while the rest of the\n' +
  '     article is illustrated; if you REMOVED a section, remove its now-orphaned component.\n' +
  '     Never add a component where the section does not earn one (no one-of-each quota).\n' +
  '   - image_requests / [[IMAGE:<id>]] markers: keep them paired the same way; drop any whose\n' +
  '     paragraph you deleted.'

// Single revision pass, run ONLY when the intent gate fails: an author agent reads the
// verdict and patches the body to cover the missing essential elements and trim any
// scope violation, then re-validates. Bounded to one attempt — a re-gate records the
// honest final verdict; a residual failure is surfaced (not silently shipped) at import.
const buildRevisePrompt = (spec, verdict) =>
  [
    'Revise ONE already-generated project blog draft to fix specific intent gaps.',
    '',
    `1. Read the author brief IN FULL first: ${briefPath} (all rules still apply).`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json — read it.`,
    '3. The intent gate FAILED this draft. Fix exactly these, changing as little else as possible:',
    `   - missing essential elements to ADD: ${JSON.stringify((verdict && verdict.missing_essential) || [])}`,
    `   - scope violations to REMOVE/trim to one sentence: ${JSON.stringify((verdict && verdict.scope_violations) || [])}`,
    `   - frame mismatch to correct: ${JSON.stringify((verdict && verdict.frame_mismatch) || '')}`,
    '4. Keep every mechanical rule (cp-component data specs valid, no inline style=, 2-4',
    '   takeaways, meta/title/h1 lengths, INDEXABLE_URLS-only internal links, no /blog links).',
    '   Do NOT touch the "internal_links" or "external_sources" fields.',
    `5. ${VISUAL_RECONCILE_STEPS}`,
    `6. Write the bundle back to the SAME path; slug stays "${spec.slug}".`,
    '7. Return ONLY a compact one-line JSON status: {"slug":"...","revised":true,"addressed":N}.',
  ].join('\n')

const INTENT_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    satisfied: { type: 'boolean' },
    missing: { type: 'number' },
    scope_violations: { type: 'number' },
    missing_essential: { type: 'array', items: { type: 'string' } },
    frame_mismatch: { type: 'string' },
  },
  required: ['satisfied'],
}

// Editorial-quality gate for one already-written bundle: an independent reader that
// judges ONLY how the FINAL article READS — flow, cohesion, voice consistency, visual
// integration, intro/closing coherence, readability — the seams a stitched-together
// pipeline (draft + intent-revision sections + inserted visuals + post-hoc links) can
// leave. Runs AFTER the intent gate (prose is final) and BEFORE the relevance gate and
// visuals (so links/figures land on the polished body). It patches an `editorial_gate`
// verdict into the bundle. Advisory — a residual fail is surfaced, not import-blocked.
const buildEditorialGatePrompt = (spec) =>
  [
    'Judge ONLY how ONE already-generated project blog article READS — its flow and',
    'cohesion — not whether it satisfies search intent (a separate gate already did that).',
    'The article was assembled in pieces (a draft, then an intent revision that may have',
    'added/removed sections, plus visual markers), so hunt for the SEAMS that hurt reading.',
    '',
    `1. Read the editorial-quality-gate brief IN FULL: ${editorialGatePath}`,
    `2. The bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read its title/h1/meta_description + body_markdown. Treat [[FIGURE:<id>]] /',
    '   [[IMAGE:<id>]] as visual placeholders — judge whether the prose AROUND each one',
    '   sets it up and pays it off, not the marker text itself.',
    '3. Score the rubric dimensions in the brief (flow & transitions, cohesion &',
    '   non-redundancy, voice consistency, visual integration, opening/closing coherence,',
    '   readability). Flag SPECIFIC seam locations. Only fail for problems a reader would',
    '   actually feel — do NOT nitpick prose that already reads well.',
    '4. Patch an "editorial_gate" object into the bundle (leave every other field untouched;',
    `   write it back to the SAME path; slug stays "${spec.slug}").`,
    '5. Then return the structured verdict.',
  ].join('\n')

// Single flow-only revision, run ONLY when the editorial gate fails. It smooths the
// seams the judge named WITHOUT changing substance — no added/removed facts, no
// reintroduced scope violations, no new/dropped sections beyond what a transition
// needs; it rewrites transitions/sentences, removes redundancy, unifies voice, and
// keeps the visuals reconciled. Bounded to one attempt; a re-judge records the honest
// final verdict.
const buildEditorialRevisePrompt = (spec, verdict) =>
  [
    'Smooth the READING of ONE already-generated project blog article (editorial follow-up).',
    'This is a PROSE pass, not a rewrite: preserve every fact, element, section, and the',
    'structure the intent gate blessed — change only how it reads.',
    '',
    `1. Read the author brief IN FULL first: ${briefPath} (all rules still apply).`,
    `2. The bundle is at: ${outDir}/${spec.content_id}.bundle.json — read it.`,
    '3. The editorial gate flagged these reading problems — fix exactly these:',
    `   - problems by dimension: ${JSON.stringify((verdict && verdict.problems) || [])}`,
    `   - specific seam locations: ${JSON.stringify((verdict && verdict.seams) || [])}`,
    '   Fix them by rewriting transitions and sentences, adding connective tissue, removing',
    '   repeated explanations, and unifying voice/tense/person. Do NOT add or remove facts,',
    '   essential elements, or sections; do NOT reintroduce anything the intent gate removed;',
    '   do NOT touch the "internal_links" or "external_sources" fields.',
    '4. Keep every mechanical rule (cp-component specs valid, no inline style=, 2-4 takeaways,',
    '   meta/title/h1 lengths, INDEXABLE_URLS-only internal links, no /blog links).',
    `5. ${VISUAL_RECONCILE_STEPS}`,
    `6. Write the bundle back to the SAME path; slug stays "${spec.slug}".`,
    '7. Return ONLY a compact one-line JSON status: {"slug":"...","revised":true,"addressed":N}.',
  ].join('\n')

const EDITORIAL_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    reads_well: { type: 'boolean', description: 'true only when the article flows as one coherent piece with no reader-felt seams.' },
    scores: {
      type: 'object', additionalProperties: true,
      properties: {
        flow: { type: 'integer' },
        cohesion: { type: 'integer' },
        voice: { type: 'integer' },
        visual_integration: { type: 'integer' },
        opening_closing: { type: 'integer' },
        readability: { type: 'integer' },
      },
    },
    problems: { type: 'array', items: { type: 'string' } },
    seams: { type: 'array', items: { type: 'string' } },
  },
  required: ['reads_well'],
}

// pipeline: each article flows write -> intent-gate (+revision) -> editorial-gate
// (+revision) -> relevance-gate -> figures -> images -> hero independently (no
// barrier). The two body-revising gates run FIRST and in this order — intent
// settles WHAT the article says (coverage + scope), then the editorial gate
// settles HOW it reads (flow, cohesion, voice, the seams a stitched-together
// assembly leaves) — so the external-source relevance gate, the figures, the
// images, and the hero are all judged/drawn against the FINAL, polished body. A
// failed author bundle (status null) skips the rest. The downstream content_import
// then runs the deterministic 200 + allowlist gate on whatever external_sources
// survived here, and blocks on an unsatisfied intent_gate verdict (override:
// --allow-unsatisfied); the editorial_gate verdict is advisory (surfaced, not blocking).
//
// THROTTLE: each author agent is a heavy general-purpose run (multi web fetch + long
// draft). Letting the runtime fan out all specs at once (cap = min(16, cores-2)) burst-
// hammers the API and trips a server-side rate limit that fails the WHOLE batch (and
// still burns the tokens). So we process the specs in WAVES of `waveSize` (default 4),
// each wave a self-contained write->gate pipeline, waves run sequentially. Bounds the
// concurrent author count regardless of the host core count.
const waveSize = Math.max(1, (A && Number(A.waveSize)) || 4)
const waves = []
for (let i = 0; i < contents.length; i += waveSize) waves.push(contents.slice(i, i + waveSize))
log(`generating in ${waves.length} wave(s) of up to ${waveSize} concurrent author(s)`)

const results = []
for (let w = 0; w < waves.length; w++) {
  log(`wave ${w + 1}/${waves.length}: ${waves[w].length} article(s)`)
  const waveResults = await pipeline(
    waves[w],
    (spec) =>
      agent(buildPrompt(spec), {
        label: `write:${spec.slug}`,
        phase: 'Generate',
        agentType: 'general-purpose', // Tools: * — has WebSearch/WebFetch/Read/Write
      }).then((status) => ({ slug: spec.slug, content_id: spec.content_id, status })),
    // Stage 2 — INTENT GATE FIRST. Any body revision it triggers happens before
    // the relevance gate, figures, images, and hero, so every later stage sees the
    // FINAL body. Operates directly on the author bundle (no relevance gate ran yet).
    async (authored, spec) => {
      if (!intentGatePath || !authored || authored.status == null) return { ...authored, intentGate: null }
      let verdict = await agent(buildIntentGatePrompt(spec), {
        label: `intent-gate:${spec.slug}`,
        phase: 'Intent gate',
        agentType: 'general-purpose',
        schema: INTENT_VERDICT_SCHEMA,
      })
      let revised = false
      if (verdict && verdict.satisfied === false) {
        await agent(buildRevisePrompt(spec, verdict), {
          label: `revise:${spec.slug}`,
          phase: 'Intent gate',
          agentType: 'general-purpose',
        })
        revised = true
        // Re-gate once to record the honest final verdict in the bundle.
        verdict = await agent(buildIntentGatePrompt(spec), {
          label: `re-gate:${spec.slug}`,
          phase: 'Intent gate',
          agentType: 'general-purpose',
          schema: INTENT_VERDICT_SCHEMA,
        })
      }
      return { ...authored, intentGate: { satisfied: !!(verdict && verdict.satisfied), revised } }
    },
    // Stage 3 — EDITORIAL GATE. Judges how the FINAL article READS (flow, cohesion,
    // voice, seams) after the intent revision settled the prose, and BEFORE the
    // relevance gate + visuals so links/figures land on the polished body. One
    // flow-only revision on fail, then a re-judge records the honest verdict.
    async (intented, spec) => {
      if (!editorialGatePath || !intented || intented.status == null) return { ...intented, editorialGate: null }
      let verdict = await agent(buildEditorialGatePrompt(spec), {
        label: `editorial-gate:${spec.slug}`,
        phase: 'Editorial gate',
        agentType: 'general-purpose',
        schema: EDITORIAL_VERDICT_SCHEMA,
      })
      let revised = false
      if (verdict && verdict.reads_well === false) {
        await agent(buildEditorialRevisePrompt(spec, verdict), {
          label: `editorial-revise:${spec.slug}`,
          phase: 'Editorial gate',
          agentType: 'general-purpose',
        })
        revised = true
        // Re-judge once to record the honest final verdict in the bundle.
        verdict = await agent(buildEditorialGatePrompt(spec), {
          label: `editorial-rejudge:${spec.slug}`,
          phase: 'Editorial gate',
          agentType: 'general-purpose',
          schema: EDITORIAL_VERDICT_SCHEMA,
        })
      }
      return { ...intented, editorialGate: { reads_well: !!(verdict && verdict.reads_well), revised } }
    },
    // Stage 4 — RELEVANCE GATE, now against the FINAL body. The intent-gate and
    // editorial-gate revisions (if any) have already run, so external sources are
    // fetched and judged against the article the reader will actually get.
    (judged, spec) => {
      if (!gatePath || !judged || judged.status == null) return { ...judged, gated: false }
      return agent(buildGatePrompt(spec), {
        label: `gate:${spec.slug}`,
        phase: 'Relevance gate',
        agentType: 'general-purpose',
      }).then((gate) => ({ ...judged, gated: true, gate }))
    },
    async (judged, spec) => {
      if (!figuresPath || !judged || judged.status == null) return { ...judged, figures: null }
      await agent(buildFiguresPrompt(spec), {
        label: `figures:${spec.slug}`,
        phase: 'Figures',
        agentType: 'general-purpose', // Tools: * — needs Read (vision) + Bash + Write
      })
      let verdict = await agent(buildFigureJudgePrompt(spec), {
        label: `figure-judge:${spec.slug}`,
        phase: 'Figures',
        agentType: 'general-purpose',
        schema: FIGURE_VERDICT_SCHEMA,
      })
      let revised = false
      if (verdict && verdict.all_approved === false) {
        await agent(buildFiguresRevisePrompt(spec, verdict), {
          label: `figure-revise:${spec.slug}`,
          phase: 'Figures',
          agentType: 'general-purpose',
        })
        revised = true
        // Re-judge once to record the honest final verdict in the bundle.
        verdict = await agent(buildFigureJudgePrompt(spec), {
          label: `figure-rejudge:${spec.slug}`,
          phase: 'Figures',
          agentType: 'general-purpose',
          schema: FIGURE_VERDICT_SCHEMA,
        })
      }
      return { ...judged, figures: { approved: !!(verdict && verdict.all_approved), revised } }
    },
    async (judged, spec) => {
      if (!imagesPath || !judged || judged.status == null) return { ...judged, images: null }
      // Author-images no-ops fast when there are no image_requests (common case);
      // only spin up the vision judge when it actually rendered something.
      const authored = await agent(buildImagesPrompt(spec), {
        label: `images:${spec.slug}`,
        phase: 'Images',
        agentType: 'general-purpose', // Tools: * — needs Read (vision) + Bash + Write
        schema: IMAGE_AUTHOR_STATUS_SCHEMA,
      })
      const rendered = (authored && Number(authored.images)) || 0
      if (rendered <= 0) return { ...judged, images: { count: 0, approved: true, revised: false } }
      let verdict = await agent(buildImageJudgePrompt(spec), {
        label: `image-judge:${spec.slug}`,
        phase: 'Images',
        agentType: 'general-purpose',
        schema: IMAGE_VERDICT_SCHEMA,
      })
      let revised = false
      if (verdict && verdict.all_approved === false) {
        await agent(buildImagesRevisePrompt(spec, verdict), {
          label: `image-revise:${spec.slug}`,
          phase: 'Images',
          agentType: 'general-purpose',
        })
        revised = true
        // Re-judge once to record the honest final verdict in the bundle.
        verdict = await agent(buildImageJudgePrompt(spec), {
          label: `image-rejudge:${spec.slug}`,
          phase: 'Images',
          agentType: 'general-purpose',
          schema: IMAGE_VERDICT_SCHEMA,
        })
      }
      return { ...judged, images: { count: rendered, approved: !!(verdict && verdict.all_approved), revised } }
    },
    (judged, spec) => {
      if (!heroPath || !judged || judged.status == null) return { ...judged, hero: false }
      return agent(buildHeroPrompt(spec), {
        label: `hero:${spec.slug}`,
        phase: 'Hero',
        agentType: 'general-purpose',
      }).then((heroStatus) => ({ ...judged, hero: true, heroStatus }))
    }
  )
  results.push(...waveResults)
}

const ok = results.filter(Boolean)
const gatedCount = ok.filter((r) => r && r.gated).length
const heroCount = ok.filter((r) => r && r.hero).length
const intentChecked = ok.filter((r) => r && r.intentGate).length
const intentSatisfied = ok.filter((r) => r && r.intentGate && r.intentGate.satisfied).length
const intentRevised = ok.filter((r) => r && r.intentGate && r.intentGate.revised).length
const editorialChecked = ok.filter((r) => r && r.editorialGate).length
const editorialPassed = ok.filter((r) => r && r.editorialGate && r.editorialGate.reads_well).length
const editorialRevised = ok.filter((r) => r && r.editorialGate && r.editorialGate.revised).length
const figuresRun = ok.filter((r) => r && r.figures).length
const figuresApproved = ok.filter((r) => r && r.figures && r.figures.approved).length
const figuresRevised = ok.filter((r) => r && r.figures && r.figures.revised).length
const imagesArticles = ok.filter((r) => r && r.images && r.images.count > 0).length
const imagesTotal = ok.reduce((n, r) => n + ((r && r.images && r.images.count) || 0), 0)
log(`done: ${ok.length}/${contents.length} drafts written, ${gatedCount} passed the relevance gate, ${heroCount} heroes authored — bundles in ${outDir}`)
log(`intent gate: ${intentSatisfied}/${intentChecked} satisfied (${intentRevised} revised once); unsatisfied drafts are flagged at content_import`)
log(`editorial gate: ${editorialPassed}/${editorialChecked} read cleanly (${editorialRevised} flow-revised once); the verdict is advisory — a residual seam is surfaced, not blocked`)
log(`figures: ${figuresApproved}/${figuresRun} articles fully judge-approved (${figuresRevised} revised once); unapproved figures are surfaced at content_import`)
log(`image-nb2: ${imagesTotal} photoreal image(s) across ${imagesArticles} article(s) (optional, budget 2/1000 words; over-budget blocks at content_import)`)

// Phase 'Cluster links' — blog→blog internal linking, computed ONCE per topic
// cluster AFTER every article in that cluster exists. This is the point where the
// parallel-generation blindness is gone: the candidate set (the cluster's siblings)
// is complete and stable. One planner agent per multi-article cluster reads the
// finished bundles, applies pillar↔spoke topology, and writes a structured
// `internal_links` edge list ({anchor, target_slug}) into each bundle — it does NOT
// rewrite bodies. The publisher (publish_from_bundle → apply_internal_links) inserts
// the edges deterministically + idempotently at content_import time.
//
// Specs carry topic_cluster/role/slug already, so the cluster grouping needs no file
// reads (the workflow sandbox has no filesystem); the planner agent reads the bundle
// bodies itself. Single-article clusters are skipped — there is nothing to cross-link
// (the live cluster rail still surfaces the pillar). Cross-CLUSTER links are
// intentionally out of scope: low signal, high irrelevance risk.
phase('Cluster links')
const okIds = new Set(ok.filter((r) => r && r.status != null).map((r) => r.content_id))
const byCluster = new Map()
for (const spec of contents) {
  if (!okIds.has(spec.content_id)) continue
  const key = ((spec && spec.topic_cluster) || '').trim()
  if (!key) continue
  if (!byCluster.has(key)) byCluster.set(key, [])
  byCluster.get(key).push(spec)
}
// A cluster qualifies when the batch has >=2 articles OR the cluster already has
// produced siblings (spec.cluster_siblings from export_worklist) — the content
// spine is route-independent, so a single new spoke joining an existing cluster
// still gets inline links to that cluster's live pillar/spokes.
const _sibs = (specs) => (specs[0] && specs[0].cluster_siblings) || []
const linkClusters = [...byCluster.entries()].filter(
  ([, specs]) => specs.length >= 2 || _sibs(specs).length >= 1
)
const skipped = byCluster.size - linkClusters.length
log(`cluster-linking ${linkClusters.length} cluster(s) (batch>=2 or existing siblings; ${skipped} isolated single(s) skipped)`)

const buildClusterLinkPrompt = (cluster, specs) => {
  const arts = specs.map((s) => ({
    slug: s.slug,
    role: (s.role || 'spoke'),
    title: s.title || s.h1 || s.slug,
    // Each article's DECLARED canonical intent (from ContentPlan.to_worklist_spec).
    // The target's intent is handed to the linker HERE so it matches anchors against
    // a stated intent instead of re-inferring one by reading the target's prose —
    // the fix for anchors like "best cTrader broker" pointing at a platform-agnostic
    // page. scope_includes/excludes sharpen where the discriminating qualifier lives.
    intent: s.intent || '',
    observed_intent: s.observed_intent || '',
    scope_includes: s.scope_includes || [],
    scope_excludes: s.scope_excludes || [],
    bundle_path: `${outDir}/${s.content_id}.bundle.json`,
  }))
  const siblings = _sibs(specs)
  // The directed link plan the cluster-pass designed (from_slug -> to_slug at a
  // concept). The authors were asked to leave a natural anchor phrase for each edge
  // whose from_slug is theirs, so these are the FIRST-CHOICE anchors — the pass
  // prefers a planned anchor and only falls back to an opportunistic phrase when a
  // planned one did not materialize. Rides every spec via cluster_brief.
  const linkPlan = ((specs[0] && specs[0].cluster_brief && specs[0].cluster_brief.link_plan) || [])
  return [
    `Wire blog→blog internal links across ONE topic cluster: "${cluster}".`,
    '',
    `1. Read the cluster-linking brief IN FULL: ${repoRoot}/content-pipeline/prompts/cluster-internal-links.md`,
    '2. These are the already-generated article bundles in this cluster. Each carries its',
    '   DECLARED `intent` (+ scope fences) — treat that as the authoritative statement of what',
    '   the TARGET article is for. Read each bundle body ONLY to pick a real anchor phrase from',
    '   the SOURCE; judge intent-match against the declared `intent`, not by re-reading target prose:',
    JSON.stringify(arts, null, 2),
    linkPlan.length
      ? 'DESIGNED LINK PLAN (first-choice edges the cluster strategist planned; the authors were asked\n' +
        'to leave a natural anchor phrase for each. For every edge, PREFER wiring exactly this: find the\n' +
        'planned anchor phrase in from_slug\'s body and link it to to_slug. Only fall back to your own\n' +
        'opportunistic anchor when the planned phrase is genuinely absent, and still honor every hard rule\n' +
        '(verbatim phrase, intent-match, one per target). Do NOT treat these as a cap — add a well-earned\n' +
        'edge the plan missed; do NOT force an edge whose planned anchor never made it into the body:\n' +
        JSON.stringify(linkPlan, null, 2)
      : '(no designed link plan for this cluster — plan the graph from intent + topology as below)',
    siblings.length
      ? 'EXISTING cluster siblings (already-produced posts in this SAME cluster — from an earlier batch\n' +
        'or another planning route). They are valid link TARGETS exactly like batch articles (their\n' +
        'declared intent is given); you cannot edit them, so they only RECEIVE links from the new\n' +
        'articles (the live cluster rail links back automatically). If the cluster PILLAR is one of\n' +
        'them, every new spoke links to that existing pillar:\n' +
        JSON.stringify(siblings, null, 2)
      : '(no existing siblings — this batch is the whole cluster so far)',
    '3. Plan the within-cluster link graph per the brief: pillar↔spoke topology, one link per',
    '   distinct target, every anchor a verbatim plain-text phrase from the SOURCE body, and —',
    '   critically — the anchor\'s search intent MUST match the TARGET\'s declared intent (never',
    '   the source\'s own intent/head-term; platform/entity qualifiers are intent-defining).',
    '4. For EACH batch article, write its chosen OUTGOING edges into that bundle\'s "internal_links"',
    '   field as a JSON array of {"anchor","target_slug"} (target_slug = any article in THIS cluster,',
    '   batch or existing sibling). Leave every other field untouched — do NOT modify body_markdown —',
    '   and write the bundle back to its SAME path. Never try to write a sibling\'s bundle (none exists).',
    '5. Return ONLY a compact one-line JSON status: {"cluster":"...","edges":N,"articles":M}.',
  ].join('\n')
}

const linkResults = await parallel(
  linkClusters.map(([cluster, specs]) => () =>
    agent(buildClusterLinkPrompt(cluster, specs), {
      label: `cluster-links:${cluster.slice(0, 28)}`,
      phase: 'Cluster links',
      agentType: 'general-purpose', // Tools: * — needs Read + Write
    }).then((status) => ({ cluster, articles: specs.length, status }))
  )
)
const linked = linkResults.filter(Boolean)
log(`cluster-linking done: ${linked.length}/${linkClusters.length} cluster(s) wired`)

// Phase 'Overlap audit' — Layer 4 (CANNIBALIZATION-PREVENTION-PLAN.md §3). Because
// Layer 1 auto-decides with no human gate, one agent reads every finished bundle and
// computes pairwise overlap (shared H2 headings, widget/calculator signatures,
// repeated stats, intro similarity), then writes overlap-audit.json. The audit does
// not modify bundles, but its output now gates at import: content_import hard-blocks
// both articles of any pair scoring >=75 (60–74 are flagged-but-imported). So a true
// near-duplicate pair can no longer silently publish — a human must resolve it first.
phase('Overlap audit')
const auditBundles = ok.filter((r) => r && r.status != null)
let overlapAudit = { status: 'skipped (need >=2 bundles)' }
if (auditBundles.length >= 2) {
  const auditPrompt = [
    'Run the Layer-4 overlap audit across a just-generated batch of blog bundles.',
    'Your scores have real consequences: content_import HARD-BLOCKS both articles of',
    'any pair you score >=75, and flags 60-74 pairs for human review — so calibrate',
    'scores honestly rather than leniently, especially near those thresholds.',
    '',
    `1. Read the overlap-audit brief IN FULL: ${repoRoot}/content-pipeline/prompts/overlap-audit.md`,
    `2. The bundles are at ${outDir}. Slugs to compare (read each bundle's body_markdown + h1 +`,
    `   meta_description; use Bash+python/jq to pull fields so you don't overflow context):`,
    `   ${auditBundles.map((r) => r.slug).join(', ')}`,
    `3. Do the audit per the brief and write ${outDir}/overlap-audit.json. Do NOT modify any bundle.`,
    '4. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')
  const auditStatus = await agent(auditPrompt, {
    label: 'overlap-audit',
    phase: 'Overlap audit',
    agentType: 'general-purpose', // Tools: * — needs Read + Bash + Write
  })
  overlapAudit = { status: auditStatus }
  log(`overlap-audit done: ${typeof auditStatus === 'string' ? auditStatus.slice(0, 160) : ''}`)
} else {
  log('overlap-audit skipped (fewer than 2 generated bundles to compare)')
}

// Phase 'Glossary gap' — flags glossary-worthy terms this batch leans on that the
// live glossary is missing (without this phase a batch ships with NO missing-term
// suggestions). One agent reads every finished bundle
// body + the live glossary term list (args.glossaryTerms, fetched fresh from prod
// like indexableUrls) and writes genuinely-missing, glossary-worthy terms to a
// suggestions JSON next to the bundles. The queue of record is the DB — ingest the
// file with `manage.py contentplan_ingest_terms <file> --cluster <batch cluster>`
// on prod, in the same step as content_import. Advisory only — never blocks.
phase('Glossary gap')
const glossaryTerms = (A && Array.isArray(A.glossaryTerms) && A.glossaryTerms) || []
let glossary = { added: 0, status: 'skipped (no glossaryTerms provided)' }
const okBundles = ok.filter((r) => r && r.status != null)
if (glossaryTerms.length && okBundles.length) {
  const suggestionsPath = `${outDir}/glossary-suggestions.json`
  const gapPrompt = [
    'Run a GLOSSARY-GAP analysis across a just-generated batch of blog bundles.',
    '',
    `1. Read the batch glossary-gap brief IN FULL: ${repoRoot}/content-pipeline/prompts/glossary-gap-batch.md`,
    `2. The bundles are at ${outDir}; slugs (read each body_markdown via Bash+python/jq so you don't`,
    `   overflow context): ${okBundles.map((r) => r.slug).join(', ')}`,
    '3. EXISTING glossary terms (do NOT suggest these or trivial plural/hyphen/abbrev variants):',
    JSON.stringify(glossaryTerms),
    `4. Write genuinely-missing terms to the suggestions file at ${suggestionsPath}, per the brief.`,
    '5. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')
  const gapStatus = await agent(gapPrompt, {
    label: 'glossary-gap',
    phase: 'Glossary gap',
    agentType: 'general-purpose', // Tools: * — needs Read + Bash + Write
  })
  glossary = { status: gapStatus }
  log(`glossary-gap done: ${typeof gapStatus === 'string' ? gapStatus.slice(0, 120) : ''}`)
} else {
  log('glossary-gap skipped (pass args.glossaryTerms — the live is_term=True names — to enable)')
}

// Outbound-domain histogram — aggregated from the link-gate statuses (each gate
// reports the kept hosts as `domains`) so every run report shows which external
// domains this batch links and how concentrated the profile is. The site-wide
// cross-run view is `manage.py content_outbound_domains` on prod.
const externalDomains = {}
for (const r of ok) {
  if (!r || typeof r.gate !== 'string') continue
  try {
    const m = r.gate.match(/\{[\s\S]*\}/)
    const parsed = m ? JSON.parse(m[0]) : null
    const hosts = parsed && Array.isArray(parsed.domains) ? parsed.domains : []
    for (const d of hosts) {
      const host = String(d).toLowerCase().replace(/^www\./, '')
      if (host) externalDomains[host] = (externalDomains[host] || 0) + 1
    }
  } catch (e) { /* tolerate a non-JSON gate status — histogram is best-effort */ }
}
const domainLine = Object.entries(externalDomains)
  .sort((a, b) => b[1] - a[1])
  .map(([d, n]) => `${d} x${n}`)
  .join(', ')
log(`outbound domains this run: ${domainLine || '(none reported by the gate)'}`)

return {
  requested: contents.length,
  completed: ok.length,
  externalDomains,
  gated: gatedCount,
  heroes: heroCount,
  intentChecked,
  intentSatisfied,
  intentRevised,
  editorialChecked,
  editorialPassed,
  editorialRevised,
  figuresRun,
  figuresApproved,
  figuresRevised,
  imagesArticles,
  imagesTotal,
  clustersLinked: linked.length,
  outDir,
  results: ok,
  clusterLinks: linked,
  overlapAudit,
  glossary,
}

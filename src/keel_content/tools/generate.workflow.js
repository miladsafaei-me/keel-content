export const meta = {
  name: 'generate-blog-from-worklist',
  description:
    'Generate one project blog draft per worklist spec — one fresh agent each, each writing a self-contained bundle JSON for content_import. Then an independent link-relevance gate reviews every draft\'s external sources, and a cluster-linking pass wires blog→blog internal links within each topic cluster once all its articles exist. Independent contexts (no chaining) so every article gets a fresh strategist read.',
  phases: [
    { title: 'Generate', detail: 'one fresh agent per content spec' },
    { title: 'Quality gate', detail: 'ONE reviewer scores both intent-satisfaction (coverage/scope) AND editorial quality (flow/cohesion/voice/seams) in a single pass on a recalibrated real-problems-only bar; a single revision fixes coverage gaps + smooths seams together on fail — runs before links + visuals are judged/drawn against the FINAL body' },
    { title: 'Relevance gate', detail: 'independent reviewer fetches + judges each draft\'s external links AGAINST THE FINAL body (after any quality-gate revision)' },
    { title: 'Figures', detail: "a separate agent draws each article's in-article figures (SVG -> WebP) from the author's figure_requests after the body is FINAL; a vision judge gates them, one revision on fail. Runs CONCURRENTLY with the relevance gate" },
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
const intentGatePath = (A && A.intentGatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/intent-satisfaction-gate.md` : '')
const editorialGatePath = (A && A.editorialGatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/editorial-quality-gate.md` : '')
// The body-revising stages (intent-revise + editorial-revise) read this LEAN card
// instead of the full author brief — it carries only the binding hard rules
// (via brief-core-constraints.md) + the visual-reconcile step a revise needs. The
// full brief is the WRITE stage's system prompt; a surgical revise does not need
// its research/visual-selection/schema walls, so pointing revises here is the main
// per-article token cut (see content-pipeline/prompts/brief-revise-card.md).
const revisePath = (A && A.revisePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/brief-revise-card.md` : '')
// Merged quality gate: ONE Sonnet judge scores BOTH intent-satisfaction AND editorial
// quality (replacing the separate intent-gate + editorial-gate stages), on a recalibrated
// "real problems only" bar; a single Opus revise fixes coverage gaps + smooths seams
// together; a Sonnet re-judge records the honest verdict. See quality-gate.md.
const qualityGatePath = (A && A.qualityGatePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/quality-gate.md` : '')
const figuresPath = (A && A.figuresPath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/author-figures.md` : '')
const figureJudgePath = (A && A.figureJudgePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/figure-judge.md` : '')
const figureStylePath = (A && A.figureStylePath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/figure-style-guide.md` : '')
// The figure VISION-JUDGE (and its rejudge) only VIEW the rendered figure and check it —
// they don't draw, so they read this compact pass/fail card instead of the full
// figure-style-guide.md drawing recipe (the figure author + figure-revise still read the
// full guide, since they draw SVG). Same per-stage-composition cut as the revise card.
const figureJudgeCardPath = (A && A.figureJudgeCardPath) || (repoRoot ? `${repoRoot}/content-pipeline/prompts/figure-judge-card.md` : '')
// Renders (figure_raster / nb2_image) run ON THE SERVER via this wrapper: it
// stages the bundle dir up, renders inside an isolated memory-capped container,
// and copies the rendered files back — so the box driving generation needs no
// local Linux render tooling (only ssh + scp). @W in the argv -> the staged dir.
const renderPath = (A && A.renderPath) || (repoRoot ? `${repoRoot}/tools/content_pipeline/render_on_server.sh` : '')
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

// Per-stage model tiering (TOKEN-OPTIMIZATION-PLAN.md). Every agent() call sets
// model: EXPLICITLY — never rely on session-model inheritance — so per-article
// usage cost drops without touching quality. Re-tiering a whole class of stage is
// a one-line change here.
//   M_AUTHOR — substance authoring + the merged quality gate's revise (generative quality)
//   M_JUDGE  — verification / judgement / classification / spec-driven visuals (incl. the
//              quality-gate JUDGE + re-judge: scoring prose flow is verification, not
//              authoring, so it runs on Sonnet; only the revise it triggers stays Opus)
//   M_MECH   — pure script-runner agents (run a command, return its output)
const M_AUTHOR = 'opus'
const M_JUDGE = 'sonnet'
const M_MECH = 'haiku'

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
    `2. repoRoot for every other read (BLOG.md, BUSINESS.md, and the component catalog at content-pipeline/components/CATALOG.md): ${repoRoot}.`,
    '   You do NOT need to load the full CLAUDE.md — the author brief already distills every',
    '   authoring-relevant rule (compliance, trade-semantic colors, English-only, the internal-link',
    '   + noindex model). Its git/deploy/podman/CI/registry sections do not apply to authoring; if you',
    '   must verify a compliance edge case, grep the one relevant CLAUDE.md section rather than reading it whole.',
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
    '   Fetch each DISTINCT url at most once — if the same url appears twice, reuse the fetch.',
    '   Keep (anchor rewritten if it over-claims) or drop. Drop generic homepages/section hubs.',
    '4. Overwrite the bundle\'s "external_sources" with ONLY the kept (anchor-corrected) items.',
    '   Leave every other field untouched. Write the bundle back to the SAME path.',
    `   slug MUST stay "${spec.slug}".`,
    '5. Return ONLY the compact one-line JSON status described in the brief.',
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
    '6. Return the compact JSON status described in the brief, and ADD a boolean',
    '   "has_image_requests" field: true iff the bundle\'s "image_requests" array is',
    '   present and non-empty (you already read the bundle — just report what you saw).',
  ].join('\n')

const buildFigureJudgePrompt = (spec) =>
  [
    'Vision-judge the in-article figures of ONE project blog article. Default to rejecting.',
    '',
    `1. Read the judge brief IN FULL: ${figureJudgePath}`,
    `2. Read the figure judge card IN FULL: ${figureJudgeCardPath} (the compact pass/fail bar — you view + judge, you do not draw).`,
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

// Status the figures author returns. `has_image_requests` powers the NB2 no-op
// guard: the images stage is skipped entirely when the bundle carries no
// image_requests (the author read the bundle here, so it is the cheapest place to
// learn this — the workflow sandbox has no filesystem of its own).
const FIGURES_STATUS_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    figures: { type: 'number' },
    has_image_requests: { type: 'boolean', description: 'true iff the bundle\'s image_requests array is present and non-empty' },
    ok: { type: 'boolean' },
  },
  required: ['has_image_requests'],
}

// Summary the Haiku runner returns after executing overlap_score.py — mirrors the
// script's stdout SUMMARY line. gray_band > 0 triggers the Sonnet confirm pass.
const OVERLAP_RUN_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    written: { type: 'boolean' },
    bundles: { type: 'number' },
    pairs: { type: 'number' },
    blocked: { type: 'number' },
    flagged: { type: 'number' },
    gray_band: { type: 'number' },
    top_score: { type: 'number' },
  },
  required: ['pairs', 'gray_band'],
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
// Merged quality-gate judge: ONE Sonnet reviewer scores BOTH (A) intent satisfaction
// (coverage/scope/frame/promotion) AND (B) editorial quality (flow/cohesion/voice/seams)
// in a single pass, on a "real problems only" bar, and patches BOTH an `intent_gate`
// (content_import blocks on satisfied=false) and an `editorial_gate` (advisory) verdict.
const buildQualityGatePrompt = (spec) =>
  [
    'Judge ONE already-generated project blog draft on TWO dimensions in a single pass:',
    '(A) does it satisfy its search intent and stay in scope, and (B) does the finished',
    'article READ as one coherent piece. Be strict on real coverage/scope gaps and',
    'reader-felt seams; do NOT nitpick prose that already works (the revise is expensive).',
    '',
    `1. Read the quality-gate brief IN FULL: ${qualityGatePath}`,
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json`,
    '   Read ONLY its title/h1/meta_description + body_markdown. Ignore generation_report/self_flags.',
    '3. Judge Part A (essential-element coverage, intent-frame fit, scope discipline, promotion',
    '   balance, keyword naturalness) against the ORIGINAL INTENT below, and Part B (flow,',
    '   cohesion, voice, visual integration, opening/closing, readability) per the brief.',
    '4. Patch BOTH an "intent_gate" and an "editorial_gate" object into the bundle (leave every',
    `   other field untouched; write it back to the SAME path; slug stays "${spec.slug}").`,
    '5. Then return the combined structured verdict.',
    '',
    'ORIGINAL INTENT (the spec):',
    JSON.stringify(intentFields(spec), null, 2),
  ].join('\n')

// The visual-reconciliation contract that both body-revising stages must honor now
// lives in the host revise card (content-pipeline/prompts/brief-revise-card.md), which
// each revise agent reads — so it is no longer inlined here.

// Single merged revision, run ONLY when the quality gate fails EITHER dimension: one Opus
// agent adds the missing essential substance / trims scope AND smooths the named reading
// seams, in one pass, then a re-judge records the honest final verdict. Bounded to one
// attempt; a residual failure is surfaced (not silently shipped) at import.
const buildQualityRevisePrompt = (spec, verdict) =>
  [
    'Revise ONE already-generated project blog draft to fix the specific problems a quality',
    'gate flagged — both intent-coverage gaps and reading seams — in a single pass.',
    '',
    `1. Read the revise card IN FULL first: ${revisePath} — it carries every binding rule`,
    '   (it points you to brief-core-constraints.md — read that too), the "do NOT touch',
    '   internal_links/external_sources" rule, and the visual-reconcile step.',
    `2. The draft bundle is at: ${outDir}/${spec.content_id}.bundle.json — read it.`,
    '3. Fix exactly these, changing as little else as possible:',
    `   - missing essential elements to ADD: ${JSON.stringify((verdict && verdict.missing_essential) || [])}`,
    `   - scope violations to REMOVE/trim to one sentence: ${JSON.stringify((verdict && verdict.scope_violations) || [])}`,
    `   - frame mismatch to correct: ${JSON.stringify((verdict && verdict.frame_mismatch) || '')}`,
    `   - reading problems to smooth: ${JSON.stringify((verdict && verdict.problems) || [])}`,
    `   - specific seam locations: ${JSON.stringify((verdict && verdict.seams) || [])}`,
    '   Add missing substance where a coverage gap needs it; smooth seams by rewriting',
    '   transitions/sentences, removing repetition, unifying voice. Do NOT reintroduce a',
    '   scope violation, invent facts/stats, or add/drop sections beyond what a fix needs.',
    '4. Reconcile the visuals with your edit per the card.',
    `5. Write the bundle back to the SAME path; slug stays "${spec.slug}".`,
    '6. Return ONLY a compact one-line JSON status: {"slug":"...","revised":true,"addressed":N}.',
  ].join('\n')

const COMBINED_VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    slug: { type: 'string' },
    satisfied: { type: 'boolean' },
    reads_well: { type: 'boolean' },
    // The editorial dimension's weakest sub-score, surfaced so the workflow can
    // tell a real structural problem from a stylistic nit. `reads_well:false`
    // alone is NOT enough to justify an Opus revise: the verdict is advisory at
    // content_import (it never blocks), and in practice it fails on cohesion 3-4
    // — "a component re-lists what the prose just said" — which costs a full
    // rewrite round for a draft that ships either way. Only cohesion <= 2 is a
    // seam a reader would actually trip over.
    cohesion: { type: 'integer', minimum: 1, maximum: 5 },
    missing_essential: { type: 'array', items: { type: 'string' } },
    scope_violations: { type: 'array', items: { type: 'string' } },
    frame_mismatch: { type: 'string' },
    problems: { type: 'array', items: { type: 'string' } },
    seams: { type: 'array', items: { type: 'string' } },
  },
  required: ['satisfied', 'reads_well'],
}

// (The former separate editorial-quality gate + its Opus judge/revise/rejudge are merged
// into the single quality gate above — one Sonnet judge scores flow/cohesion/voice/seams
// alongside intent, and the one Opus revise smooths the seams it names.)

// pipeline: each article flows write -> quality gate (+revision) -> post-body
// (relevance gate ∥ figures) independently, with NO barrier anywhere. The quality
// gate runs FIRST — it settles both WHAT the article says (coverage + scope) and
// HOW it reads (flow, cohesion, voice, seams) — so the external-source relevance
// gate and the figures are judged/drawn against the FINAL, polished body. A failed
// author bundle (status null) skips the rest. The downstream content_import then
// runs the deterministic 200 + allowlist gate on whatever external_sources survived
// here, and blocks on an unsatisfied intent_gate verdict (override:
// --allow-unsatisfied); the editorial_gate verdict is advisory (surfaced, not blocking).
//
// THROTTLE — on the WRITE STAGE ONLY. Each author agent is a heavy general-purpose
// run (multi web fetch + long draft). Letting the runtime fan out all specs at once
// (cap = min(16, cores-2)) burst-hammers the API and trips a server-side rate limit
// that fails the WHOLE batch (and still burns the tokens). So author agents pass
// through a semaphore of `writeConcurrency` (default 4).
//
// This used to be implemented as sequential WAVES of `waveSize` specs, each wave a
// self-contained write->gate->visuals pipeline behind a barrier. That throttled the
// right thing in the wrong place: it serialized the ENTIRE 7-stage chain when only
// the write stage needed bounding. Measured on an 11-article cluster, the barrier
// cost 173 minutes of idle agent-slots (23% of all article work) — one article
// finished its chain in 52 minutes and then waited 66 more for a 119-minute sibling
// to clear the barrier, and the critical path was 244 minutes against 119 minutes of
// actual longest-chain work. A semaphore bounds concurrent authors identically while
// letting every downstream stage start the moment its own article is ready.
const writeConcurrency = Math.max(1, (A && Number(A.writeConcurrency || A.waveSize)) || 4)

// Minimal counting semaphore — the workflow sandbox has no Node APIs, so this is
// hand-rolled. `limit` promises may be in flight; the rest queue in FIFO order.
function makeSemaphore(limit) {
  let active = 0
  const queue = []
  const pump = () => {
    while (active < limit && queue.length > 0) {
      const job = queue.shift()
      active++
      Promise.resolve()
        .then(job.fn)
        .then(job.resolve, job.reject)
        .then(() => {
          active--
          pump()
        })
    }
  }
  return (fn) =>
    new Promise((resolve, reject) => {
      queue.push({ fn, resolve, reject })
      pump()
    })
}

const writeSlot = makeSemaphore(writeConcurrency)
log(`generating ${contents.length} article(s) — one continuous pipeline, max ${writeConcurrency} concurrent author(s)`)

const results = await pipeline(
    contents,
    (spec) =>
      writeSlot(() =>
        agent(buildPrompt(spec), {
          label: `write:${spec.slug}`,
          phase: 'Generate',
          agentType: 'general-purpose', // Tools: * — has WebSearch/WebFetch/Read/Write
          model: M_AUTHOR,
        })
      ).then((status) => ({ slug: spec.slug, content_id: spec.content_id, status })),
    // Stage 2 — QUALITY GATE (merged intent + editorial). ONE Sonnet judge scores BOTH
    // coverage/scope AND flow/cohesion/voice/seams; on a real failure of EITHER dimension,
    // ONE Opus revise adds the missing substance + smooths the named seams together; ONE
    // Sonnet re-judge records the honest verdicts. Runs before the relevance gate + visuals
    // so they see the FINAL body. Patches both an intent_gate (content_import blocks on
    // satisfied=false) and an editorial_gate (advisory) verdict into the bundle.
    async (authored, spec) => {
      if (!qualityGatePath || !authored || authored.status == null) {
        return { ...authored, intentGate: null, editorialGate: null }
      }
      let verdict = await agent(buildQualityGatePrompt(spec), {
        label: `quality-gate:${spec.slug}`,
        phase: 'Quality gate',
        agentType: 'general-purpose',
        model: M_JUDGE, // judging both dimensions is verification — Sonnet, not Opus
        schema: COMBINED_VERDICT_SCHEMA,
      })
      // Revise on a real coverage failure (intent is the HARD gate — content_import
      // blocks on satisfied=false), or on an editorial failure severe enough to
      // matter. `reads_well:false` on its own is not that: the editorial verdict is
      // advisory and in practice fails on cohesion 3-4 nits, so revising on it spent
      // an Opus round per article for drafts that shipped unchanged either way.
      // Cohesion <= 2 is the bar for a seam a reader would actually trip over;
      // a judge that omits the score falls back to the old behaviour.
      const cohesion = verdict && Number.isFinite(verdict.cohesion) ? verdict.cohesion : null
      const editorialIsSevere = verdict && verdict.reads_well === false && (cohesion === null || cohesion <= 2)
      let revised = false
      if (verdict && (verdict.satisfied === false || editorialIsSevere)) {
        await agent(buildQualityRevisePrompt(spec, verdict), {
          label: `quality-revise:${spec.slug}`,
          phase: 'Quality gate',
          agentType: 'general-purpose',
          model: M_AUTHOR, // the substance-add / prose-rewrite stays Opus
        })
        revised = true
        // Re-judge once to record the honest final verdicts in the bundle.
        verdict = await agent(buildQualityGatePrompt(spec), {
          label: `quality-rejudge:${spec.slug}`,
          phase: 'Quality gate',
          agentType: 'general-purpose',
          model: M_JUDGE,
          schema: COMBINED_VERDICT_SCHEMA,
        })
      }
      return {
        ...authored,
        intentGate: { satisfied: !!(verdict && verdict.satisfied), revised },
        editorialGate: { reads_well: !!(verdict && verdict.reads_well), revised },
      }
    },
    // Stage 3 — POST-BODY, against the FINAL body. The relevance gate and the
    // figures chain both read only the finished article and nothing else, and
    // neither consumes the other's output, so they run CONCURRENTLY. Measured on an
    // 11-article cluster, serializing the post-body stages cost 338 minutes of chain
    // against 207 minutes when overlapped.
    //
    // The bespoke hero and the NB2 photoreal images used to be two more stages here.
    // They are now produced AFTER content_import by the standalone images workflow
    // (see images.workflow.js + the `generate_post_images` command), because nothing
    // in this run consumes them and holding the article hostage to them added ~123
    // minutes of chain per cluster. content_import records their absence on the Post
    // as `images_ready=False`; the standalone pass fills them in and flips the flag.
    async (judged, spec) => {
      if (!judged || judged.status == null) return { ...judged, gated: false, figures: null }
      const [gate, figures] = await parallel([
        () => {
          if (!gatePath) return Promise.resolve(null)
          return agent(buildGatePrompt(spec), {
            label: `gate:${spec.slug}`,
            phase: 'Relevance gate',
            agentType: 'general-purpose',
            model: M_JUDGE,
          })
        },
        async () => {
          if (!figuresPath) return null
          await agent(buildFiguresPrompt(spec), {
            label: `figures:${spec.slug}`,
            phase: 'Figures',
            agentType: 'general-purpose', // Tools: * — needs Read (vision) + Bash + Write
            model: M_JUDGE, // spec-driven visual production (test-first Sonnet)
            schema: FIGURES_STATUS_SCHEMA,
          })
          const verdict = await agent(buildFigureJudgePrompt(spec), {
            label: `figure-judge:${spec.slug}`,
            phase: 'Figures',
            agentType: 'general-purpose',
            model: M_JUDGE,
            schema: FIGURE_VERDICT_SCHEMA,
          })
          if (!verdict || verdict.all_approved !== false) {
            return { approved: !!(verdict && verdict.all_approved), revised: false }
          }
          await agent(buildFiguresRevisePrompt(spec, verdict), {
            label: `figure-revise:${spec.slug}`,
            phase: 'Figures',
            agentType: 'general-purpose',
            model: M_JUDGE,
          })
          // No re-judge. The figure verdict is ADVISORY — content_import only prints
          // "figure gate NOT fully approved, review the draft preview" and imports
          // anyway — so a second vision pass bought bookkeeping, not a decision, at
          // ~1.4 min per revised article. The verdict below is therefore the
          // PRE-revision one; `revised: true` is what says the figure was redrawn.
          return { approved: false, revised: true }
        },
      ])
      return { ...judged, gated: gate != null, gate, figures }
    }
  )

const ok = results.filter(Boolean)
const gatedCount = ok.filter((r) => r && r.gated).length
const intentChecked = ok.filter((r) => r && r.intentGate).length
const intentSatisfied = ok.filter((r) => r && r.intentGate && r.intentGate.satisfied).length
const intentRevised = ok.filter((r) => r && r.intentGate && r.intentGate.revised).length
const editorialChecked = ok.filter((r) => r && r.editorialGate).length
const editorialPassed = ok.filter((r) => r && r.editorialGate && r.editorialGate.reads_well).length
const editorialRevised = ok.filter((r) => r && r.editorialGate && r.editorialGate.revised).length
const figuresRun = ok.filter((r) => r && r.figures).length
const figuresApproved = ok.filter((r) => r && r.figures && r.figures.approved).length
const figuresRevised = ok.filter((r) => r && r.figures && r.figures.revised).length
log(`done: ${ok.length}/${contents.length} drafts written, ${gatedCount} passed the relevance gate — bundles in ${outDir}`)
log(`intent gate: ${intentSatisfied}/${intentChecked} satisfied (${intentRevised} revised once); unsatisfied drafts are flagged at content_import`)
log(`editorial gate: ${editorialPassed}/${editorialChecked} read cleanly (${editorialRevised} revised once — only cohesion <= 2 triggers it); the verdict is advisory`)
log(`figures: ${figuresApproved}/${figuresRun} articles judge-approved first pass (${figuresRevised} redrawn once, not re-judged); surfaced at content_import`)
log(`hero + NB2 images: NOT produced here — run the standalone images workflow after content_import (posts land with images_ready=False)`)

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
      model: M_JUDGE, // blog→blog anchor planning is judgement, not authoring
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
// The pairwise scoring itself is deterministic (TOKEN-OPTIMIZATION-PLAN.md §1):
// tools/content_pipeline/overlap_score.py reads every bundle body and computes the
// shared-H2 / intro-similarity / repeated-stats / duplicate-widget signals with zero
// LLM tokens, writing overlap-audit.json in the exact schema content_import consumes
// (block: true on score>=75). A cheap Haiku agent just runs the script; then — ONLY
// if the script flagged any pair in the gray band straddling the 75 block line — a
// single Sonnet agent re-reads just those bundle pairs and confirms/overrides `block`.
// Pairs far from the threshold never touch an LLM.
phase('Overlap audit')
const auditBundles = ok.filter((r) => r && r.status != null)
let overlapAudit = { status: 'skipped (need >=2 bundles)' }
if (auditBundles.length >= 2) {
  const scorePath = `${repoRoot}/tools/content_pipeline/overlap_score.py`
  const auditPath = `${outDir}/overlap-audit.json`
  const runSummary = await agent([
    'Run the deterministic Layer-4 overlap scorer over a just-generated bundle batch.',
    `Execute EXACTLY this command with Bash: python3 ${scorePath} ${outDir} ${auditBundles.map((r) => r.slug).join(' ')}`,
    `It writes ${auditPath} and prints a line beginning "SUMMARY " followed by JSON.`,
    'Return that summary JSON\'s fields (written, pairs, blocked, flagged, gray_band, top_score).',
    'Do NOT modify any bundle and do NOT compute anything yourself — just run the script and report.',
  ].join('\n'), {
    label: 'overlap-audit',
    phase: 'Overlap audit',
    agentType: 'general-purpose', // Tools: * — needs Bash
    model: M_MECH,
    effort: 'low',
    schema: OVERLAP_RUN_SCHEMA,
  })
  const grayBand = (runSummary && Number(runSummary.gray_band)) || 0
  overlapAudit = { status: runSummary, grayReviewed: 0 }
  log(`overlap-audit scored: ${(runSummary && runSummary.pairs) || 0} pair(s), ` +
      `${(runSummary && runSummary.blocked) || 0} block(s), ${grayBand} in the gray band`)
  // Gray-band confirm/override — Sonnet, only when the deterministic score put a pair
  // near the 75 line. The agent edits overlap-audit.json in place (sandbox has no FS).
  if (grayBand > 0) {
    const grayStatus = await agent([
      'Confirm or override the BLOCK flag on the borderline overlap pairs of a blog batch.',
      `1. Read the overlap-audit brief for the block rule IN FULL: ${repoRoot}/content-pipeline/prompts/overlap-audit.md`,
      `2. Read ${auditPath}. Its scores are from a deterministic scorer. For EVERY pair with`,
      `   a score in the inclusive range 65..84 (the gray band around the 75 block line):`,
      `   read BOTH bundles' body_markdown at ${outDir}/<...>.bundle.json (use Bash+python/jq`,
      `   to pull fields so you don't overflow context; a slug maps to the bundle whose "slug"`,
      '   field equals it), then judge whether ONE page would satisfy both readers\' need.',
      '3. Set that pair\'s "block" to true iff it is a genuine near-duplicate a human must resolve,',
      '   else false. Do NOT change any score, and do NOT touch pairs outside 65..84.',
      `4. Write ${auditPath} back with the same schema (pairs sorted by score desc; keep "flagged"`,
      '   as the pairs with score>=60). Modify NO bundle.',
      '5. Return ONLY compact JSON: {"reviewed":N,"blocked_after":M}.',
    ].join('\n'), {
      label: 'overlap-gray-review',
      phase: 'Overlap audit',
      agentType: 'general-purpose', // Tools: * — needs Read + Bash + Write
      model: M_JUDGE,
    })
    overlapAudit.grayReviewed = grayBand
    log(`overlap-audit gray-band review done: ${typeof grayStatus === 'string' ? grayStatus.slice(0, 120) : ''}`)
  }
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
    model: M_JUDGE,
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

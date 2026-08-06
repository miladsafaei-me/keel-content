export const meta = {
  name: 'generate-post-images',
  description:
    "Produce the machine-made visuals a post was imported without — its bespoke featured hero and its in-article NB2 photoreal images — one fresh agent per job, all posts flowing concurrently. Split out of generate.workflow.js because nothing in a generation run consumes these: holding every article's chain open for them cost ~123 minutes per cluster while the drafts themselves were already finished.",
  phases: [
    { title: 'Hero', detail: 'one agent per post designs its featured-image SVG' },
    { title: 'Images', detail: 'one agent per post renders its NB2 photoreal images' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.contents   : the manifest.json "contents" array written by
//                     `manage.py export_pending_visuals` — [{slug, content_id,
//                     hero_needed, image_count}, ...].
//   args.outDir     : the same dir export_pending_visuals wrote (holds
//                     <slug>.bundle.json; the agents patch those files in place).
//   args.repoRoot   : absolute repo root (for the prompt overrides + render script).
//   args.heroPath / args.imagesPath / args.renderPath :
//                     optional absolute overrides; each defaults under repoRoot.
//   args.concurrency: optional cap on concurrent posts (default 6). Unlike the
//                     generator's write throttle this can run high — these agents do
//                     no web research, they render and look.
//   args.agentTypes : optional {visual} map of consumer-defined restricted subagent
//                     types. Both stages draw and look at pixels, so both take the
//                     `visual` role; it defaults to 'general-purpose', leaving an
//                     unconfigured caller unchanged. See the AGENT_TYPES note in
//                     generate.workflow.js — the fixed per-agent floor is ~45% of the
//                     bill, and a restricted definition measured 31,913 tokens against
//                     43,577. Any definition used here MUST include StructuredOutput:
//                     the NB2 stage returns through a schema and would fail silently.
//
// Run it between the two halves of the standalone images pass:
//   manage.py export_pending_visuals --out /tmp/visuals
//   <this workflow over /tmp/visuals/manifest.json contents>
//   manage.py apply_post_images /tmp/visuals

const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const contents = (A && Array.isArray(A.contents) && A.contents) || []
const outDir = (A && A.outDir) || ''
const repoRoot = (A && A.repoRoot) || ''

if (!contents.length) throw new Error('args.contents is empty — pass the manifest.json "contents" array')
if (!outDir || !repoRoot) throw new Error('pass absolute args.outDir and args.repoRoot')

const heroPath = (A && A.heroPath) || `${repoRoot}/content-pipeline/prompts/author-hero.md`
const imagesPath = (A && A.imagesPath) || `${repoRoot}/content-pipeline/prompts/author-images.md`
const renderPath = (A && A.renderPath) || `${repoRoot}/tools/content_pipeline/render_on_server.sh`
// 6 -> 10, the runtime's own ceiling of min(16, cores-2). Measured 2026-08-01, a
// visuals agent costs 16 turns and ~790k tokens of context against 88 turns and
// ~9.9M for an article author, so this stage cannot exhaust a token window the way
// generation can — and unlike generation it has no expensive downstream chain
// competing for the same agent slots, so the cap is the right number rather than a
// number to stay safely under.
const concurrency = Math.max(1, Number(A && A.concurrency) || 10)

// Both jobs are spec-driven visual production judged by looking at pixels — Sonnet,
// not Opus. Same call the generator made when these stages lived inside it.
const M = 'sonnet'

const AGENT_TYPES = (A && typeof A.agentTypes === 'object' && A.agentTypes) || {}
const AT_VISUAL = AGENT_TYPES.visual || 'general-purpose'

const buildHeroPrompt = (item) =>
  [
    'Author the bespoke featured-image hero SVG for ONE already-published-as-draft project blog article.',
    '',
    `1. Read the hero-authoring brief IN FULL: ${heroPath}`,
    `2. The work-order bundle is at: ${outDir}/${item.content_id}.bundle.json`,
    '   Read it — its h1 + title + meta_description + body_markdown tell you what to draw.',
    '3. Design the hero per the brief, then patch a "hero" object ({svg_element, head}) into',
    '   that bundle, leaving every other field untouched. Write the bundle back to its SAME path.',
    `   slug MUST stay "${item.slug}".`,
    '4. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')

const buildImagesPrompt = (item) =>
  [
    'Render the in-article NB2 photoreal images for ONE already-published-as-draft project blog article.',
    '',
    `1. Read the images brief IN FULL: ${imagesPath}`,
    `2. The work-order bundle is at: ${outDir}/${item.content_id}.bundle.json`,
    '   Read it FIRST. If "image_requests" is missing or empty, do NOTHING else and return',
    `   {"slug":"${item.slug}","images":0,"ok":true}.`,
    '3. Otherwise, for each request within the 2-per-1000-words budget, render it ON THE SERVER:',
    `   bash ${renderPath} ${outDir} nb2_image --bundle @W/${item.content_id}.bundle.json --id <id>`,
    '   The wrapper patches the bundle + writes the images back locally. Render one id at a time.',
    '   Then LOOK at each rendered <id>.png yourself (Read tool) and regenerate what is off.',
    '4. The command patches the "images" array itself. Every entry MUST keep the id its',
    '   request carries — the post body holds a pending-image anchor per id, and',
    '   `apply_post_images` matches them by exactly that id. Leave every other field',
    `   untouched. slug stays "${item.slug}".`,
    '5. Return ONLY the compact one-line JSON status described in the brief.',
  ].join('\n')



const IMAGE_AUTHOR_STATUS_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: { slug: { type: 'string' }, images: { type: 'number' }, ok: { type: 'boolean' } },
  required: ['ok'],
}


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

const slot = makeSemaphore(concurrency)

log(`producing visuals for ${contents.length} post(s), max ${concurrency} concurrent`)

// Hero and images touch the SAME bundle file, so per post they must not run
// concurrently — that is the one ordering constraint here. Across posts everything
// is independent, so each post's (hero -> images) chain runs on its own.
const results = await parallel(
  contents.map((item) => () =>
    slot(async () => {
      let hero = false
      let images = { count: 0, approved: true, revised: false }

      if (item.hero_needed !== false) {
        const heroStatus = await agent(buildHeroPrompt(item), {
          label: `hero:${item.slug}`,
          phase: 'Hero',
          agentType: AT_VISUAL,
          model: M,
        })
        hero = heroStatus != null
      }

      if (Number(item.image_count) > 0) {
        const authored = await agent(buildImagesPrompt(item), {
          label: `images:${item.slug}`,
          phase: 'Images',
          agentType: AT_VISUAL, // needs Read (vision) + Bash + Write + StructuredOutput
          model: M,
          schema: IMAGE_AUTHOR_STATUS_SCHEMA,
        })
        const rendered = (authored && Number(authored.images)) || 0
        if (rendered > 0) {
          // VISUAL JUDGING REMOVED (Milad, 2026-08-06) — same call as the figure
          // gate in generate.workflow.js. The verdict was advisory: nothing
          // downstream blocked on it, the draft imported either way, and a human
          // reviews every draft before it can be published. Judging + revising was
          // the single largest discretionary line in the visuals pass.
          images = { count: rendered, approved: null, revised: false }
        }
      }

      return { slug: item.slug, hero, images }
    })
  )
)

const ok = results.filter(Boolean)
const heroes = ok.filter((r) => r.hero).length
const withImages = ok.filter((r) => r.images && r.images.count > 0).length
const imageTotal = ok.reduce((n, r) => n + ((r.images && r.images.count) || 0), 0)

log(`heroes authored: ${heroes}/${contents.length}`)
log(`nb2 images: ${imageTotal} across ${withImages} post(s)`)
log(`next: manage.py apply_post_images ${outDir}  (applies these back + flips images_ready)`)

return {
  requested: contents.length,
  completed: ok.length,
  heroes,
  imageTotal,
  outDir,
  results: ok,
}

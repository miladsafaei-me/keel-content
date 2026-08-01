export const meta = {
  name: 'generate-post-images',
  description:
    "Produce the machine-made visuals a post was imported without — its bespoke featured hero and its in-article NB2 photoreal images — one fresh agent per job, all posts flowing concurrently. Split out of generate.workflow.js because nothing in a generation run consumes these: holding every article's chain open for them cost ~123 minutes per cluster while the drafts themselves were already finished.",
  phases: [
    { title: 'Hero', detail: 'one agent per post designs its featured-image SVG' },
    { title: 'Images', detail: 'one agent per post renders + vision-judges its NB2 photoreal images' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.contents   : the manifest.json "contents" array written by
//                     `manage.py export_pending_visuals` — [{slug, content_id,
//                     hero_needed, image_count}, ...].
//   args.outDir     : the same dir export_pending_visuals wrote (holds
//                     <slug>.bundle.json; the agents patch those files in place).
//   args.repoRoot   : absolute repo root (for the prompt overrides + render script).
//   args.heroPath / args.imagesPath / args.imageJudgePath / args.renderPath :
//                     optional absolute overrides; each defaults under repoRoot.
//   args.concurrency: optional cap on concurrent posts (default 6). Unlike the
//                     generator's write throttle this can run high — these agents do
//                     no web research, they render and look.
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
const imageJudgePath = (A && A.imageJudgePath) || `${repoRoot}/content-pipeline/prompts/image-judge.md`
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

const buildImageJudgePrompt = (item) =>
  [
    'Vision-judge the in-article NB2 images of ONE project blog article. Default to rejecting.',
    '',
    `1. Read the judge brief IN FULL: ${imageJudgePath}`,
    `2. The bundle is at: ${outDir}/${item.content_id}.bundle.json`,
    "   View each image's rendered .png (sibling of its .webp) with the Read tool.",
    '3. Patch the "image_gate" verdict into the bundle (leave every other field untouched;',
    `   SAME path; slug stays "${item.slug}"), then return the structured verdict.`,
  ].join('\n')

const buildImagesRevisePrompt = (item, verdict) => {
  const failed = ((verdict && verdict.images) || []).filter((f) => f && f.approved === false)
  return [
    'REVISE specific in-article NB2 images of ONE project blog article (judge follow-up).',
    '',
    `1. Read the images brief IN FULL: ${imagesPath} (see "Revision mode").`,
    `2. The bundle is at: ${outDir}/${item.content_id}.bundle.json`,
    '3. The vision judge FAILED these images — fix exactly these, nothing else:',
    JSON.stringify(failed, null, 2),
    `4. Regenerate each ON THE SERVER (bash ${renderPath} ${outDir} nb2_image --bundle @W/${item.content_id}.bundle.json --id <id>),`,
    '   or adjust its scene_brief/overlay_text in image_requests first, then regenerate; LOOK at the new .png(s).',
    `5. Write back to the SAME path (slug stays "${item.slug}"); return the one-line JSON status.`,
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
      },
    },
  },
  required: ['all_approved'],
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
          agentType: 'general-purpose',
          model: M,
        })
        hero = heroStatus != null
      }

      if (Number(item.image_count) > 0) {
        const authored = await agent(buildImagesPrompt(item), {
          label: `images:${item.slug}`,
          phase: 'Images',
          agentType: 'general-purpose', // Tools: * — needs Read (vision) + Bash + Write
          model: M,
          schema: IMAGE_AUTHOR_STATUS_SCHEMA,
        })
        const rendered = (authored && Number(authored.images)) || 0
        if (rendered > 0) {
          const verdict = await agent(buildImageJudgePrompt(item), {
            label: `image-judge:${item.slug}`,
            phase: 'Images',
            agentType: 'general-purpose',
            model: M,
            schema: IMAGE_VERDICT_SCHEMA,
          })
          let revised = false
          if (verdict && verdict.all_approved === false) {
            await agent(buildImagesRevisePrompt(item, verdict), {
              label: `image-revise:${item.slug}`,
              phase: 'Images',
              agentType: 'general-purpose',
              model: M,
            })
            revised = true
          }
          // No re-judge: like the figure gate, the image verdict is advisory — the
          // draft is reviewed by a human before publishing either way, so a second
          // vision pass buys bookkeeping rather than a decision.
          images = { count: rendered, approved: !!(verdict && verdict.all_approved), revised }
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

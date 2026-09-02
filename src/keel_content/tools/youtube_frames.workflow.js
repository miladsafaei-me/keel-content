export const meta = {
  name: 'youtube-frames',
  description:
    'Capture the screenshots that carry a YouTube video\'s meaning and prepare them as in-article figures. Reads the timestamped transcript index to choose the moments worth a picture BEFORE any video is downloaded, captures a burst of candidate frames around each one, looks at the candidates to pick the best and caption it, and writes a blog_add_figures manifest. Companion to classify_youtube.workflow.js: that route turns a video into an article, this one gives the article the pictures of what the video actually showed.',
  phases: [
    { title: 'Moments', detail: 'one agent reads the thin transcript index and names the moments worth a screenshot' },
    { title: 'Capture', detail: 'a mechanical agent downloads only those seconds and cuts a burst of candidate frames' },
    { title: 'Select', detail: 'one agent per batch looks at the candidates, picks the winner, and writes alt + caption + placement' },
    { title: 'Finalize', detail: 'a mechanical agent converts the winners to WebP and writes the figures manifest' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.youtubeUrl : the source video.
//   args.slug       : the post slug the figures belong to (names the WebP files).
//   args.workDir    : an absolute scratch dir OUTSIDE any git worktree - a worktree is
//                     deleted at session end and would take the frames with it.
//   args.bodyPath   : optional path to the article's markdown or rendered HTML. Supplied,
//                     the Select stage anchors each figure to a real heading id; omitted,
//                     placement is left blank for a human to fill before the retrofit.
//   args.shots      : how many screenshots to take (default 6).
//   args.agentTypes : optional {visual, mech} map of consumer-defined restricted subagent
//                     types, matching generate.workflow.js.
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const youtubeUrl = (A && A.youtubeUrl) || ''
const slug = (A && A.slug) || ''
const workDir = (A && A.workDir) || ''
const bodyPath = (A && A.bodyPath) || ''
const shots = Number(A && A.shots) > 0 ? Number(A.shots) : 6
if (!youtubeUrl) throw new Error('pass args.youtubeUrl')
if (!slug) throw new Error('pass args.slug (it names the WebP files and the retrofit target)')
if (!workDir) throw new Error('pass args.workDir - an absolute path OUTSIDE any git worktree')

const AGENT_TYPES = (A && typeof A.agentTypes === 'object' && A.agentTypes) || {}
const at = (role) => AGENT_TYPES[role] || undefined

// Model tiering, stated explicitly per stage rather than inherited from the session.
// Both questions here are bounded judgement against material the agent is handed -
// which moment, which frame - so both sit on the mid tier; the mechanical stages run
// a script and report its output, and carry no model of their own.
const M_JUDGE = 'sonnet'

const CMD = 'python -m keel_content.core.youtube_frames'

// How many moments one Select agent judges at a time. Each moment brings several
// images, and a bounded batch keeps any single request answerable.
const SELECT_BATCH = 4

const MOMENTS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['moments'],
  properties: {
    moments: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['timecode', 'key', 'label'],
        properties: {
          timecode: { type: 'string', description: 'MM:SS or HH:MM:SS, inside the video length' },
          key: { type: 'string', description: 'short kebab-case id, unique in this video' },
          label: { type: 'string', description: 'one plain sentence naming what should be visible' },
        },
      },
    },
  },
}

const SELECTION_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['selections'],
  properties: {
    selections: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['key', 'winner', 'alt', 'caption', 'after_heading_id', 'after_paragraphs', 'usable'],
        properties: {
          key: { type: 'string' },
          winner: { type: 'string', description: 'candidate filename, exactly as listed' },
          alt: { type: 'string', description: 'accessible description of the image' },
          caption: { type: 'string', description: 'one sentence shown under the figure' },
          after_heading_id: { type: 'string', description: 'id of the H2/H3 to place it under; "" if unknown' },
          after_paragraphs: { type: 'integer', description: '0 = directly under the heading' },
          usable: { type: 'boolean', description: 'false when no candidate is worth publishing' },
        },
      },
    },
  },
}

const mech = (command, label) =>
  agent(
    [
      'Run exactly this command and report its stdout and stderr verbatim. Do not edit any file,',
      'do not interpret the result, do not run anything else.',
      '',
      command,
    ].join('\n'),
    { label, phase: undefined, agentType: at('mech') },
  )

phase('Moments')
log(`planning ${youtubeUrl}`)
await mech(`${CMD} plan --url ${JSON.stringify(youtubeUrl)} --out ${JSON.stringify(workDir)}`, 'plan')

const momentsAnswer = await agent(
  [
    `Read this timestamped transcript index: ${workDir}/thin.txt`,
    `It indexes the video ${youtubeUrl}. Metadata is in ${workDir}/video.json.`,
    '',
    `Choose the ${shots} moments where a screenshot of the video would add the most to a written`,
    'article about it. Judge by what is being SHOWN, not by what sounds important:',
    '  - Prefer moments where the speaker is walking through something visual - a chart, a diagram,',
    '    a table of numbers, a settings panel, a result, a worked example.',
    '  - Prefer the moment the thing is fully drawn and explained over the moment it is first',
    '    mentioned; a few seconds later is usually the better picture.',
    '  - Skip introductions, sign-offs, sponsor reads, subscribe requests, and stretches of the',
    '    speaker talking to camera with nothing on screen.',
    '  - Spread the moments across the video rather than clustering them in one section.',
    '',
    'Return only the JSON object.',
  ].join('\n'),
  { label: 'moments', phase: 'Moments', agentType: at('visual'), model: M_JUDGE, schema: MOMENTS_SCHEMA },
)

const moments = (momentsAnswer && momentsAnswer.moments) || []
if (!moments.length) throw new Error('no moments were chosen - nothing to capture')
log(`chose ${moments.length} moment(s)`)

phase('Capture')
await mech(
  [
    `cat > ${workDir}/moments.json <<'EOF'`,
    JSON.stringify({ moments }, null, 2),
    'EOF',
    `${CMD} capture --url ${JSON.stringify(youtubeUrl)} --out ${JSON.stringify(workDir)} --moments ${workDir}/moments.json`,
  ].join('\n'),
  'capture',
)

phase('Select')
const batches = []
for (let i = 0; i < moments.length; i += SELECT_BATCH) batches.push(moments.slice(i, i + SELECT_BATCH))

const buildSelectPrompt = (batch) =>
  [
    `The candidate frames for each moment are listed in ${workDir}/candidates.json, keyed by the`,
    'moment id. Read that file, then LOOK AT every candidate image for the moments below.',
    '',
    ...batch.map((m) => `MOMENT ${m.key} - ${m.label}`),
    '',
    'For each moment choose the single best frame. These are frames sampled a few seconds either',
    'side of one point in the video, so most moments have a good one and a bad one. Judge in this',
    'order: (1) does it actually show what the label describes; (2) is the visual complete - the',
    'whole chart or panel in view, labels readable, not cut off, not mid-scroll, not mid-transition,',
    'not blurred; (3) is it free of clutter that does not belong in an article. Prefer a frame',
    'showing the subject over one showing the presenter. If nothing is publishable, still name the',
    'least bad frame and set usable to false.',
    '',
    'Write alt as an accessible description of the image, and caption as one sentence under 140',
    'characters. Neither may mention the video, the presenter, or that this is a screenshot.',
    '',
    bodyPath
      ? `Then read the article at ${bodyPath}, find the heading each figure belongs under, and set`
        + ' after_heading_id to that heading\'s id anchor and after_paragraphs to how many paragraphs'
        + ' after the heading it should sit (0 = directly under it).'
      : 'No article body was supplied: set after_heading_id to "" and after_paragraphs to 1.',
    '',
    'Return one selection per moment listed above. Return only the JSON object.',
  ].join('\n')

const answers = await parallel(
  batches.map((batch) => () =>
    agent(buildSelectPrompt(batch), {
      label: `select:${batch[0].key}`,
      phase: 'Select',
      agentType: at('visual'), // needs Read for vision + StructuredOutput
      model: M_JUDGE,
      schema: SELECTION_SCHEMA,
    }),
  ),
)

const selections = answers.flatMap((a) => (a && a.selections) || [])
const usable = selections.filter((s) => s && s.usable !== false)
log(`selected ${selections.length}, of which ${usable.length} are publishable`)
if (!usable.length) return { slug, moments, selections, manifest: null, note: 'no publishable frame' }

phase('Finalize')
await mech(
  [
    `cat > ${workDir}/selection.json <<'EOF'`,
    JSON.stringify({ selections: usable }, null, 2),
    'EOF',
    `${CMD} finalize --out ${JSON.stringify(workDir)} --slug ${JSON.stringify(slug)} --selection ${workDir}/selection.json`,
  ].join('\n'),
  'finalize',
)

return {
  slug,
  moments,
  selections,
  manifest: `${workDir}/figures-manifest.json`,
  figuresDir: `${workDir}/${slug}.figures`,
  next: `./manage.py blog_add_figures --slug ${slug} --manifest <manifest copied into the container>`,
}

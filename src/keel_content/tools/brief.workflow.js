export const meta = {
  name: 'brief-worklist',
  description:
    'Source-agnostic brief stage: a CLUSTER PASS first divides the need-space between siblings (element ownership, scope fences, link-terms — skipped when the cluster already carries a brief), then one independent agent per article crawls the stored evidence URLs (spec.competitor_urls; WebSearch only as fallback), writes an intent-first structured brief (incl. per-article glossary_targets), and an adversarial JUDGE reviews it against the same contract (one revision round). A final OVERLAP PRECHECK compares the finished briefs pairwise and flags near-duplicates BEFORE any expensive generation runs (the cheap analogue of the post-generation Layer-4 overlap audit). Returns {cluster_briefs, briefs, overlap_warnings} — the session writes it to a file and binds it with `manage.py contentplan_set_brief`.',
  phases: [
    { title: 'Cluster pass', detail: 'one agent per un-briefed cluster: element ownership + scope fences + link-terms' },
    { title: 'Brief', detail: 'one agent per article: crawl stored evidence -> intent-first brief + feasibility + glossary_targets' },
    { title: 'Judge', detail: 'adversarial review per brief; one revision round on "revise"' },
    { title: 'Overlap precheck', detail: 'compare finished briefs pairwise; flag near-duplicate pairs (>=75 resolve before generating, 60-74 review) BEFORE spending generation tokens' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.contents    : the worklist "contents" array from
//                      `manage.py export_worklist --cluster <slug> --target blog --status reconciled --allow-unbriefed`
//                      (lazy briefing: export the cluster whose production turn came).
//   args.briefPath   : absolute path to content-pipeline/prompts/brief-author.md
//   args.clusterPath : absolute path to content-pipeline/prompts/brief-cluster-pass.md
//   args.judgePath   : absolute path to content-pipeline/prompts/brief-judge.md
//                      (agents READ these files; paths only, so the contracts stay
//                      versioned in the repo, not frozen into this script).
//   args.waveSize    : optional concurrency throttle (default 4 — same rationale as
//                      generate.workflow.js: an unthrottled fan-out trips API limits).
//   args.limit       : optional cap for a dry-run (limit: 1 first, inspect, then full).

const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const contents = Array.isArray(A.contents) ? A.contents : []
const briefPath = A.briefPath || ''
const clusterPath = A.clusterPath || ''
const judgePath = A.judgePath || ''
const waveSize = Math.max(1, A.waveSize || 4)
const limit = A.limit || 0
if (!contents.length) {
  throw new Error('args.contents is empty — export the cluster first: ' +
    'manage.py export_worklist --cluster <slug> --target blog --status reconciled --allow-unbriefed --out /tmp/wl.json')
}
if (!briefPath) throw new Error('args.briefPath is required (content-pipeline/prompts/brief-author.md)')
if (!clusterPath) throw new Error('args.clusterPath is required (content-pipeline/prompts/brief-cluster-pass.md)')
if (!judgePath) throw new Error('args.judgePath is required (content-pipeline/prompts/brief-judge.md)')

const BRIEF_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['slug', 'brief', 'feasibility'],
  properties: {
    slug: { type: 'string' },
    feasibility: { type: 'string', enum: ['llm_full', 'llm_with_assets', 'human_only'] },
    brief: {
      type: 'object',
      additionalProperties: false,
      required: ['user_problem', 'intent_statement', 'answer_strategy', 'essential_elements',
                 'complementary_elements', 'glossary_targets', 'keyword_usage', 'headings_outline',
                 'title', 'h1', 'evidence', 'scope_excludes', 'asset_predictions',
                 'business_bridge', 'rationale'],
      properties: {
        user_problem: { type: 'string' },
        intent_statement: { type: 'string' },
        answer_strategy: { type: 'string' },
        essential_elements: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['element', 'why'], properties: { element: { type: 'string' }, why: { type: 'string' } } } },
        complementary_elements: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['element', 'why'], properties: { element: { type: 'string' }, why: { type: 'string' } } } },
        glossary_targets: { type: 'array',
          description: 'The 3-8 glossary terms genuinely central to THIS article (entity + core concepts) that the author should weave into the body and link on first mention. Selection lives here; linking stays in the author pass. May be [] only when no glossary term is genuinely central.',
          items: { type: 'object', additionalProperties: false, required: ['term', 'why'],
            properties: { term: { type: 'string' }, why: { type: 'string' } } } },
        keyword_usage: { type: 'object', additionalProperties: false,
          required: ['primary', 'supporting', 'rules'],
          properties: { primary: { type: 'string' },
                        supporting: { type: 'array', items: { type: 'string' } },
                        rules: { type: 'string' } } },
        headings_outline: { type: 'array', items: { type: 'string' } },
        title: { type: 'string' },
        h1: { type: 'string' },
        evidence: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['url', 'type', 'structure_notes'],
          properties: { url: { type: 'string' }, type: { type: 'string' }, structure_notes: { type: 'string' } } } },
        scope_excludes: { type: 'array', items: { type: 'string' } },
        asset_predictions: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['type', 'description', 'placement'],
          properties: { type: { type: 'string' }, description: { type: 'string' }, placement: { type: 'string' } } } },
        business_bridge: { type: 'object', additionalProperties: false,
          required: ['intensity', 'surface', 'user_moment', 'honest_claim',
                     'fit_boundary', 'placement_hint', 'rationale'],
          properties: {
            intensity: { type: 'string', enum: ['none', 'mention', 'worked_example', 'next_step'] },
            surface: { type: 'string' },
            user_moment: { type: 'string' },
            honest_claim: { type: 'string' },
            fit_boundary: { type: 'string' },
            placement_hint: { type: 'string' },
            rationale: { type: 'string' },
          } },
        rationale: { type: 'string' },
      },
    },
  },
}

const CLUSTER_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['cluster_slug', 'cluster_brief'],
  properties: {
    cluster_slug: { type: 'string' },
    cluster_brief: {
      type: 'object',
      additionalProperties: false,
      required: ['shared_context', 'element_ownership', 'scope_fences', 'link_terms', 'link_plan', 'notes'],
      properties: {
        shared_context: { type: 'string' },
        element_ownership: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['element', 'owner_slug', 'why'],
          properties: { element: { type: 'string' }, owner_slug: { type: 'string' }, why: { type: 'string' } } } },
        scope_fences: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['slug', 'excludes'],
          properties: { slug: { type: 'string' }, excludes: { type: 'array', items: { type: 'string' } } } } },
        link_terms: { type: 'array', items: { type: 'string' } },
        // Directed internal-link plan: which article should link to which sibling at
        // which concept. The author reads the edges where from_slug is its own slug and
        // WRITES A NATURAL ANCHOR HOME for each anchor_concept while drafting, so the
        // post-hoc cluster-link pass wires a designed anchor instead of hunting for an
        // opportunistic verbatim phrase. Derived from element_ownership (link to the
        // sibling that OWNS a concept this article only references).
        link_plan: { type: 'array', items: { type: 'object', additionalProperties: false,
          required: ['from_slug', 'to_slug', 'anchor_concept', 'why'],
          properties: { from_slug: { type: 'string' }, to_slug: { type: 'string' },
            anchor_concept: { type: 'string' }, why: { type: 'string' } } } },
        notes: { type: 'string' },
      },
    },
  },
}

const JUDGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'scores', 'reasons', 'required_fixes'],
  properties: {
    verdict: { type: 'string', enum: ['pass', 'revise'] },
    scores: { type: 'object', additionalProperties: false,
      required: ['intent_fidelity', 'flow_coherence', 'evidence_grounding', 'differentiation',
                 'scope_discipline', 'business_bridge'],
      properties: { intent_fidelity: { type: 'integer' }, flow_coherence: { type: 'integer' },
                    evidence_grounding: { type: 'integer' }, differentiation: { type: 'integer' },
                    scope_discipline: { type: 'integer' }, business_bridge: { type: 'integer' } } },
    reasons: { type: 'string' },
    required_fixes: { type: 'array', items: { type: 'string' } },
  },
}

const specCore = (spec) => ({
  slug: spec.slug,
  title: spec.title,
  h1: spec.h1,
  intent: spec.intent,
  intent_frame: spec.intent_frame,
  entity: spec.entity,
  role: spec.role,
  topic_cluster: spec.topic_cluster,
  markets: spec.markets,
  audience_roles: spec.audience_roles,
  audience_levels: spec.audience_levels,
  scope_includes: spec.scope_includes,
  scope_excludes: spec.scope_excludes,
  keywords: spec.keywords || [],
  competitor_urls: spec.competitor_urls || [],
  bridge_candidates: spec.bridge_candidates || [],
})

// ---- Phase 1: cluster pass — only for clusters arriving WITHOUT a brief --------
phase('Cluster pass')
const bySlug = new Map()
for (const spec of contents) {
  const key = spec.topic_cluster_slug || spec.topic_cluster || ''
  if (!bySlug.has(key)) bySlug.set(key, [])
  bySlug.get(key).push(spec)
}
const clusterBriefs = new Map() // cluster key -> cluster_brief object
const clusterBriefsOut = []
for (const [key, specs] of bySlug) {
  const existing = specs.find((s) => s.cluster_brief && Object.keys(s.cluster_brief).length)
  if (existing) {
    // Late-addition case: the cluster was already passed — newcomers brief in
    // CONSTRAINED mode against the existing contract; no re-pass.
    clusterBriefs.set(key, existing.cluster_brief)
    log(`cluster ${key}: existing cluster brief — constrained mode, no re-pass`)
    continue
  }
  const members = specs.map((s) => ({ slug: s.slug, title: s.title, intent: s.intent, role: s.role }))
  const produced = (specs[0].cluster_siblings || []).map((s) => ({
    slug: s.slug, title: s.title, intent: s.intent, role: s.role, produced: true,
  }))
  const res = await agent([
    `Read the cluster-pass contract at ${clusterPath} and follow it exactly.`,
    '',
    `CLUSTER: ${specs[0].topic_cluster || key} (slug: ${key})`,
    'PLANNED MEMBERS (you divide the need-space between these):',
    JSON.stringify(members, null, 2),
    'PRODUCED SIBLINGS (settled law — never re-assign what they own):',
    JSON.stringify(produced, null, 2),
    '',
    'Return exactly the JSON object the contract specifies; cluster_slug verbatim.',
  ].join('\n'), {
    label: `cluster-pass:${key.slice(0, 32)}`,
    phase: 'Cluster pass',
    schema: CLUSTER_SCHEMA,
    agentType: 'general-purpose',
  })
  if (res && res.cluster_brief) {
    clusterBriefs.set(key, res.cluster_brief)
    clusterBriefsOut.push({ cluster_slug: key, cluster_brief: res.cluster_brief })
    log(`cluster ${key}: cluster brief written (${(res.cluster_brief.element_ownership || []).length} owned element(s))`)
  } else {
    log(`FAILED cluster pass: ${key} — its articles will brief without a cluster contract`)
  }
}

// ---- Phase 2 + 3: per-article brief, then adversarial judge (one revision) -----
const buildPrompt = (spec, judgeFeedback) => [
  `Read the brief-writer contract at ${briefPath} and follow it exactly.`,
  '',
  'Write the production brief for this ONE planned article. The spec carries the',
  'stored evidence URLs (competitor_urls) — CRAWL those (WebFetch 3-6); WebSearch',
  'only if the list is empty. The evidence informs your design, never dictates it.',
  '',
  'SPEC:',
  JSON.stringify(specCore(spec), null, 2),
  '',
  'CLUSTER BRIEF (binding — never claim a sibling-owned element; link instead):',
  JSON.stringify(clusterBriefs.get(spec.topic_cluster_slug || spec.topic_cluster || '') || {}, null, 2),
  '',
  ...(judgeFeedback ? [
    'A judge reviewed your previous attempt and requires fixes. Address EVERY fix:',
    JSON.stringify(judgeFeedback, null, 2),
    '',
    'YOUR PREVIOUS BRIEF (revise it — keep what the judge did not flag):',
    JSON.stringify(judgeFeedback._previous, null, 2),
    '',
  ] : []),
  'Respect the scope fences (scope_includes / scope_excludes) — the brief must not',
  'design content the reconcile step fenced OUT of this article.',
  'Return exactly the JSON object the contract specifies. slug must be verbatim.',
].join('\n')

const judgePrompt = (spec, briefEntry) => [
  `Read the brief-judge contract at ${judgePath} and follow it exactly.`,
  '',
  'Judge this brief adversarially — try to break it against the rubric.',
  '',
  'SPEC:',
  JSON.stringify(specCore(spec), null, 2),
  '',
  'CLUSTER BRIEF:',
  JSON.stringify(clusterBriefs.get(spec.topic_cluster_slug || spec.topic_cluster || '') || {}, null, 2),
  '',
  'THE BRIEF UNDER REVIEW:',
  JSON.stringify(briefEntry, null, 2),
  '',
  'Return exactly the JSON object the contract specifies.',
].join('\n')

const briefOne = async (spec) => {
  let entry = await agent(buildPrompt(spec, null), {
    label: `brief:${(spec.slug || '').slice(0, 40)}`,
    phase: 'Brief', schema: BRIEF_SCHEMA, agentType: 'general-purpose',
  })
  if (!entry) return null
  if (entry.slug !== spec.slug) entry.slug = spec.slug
  let verdict = await agent(judgePrompt(spec, entry), {
    label: `judge:${(spec.slug || '').slice(0, 40)}`,
    phase: 'Judge', schema: JUDGE_SCHEMA, agentType: 'general-purpose',
  })
  let revised = false
  if (verdict && verdict.verdict === 'revise') {
    const feedback = { ...verdict, _previous: entry }
    const second = await agent(buildPrompt(spec, feedback), {
      label: `revise:${(spec.slug || '').slice(0, 40)}`,
      phase: 'Judge', schema: BRIEF_SCHEMA, agentType: 'general-purpose',
    })
    if (second) {
      if (second.slug !== spec.slug) second.slug = spec.slug
      entry = second
      revised = true
      verdict = await agent(judgePrompt(spec, entry), {
        label: `rejudge:${(spec.slug || '').slice(0, 38)}`,
        phase: 'Judge', schema: JUDGE_SCHEMA, agentType: 'general-purpose',
      })
    }
  }
  // The final verdict rides the brief itself — visible in /admin-os and durable.
  entry.brief._judge = verdict
    ? { verdict: verdict.verdict, scores: verdict.scores, reasons: verdict.reasons, revised }
    : { verdict: 'unjudged', revised }
  return entry
}

const queue = limit ? contents.slice(0, limit) : contents
log(`briefing ${queue.length} article(s) in waves of ${waveSize}` +
    (limit ? ` (dry-run limit ${limit} of ${contents.length})` : ''))

const briefs = []
for (let i = 0; i < queue.length; i += waveSize) {
  const wave = queue.slice(i, i + waveSize)
  const results = await parallel(wave.map((spec) => () => briefOne(spec)))
  for (let j = 0; j < wave.length; j++) {
    if (!results[j]) { log(`FAILED brief: ${wave[j].slug}`); continue }
    briefs.push(results[j])
  }
  log(`${briefs.length}/${queue.length} briefs done`)
}

const feas = briefs.reduce((m, b) => { m[b.feasibility] = (m[b.feasibility] || 0) + 1; return m }, {})
const passed = briefs.filter((b) => b.brief._judge && b.brief._judge.verdict === 'pass').length
log(`brief stage done: ${briefs.length} brief(s), ${passed} judge-passed ` +
    `(llm_full=${feas.llm_full || 0} llm_with_assets=${feas.llm_with_assets || 0} human_only=${feas.human_only || 0}).`)

// ---- Phase 4: overlap precheck — cheap near-duplicate detection on the BRIEFS,
// BEFORE any generation runs. The post-generation overlap audit (Layer 4) catches
// near-duplicates only after the whole expensive write+gates+figures+hero chain has
// already been spent on BOTH articles of a colliding pair (and then hard-blocks them
// at import). The briefs already carry enough signal to catch the same collision for
// the price of one small agent: title/h1, intent_statement, headings_outline,
// essential elements, scope_excludes. Same thresholds as the generation-time audit
// (>=75 = must resolve before generating; 60-74 = review) so the two layers speak the
// same language. Advisory: it returns warnings, it does not mutate briefs.
phase('Overlap precheck')
const OVERLAP_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['pairs'],
  properties: {
    pairs: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['slug_a', 'slug_b', 'score', 'reason', 'recommendation'],
      properties: {
        slug_a: { type: 'string' }, slug_b: { type: 'string' },
        score: { type: 'integer', description: '0-100 topical/need overlap; 75+ = one page would satisfy both.' },
        reason: { type: 'string' },
        recommendation: { type: 'string', enum: ['merge', 'rescope', 'keep'] },
      } } },
  },
}
let overlapWarnings = []
if (briefs.length >= 2) {
  const cores = briefs.map((b) => ({
    slug: b.slug,
    title: b.brief.title,
    h1: b.brief.h1,
    intent: b.brief.intent_statement,
    headings: b.brief.headings_outline || [],
    essential: (b.brief.essential_elements || []).map((e) => e.element),
    scope_excludes: b.brief.scope_excludes || [],
  }))
  const overlapRes = await agent([
    'Precheck a just-briefed batch of blog articles for NEAR-DUPLICATE pairs — pairs whose',
    'briefs describe so much of the same underlying user need that ONE page would satisfy both.',
    'This runs BEFORE generation: catching a duplicate here saves the full cost of writing,',
    'gating, drawing figures, and designing a hero for BOTH articles (which would then hard-block',
    'at import anyway).',
    '',
    'Score each genuinely-overlapping pair 0-100 on shared USER NEED (not just shared words):',
    'weigh overlapping essential elements, near-identical headings_outline, and an intent_statement',
    'that answers the same question. scope_excludes that already fence the pair apart LOWER the score.',
    'Only report pairs scoring >=60. For each: score, a one-line reason, and a recommendation',
    '(merge = one page should own the need; rescope = split the need with fences; keep = they only',
    'look similar but serve distinct needs). Distinct qualifier spokes (for-scalping vs -for-API) are',
    'NORMALLY keep. Default to NOT flagging when unsure — false alarms cost human review time.',
    '',
    'BRIEF CORES:',
    JSON.stringify(cores, null, 2),
    '',
    'Return the pairs array (empty if nothing overlaps >=60).',
  ].join('\n'), {
    label: 'brief-overlap',
    phase: 'Overlap precheck',
    schema: OVERLAP_SCHEMA,
    agentType: 'general-purpose',
  })
  overlapWarnings = ((overlapRes && overlapRes.pairs) || []).filter((p) => p && p.score >= 60)
  const hard = overlapWarnings.filter((p) => p.score >= 75)
  if (hard.length) {
    log(`OVERLAP PRECHECK: ${hard.length} pair(s) >=75 — RESOLVE these (merge/rescope) BEFORE generating; ` +
        'generating them wastes tokens and they hard-block at import: ' +
        hard.map((p) => `${p.slug_a}~${p.slug_b}(${p.score})`).join(', '))
  }
  const soft = overlapWarnings.filter((p) => p.score >= 60 && p.score < 75)
  if (soft.length) {
    log(`overlap precheck: ${soft.length} pair(s) 60-74 to review: ` +
        soft.map((p) => `${p.slug_a}~${p.slug_b}(${p.score})`).join(', '))
  }
  if (!overlapWarnings.length) log('overlap precheck: no near-duplicate brief pairs — clear to generate')
} else {
  log('overlap precheck skipped (fewer than 2 briefs to compare)')
}

log('Write {cluster_briefs, briefs, overlap_warnings} to briefs.json and bind it: ' +
    'manage.py contentplan_set_brief briefs.json (resolve any overlap_warnings >=75 first)')

return { cluster_briefs: clusterBriefsOut, briefs, overlap_warnings: overlapWarnings }

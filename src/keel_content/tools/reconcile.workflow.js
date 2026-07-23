export const meta = {
  name: 'reconcile-intent-worklist',
  description:
    'Layer 1 of cannibalization prevention (CANNIBALIZATION-PREVENTION-PLAN.md §3). The binding pre-generation gate: given the deterministic bucketing from intent_registry.py, (1) assign each residual spec a canonical_key by normalizing against the live controlled vocabulary — no embeddings, reuse-or-mint; (2) for every same-key collision (within OR cross cluster, decision #3), READ the real grouped competitor pages of each spec (decision #2, never a guessed keyword), run the sufficiency test, and return merge / re-scope / keep + a confidence. The verdicts feed intent_registry.py apply, which enforces safe-by-default (merge only on high confidence) and writes worklist.reconciled.json. This workflow only PRODUCES verdicts — it generates nothing and decides nothing destructive itself.',
  phases: [
    { title: 'Normalize', detail: 'assign a canonical_key to each residual spec — reuse-or-mint against the live vocabulary' },
    { title: 'Adjudicate', detail: 'read the real competitor pages per collision; merge / re-scope / keep + confidence' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.bucket : the FULL output of `intent_registry.py bucket <worklist.json>`
//                 (read the JSON in the session and hand the parsed object in — the
//                 workflow sandbox has no filesystem, so it cannot read the file).
// Output: { normalizations: {cid: canonical_key}, adjudications: [...] } — write it
//         to a file in the session and run `intent_registry.py apply <worklist> <that>`.

const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const B = (A && A.bucket) || A
const buckets = (B && Array.isArray(B.buckets) && B.buckets) || []
const registryKeys = (B && Array.isArray(B.registry_keys) && B.registry_keys) || []
if (!buckets.length) {
  throw new Error('args.bucket.buckets is empty — run `intent_registry.py bucket <worklist.json>` and pass its parsed JSON as args.bucket')
}

// ── schemas ────────────────────────────────────────────────────────────────
const NORMALIZE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['assignments'],
  properties: {
    assignments: {
      type: 'array',
      description: 'One entry per spec you were given. canonical_key is a short kebab-case label for the underlying USER NEED (entity + goal), NOT the title. Reuse an existing key verbatim when the need fits it; only mint a new key when none fits.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['content_id', 'canonical_key', 'reused'],
        properties: {
          content_id: { type: 'string' },
          canonical_key: { type: 'string', pattern: '^[a-z0-9]+(-[a-z0-9]+)*$' },
          reused: { type: 'boolean', description: 'true if canonical_key was taken verbatim from the provided vocabulary' },
        },
      },
    },
  },
}

const ADJUDICATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['action', 'confidence', 'survivor', 'observed_intent', 'rationale'],
  properties: {
    action: { type: 'string', enum: ['merge', 'rescope', 'keep'],
      description: 'merge = one page fully satisfies every spec here (page-losing); rescope = related but each owns a distinct slice, keep both with fences; keep = genuinely different needs that only collided on the key.' },
    confidence: { type: 'string', enum: ['high', 'low'],
      description: 'high ONLY when you are confident. The caller merges only on high; any low downgrades to a safe re-scope.' },
    survivor: { type: 'string', description: 'For merge: the content_id (or the prior_owner content_id) that should OWN the merged need. For rescope/keep: the canonical owner of any shared asset, else the first member.' },
    observed_intent: { type: 'object', additionalProperties: { type: 'string' },
      description: 'content_id -> the ACTUAL user need you read off that spec\'s real competitor pages (one plain sentence each).' },
    scopes: { type: 'object', additionalProperties: {
      type: 'object', additionalProperties: false,
      properties: { includes: { type: 'array', items: { type: 'string' } }, excludes: { type: 'array', items: { type: 'string' } } } },
      description: 'For rescope only: content_id -> {includes, excludes} fences so the two pages do not overlap.' },
    rationale: { type: 'string' },
  },
}

// ── helpers ──────────────────────────────────────────────────────────────
const marketCompatible = (a, b) =>
  a.cross_market || b.cross_market || a.market === b.market

// Within ONE frame bucket, cluster specs that share a canonical_key AND are
// market-compatible (cross-market overlaps every specific market, §2.6). Returns
// candidate groups: any cluster with >=2 batch specs, or a singleton that collides
// with a prior-run registry owner of the same key.
function candidateGroups(bucket, keyByCid) {
  const specs = bucket.specs.map((s) => ({ ...s, _key: s.canonical_key || keyByCid[s.content_id] || '' }))
  const byKey = new Map()
  for (const s of specs) {
    if (!s._key) continue
    if (!byKey.has(s._key)) byKey.set(s._key, [])
    byKey.get(s._key).push(s)
  }
  const groups = []
  for (const [key, rs] of byKey) {
    const clusters = []
    for (const r of rs) {
      let placed = false
      for (const cl of clusters) {
        if (cl.some((o) => marketCompatible(r, o))) { cl.push(r); placed = true; break }
      }
      if (!placed) clusters.push([r])
    }
    for (const cl of clusters) {
      const prior = (cl[0].registry_matches || []).find((m) => m.canonical_key === key) || null
      if (cl.length >= 2 || prior) {
        groups.push({ canonical_key: key, intent_frame: bucket.intent_frame, members: cl, prior_owner: prior })
      }
    }
  }
  return groups
}

// ── prompts ────────────────────────────────────────────────────────────────
const buildNormalizePrompt = (bucket) => {
  const residual = bucket.specs.filter((s) => bucket.needs_normalization.includes(s.content_id))
  const vocab = [...new Set([...(bucket.existing_keys || []), ...registryKeys])].sort()
  return [
    `Assign a canonical_key to each blog spec below. They all share the intent_frame "${bucket.intent_frame}".`,
    '',
    'A canonical_key is a short kebab-case label for the underlying USER NEED — the entity + goal a reader has —',
    'NOT the article title. Two specs that a single page would fully satisfy must get the SAME key, even if their',
    'wording differs (e.g. "algorithmic trading" and "quant trading" both -> automated-rule-based-trading). Two',
    'specs that need genuinely different pages must get DIFFERENT keys.',
    '',
    'SAME-KEY SMELLS (assign the SAME key so the pair is forced into adjudication — these routinely slip through',
    'as "different" phrasings and then cannibalize):',
    '  - A "best X" / "top X" ROUNDUP and a "how to choose X" GUIDE for the same X are the same underlying need',
    '    (choosing X). Same key. (Adjudication then re-scopes: the roundup owns the ranked picks, the guide owns',
    '    the decision criteria/traps.)',
    '  - A title that STRADDLES TWO entities where a sibling owns one of them ("MT4/MT5 brokers" next to an',
    '    "MT4 brokers" spec) — normalize the straddling spec to the DOMINANT single entity so it collides with the',
    '    single-entity sibling instead of quietly claiming both. (Adjudication then fences them to one entity each.)',
    '  - A pillar "best X" and its own how-to/criteria spoke in the same cluster: same key, then re-scope so the',
    '    pillar routes and the spoke teaches — never two pages of the same criteria list.',
    'Genuinely-distinct QUALIFIER spokes (best-broker-for-scalping vs -for-API vs -for-cTrader) are DIFFERENT needs',
    '— keep different keys; their differentiation is enforced downstream by the author brief, not by merging here.',
    '',
    'CONTROLLED VOCABULARY — reuse one of these existing keys VERBATIM when the need fits it; only mint a new',
    'kebab-case key when none fits (keeping the vocabulary small and stable matters):',
    vocab.length ? vocab.map((k) => `  - ${k}`).join('\n') : '  (none yet — you are seeding the vocabulary)',
    '',
    'SPECS (judge the need from the title + entity + keywords; do NOT fetch anything in this step):',
    JSON.stringify(residual.map((s) => ({ content_id: s.content_id, title: s.title, entity: s.entity, market: s.market, keywords: (s.keywords || []).slice(0, 6) })), null, 2),
    '',
    'Return the assignments array (one per spec).',
  ].join('\n')
}

const buildAdjudicatePrompt = (group) => {
  const members = group.members.map((s) => ({
    content_id: s.content_id, title: s.title, entity: s.entity, market: s.market,
    competitor_urls: s.competitor_urls || [],
    keywords: (s.keywords || []).slice(0, 8),
    produced: !!s.produced,
  }))
  return [
    `These ${members.length === 1 ? 'spec collides with an already-committed page' : members.length + ' specs collided on the same canonical_key'}`,
    `("${group.canonical_key}", intent_frame "${group.intent_frame}"). Decide whether they are really one need.`,
    '',
    'METHOD (decision #2 — judge the REAL pages, never a guessed keyword):',
    '1. For EACH spec, WebFetch 2-3 of its competitor_urls (load WebFetch via ToolSearch first if needed) and read',
    '   the page TITLE + opening section. Derive the ACTUAL user need each spec serves (its observed_intent).',
    '   A keyword-route spec has NO competitor_urls — instead WebSearch its top 1-2 keywords (load WebSearch via',
    '   ToolSearch) and read 2-3 of the top-ranking result pages; those pages are its evidence set.',
    '2. Apply the sufficiency test: would ONE page fully satisfy the need of every spec here?',
    '   - YES, one page covers all -> action "merge"; pick the survivor (the best owner of that need).',
    '   - RELATED but each owns a distinct slice (e.g. build vs deploy, general vs market-specific) -> "rescope":',
    '     give each a non-overlapping {includes, excludes} fence so they stop competing. This is the SAFE default',
    '     whenever you are unsure — keep both, fence them.',
    '   - DIFFERENT needs that only happened to share the key -> "keep".',
    '3. Set confidence "high" ONLY if you are confident. The caller MERGES ONLY ON HIGH confidence; any "low"',
    '   on a merge is downgraded to a safe re-scope automatically. Never over-merge on a hunch.',
    '4. A member with produced:true is a LIVE page (a registry seed). When you merge a group containing one,',
    '   the produced member should normally be the survivor — the new demand then enriches that existing page',
    '   instead of spawning a duplicate. Never pick an unproduced spec as survivor over a produced one unless',
    '   the produced page genuinely serves a different need.',
    '',
    group.prior_owner
      ? `PRIOR COMMITTED PAGE (from a past run — already exists; if the new spec is fully covered by it, "merge" with survivor "${group.prior_owner.owner_content_id}"):\n${JSON.stringify(group.prior_owner, null, 2)}` +
        (group.prior_owner.owner_kind === 'glossary_term'
          ? '\nNOTE: the prior owner is a LIVE GLOSSARY TERM page. A what-is need for this term belongs to that page —\nmerging routes the keyword demand into an enrichment report (the team deepens the term page), it does NOT\ndelete anything. Only keep the spec separate if it genuinely needs a different page than a rich term explainer.'
          : '')
      : '(no prior committed page for this key — this is a fresh within-batch collision)',
    '',
    'SPECS:',
    JSON.stringify(members, null, 2),
    '',
    'Return the adjudication object. observed_intent MUST have an entry for every content_id above.',
  ].join('\n')
}

// ── run: pipeline per bucket (normalize -> adjudicate), no cross-bucket barrier ──
log(`reconciling ${buckets.length} frame bucket(s); ${registryKeys.length} key(s) already in the persistent registry`)

const perBucket = await pipeline(
  buckets,
  // stage 1 — normalize residual specs in this bucket
  async (bucket) => {
    const keyByCid = {}
    if (bucket.needs_normalization && bucket.needs_normalization.length) {
      const res = await agent(buildNormalizePrompt(bucket), {
        label: `normalize:${bucket.intent_frame}`,
        phase: 'Normalize',
        schema: NORMALIZE_SCHEMA,
        agentType: 'general-purpose',
      })
      for (const a of (res && res.assignments) || []) keyByCid[a.content_id] = a.canonical_key
    }
    return { bucket, keyByCid }
  },
  // stage 2 — adjudicate every candidate collision in this bucket (nested parallel)
  async ({ bucket, keyByCid }) => {
    const groups = candidateGroups(bucket, keyByCid)
    log(`bucket "${bucket.intent_frame}": ${groups.length} collision group(s) to adjudicate`)
    const verdicts = await parallel(
      groups.map((g, i) => () =>
        agent(buildAdjudicatePrompt(g), {
          label: `adjudicate:${bucket.intent_frame}:${g.canonical_key.slice(0, 20)}#${i}`,
          phase: 'Adjudicate',
          schema: ADJUDICATE_SCHEMA,
          agentType: 'general-purpose',
        }).then((v) => v && ({
          canonical_key: g.canonical_key,
          intent_frame: g.intent_frame,
          members: g.members.map((s) => s.content_id),
          prior_owner: g.prior_owner || null,
          ...v,
        }))
      )
    )
    return { keyByCid, adjudications: verdicts.filter(Boolean) }
  }
)

// flatten the per-bucket results into the apply input shape
const normalizations = {}
const adjudications = []
for (const r of perBucket.filter(Boolean)) {
  Object.assign(normalizations, r.keyByCid)
  adjudications.push(...r.adjudications)
}

const counts = adjudications.reduce((m, a) => { m[a.action] = (m[a.action] || 0) + 1; return m }, {})
log(`reconcile done: ${Object.keys(normalizations).length} key(s) assigned, ${adjudications.length} collision(s) adjudicated ` +
    `(merge=${counts.merge || 0} rescope=${counts.rescope || 0} keep=${counts.keep || 0}). ` +
    `Hand this to: intent_registry.py apply <worklist.json> <this-output.json> --mode suggest`)

return { normalizations, adjudications }

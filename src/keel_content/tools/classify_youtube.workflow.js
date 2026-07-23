export const meta = {
  name: 'classify-youtube-videos',
  description:
    'Read each YouTube video transcript and classify it into a project blog ContentPlan spec — best-fit EXISTING topic cluster (or propose a new one), a same-market classification (market integrity), intent frame, a canonical_key for the cross-run intent registry, a publishable title/h1/slug, audience facets, and glossary terms. Turns the YouTube intake route into a hands-off classify step (the analogue of /seo-clustering for the keyword route): its output feeds contentplan_ingest_youtube --json.',
  phases: [
    { title: 'Classify', detail: 'one agent per video reads its transcript + the site taxonomy and emits a classified spec' },
  ],
}

// Inputs (pass as the Workflow `args` JSON value):
//   args.videos       : [{ youtube_url, transcript_path, title?, channel?, duration? }]
//                       transcript_path is an absolute file the agent reads (kept out
//                       of args so args stay small).
//   args.taxonomyPath : absolute path to a JSON file the agent reads, holding the live
//                       site taxonomy the video is classified INTO:
//                       { clusters:[{slug,name,markets:[...]}], markets:[...],
//                         categories:[...], audience_roles:[...], audience_levels:[...],
//                         glossary_terms:[...], registry:[{canonical_key,need_signature,owner}] }
//                       Fetch fresh from prod so cluster/market/glossary names resolve
//                       and canonical_key can be checked against existing registry owners.
//   args.repoRoot     : absolute repo/worktree root (for BUSINESS-MAP.md market-integrity
//                       + CONTENT-ARCHITECTURE.md taxonomy + SEO.md length caps).
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const videos = (A && Array.isArray(A.videos) && A.videos) || []
const taxonomyPath = (A && A.taxonomyPath) || ''
const repoRoot = (A && A.repoRoot) || ''
if (!videos.length) throw new Error('args.videos is empty — pass [{youtube_url, transcript_path}]')
if (!taxonomyPath) throw new Error('pass args.taxonomyPath (a JSON file with clusters/markets/audience/glossary/registry)')
if (!repoRoot) throw new Error('pass args.repoRoot (for BUSINESS-MAP.md / CONTENT-ARCHITECTURE.md / SEO.md)')

const SPEC_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'youtube_url', 'title', 'h1', 'slug', 'intent', 'intent_frame', 'entity',
    'canonical_key', 'role', 'markets', 'topic_cluster', 'topic_cluster_slug',
    'is_new_cluster', 'audience_roles', 'audience_levels', 'glossary_terms', 'rationale',
  ],
  properties: {
    youtube_url: { type: 'string' },
    title: { type: 'string', maxLength: 65, description: 'SEO title tag, <=65 chars' },
    h1: { type: 'string', maxLength: 65, description: 'On-page heading, distinct from title, <=65 chars' },
    slug: { type: 'string', description: 'kebab-case URL identity' },
    intent: { type: 'string', description: 'One-line user need this article satisfies' },
    intent_frame: { type: 'string', enum: ['what-is', 'how-to', 'guide', 'best', 'compare', 'review', 'vs'] },
    entity: { type: 'string', description: 'The primary entity/topic (e.g. "ICT Venom model")' },
    canonical_key: { type: 'string', description: 'Controlled-vocabulary key for the user NEED (dedup spine). Reuse an existing registry owner key ONLY if this is genuinely the same need; else a fresh concise slug.' },
    role: { type: 'string', enum: ['pillar', 'spoke'], description: 'Almost always spoke; pillar only for a comprehensive hub' },
    markets: { type: 'array', items: { type: 'string' }, description: 'Usually ONE market from taxonomy.markets (market integrity). Cross-market only if truly market-agnostic.' },
    topic_cluster: { type: 'string', description: 'An existing cluster NAME from taxonomy.clusters, or a new cluster name if none fits' },
    topic_cluster_slug: { type: 'string', description: 'The existing cluster slug (if joining one), else the slugified new name' },
    is_new_cluster: { type: 'boolean', description: 'true when proposing a cluster not in taxonomy.clusters' },
    audience_roles: { type: 'array', items: { type: 'string' } },
    audience_levels: { type: 'array', items: { type: 'string' } },
    glossary_terms: { type: 'array', items: { type: 'string' }, description: 'ONLY terms present in taxonomy.glossary_terms that the video actually covers' },
    rationale: { type: 'string', description: 'One or two sentences: why this cluster + market + canonical_key' },
  },
}

const buildPrompt = (v) =>
  [
    'Classify ONE YouTube video into a project blog ContentPlan spec. Return ONLY the structured object.',
    '',
    `1. READ the transcript first (your PRIMARY evidence): ${v.transcript_path}`,
    v.title ? `   Video title (creator's, for context only): ${v.title}` : '',
    v.channel ? `   Channel: ${v.channel}` : '',
    `2. READ the site taxonomy JSON (your allowed vocabulary): ${taxonomyPath}`,
    '   It has: clusters:[{slug,name,markets}], markets, audience_roles, audience_levels,',
    '   glossary_terms, registry:[{canonical_key,need_signature,owner}].',
    `3. Read these for the rules: ${repoRoot}/BUSINESS-MAP.md (MARKET INTEGRITY — a product/topic routes only to a same-market surface), ${repoRoot}/CONTENT-ARCHITECTURE.md (the cluster/market/audience taxonomy), ${repoRoot}/SEO.md (title & h1 <= 65 chars).`,
    '4. Decide the classification from what the video ACTUALLY teaches (not the creator\'s hype):',
    '   - market: the single best-fit market from taxonomy.markets (market integrity — never cross a crypto topic into a binary market, etc.). Use "Cross-market" only if genuinely market-agnostic.',
    '   - topic_cluster: choose the SINGLE best-fit EXISTING cluster from taxonomy.clusters and copy its exact slug into topic_cluster_slug (is_new_cluster=false). ONLY if NONE genuinely fits, propose a NEW cluster (clear name, slugified, is_new_cluster=true). Prefer joining an existing cluster — new clusters are the exception. Respect the cluster\'s markets (do not put a forex video into a crypto-only cluster).',
    '   - canonical_key: a concise controlled-vocabulary slug for the user NEED (the intent-registry dedup spine). Compare against taxonomy.registry; reuse an owner\'s key ONLY if this video answers the SAME need (a genuine merge), otherwise mint a fresh concise key.',
    '   - intent_frame: what-is | how-to | guide | best | compare | review | vs (match the video\'s teaching shape).',
    '   - title (<=65) / h1 (<=65, distinct, reader-facing) / slug (kebab-case): publishable, honest, keyword-natural — no clickbait, no unverifiable win-rate/"risk-free"/"guaranteed" claims.',
    '   - audience_roles / audience_levels: choose from taxonomy.audience_roles / taxonomy.audience_levels.',
    '   - glossary_terms: ONLY terms present in taxonomy.glossary_terms that the video genuinely covers.',
    '   - role: spoke (default) unless this is a comprehensive hub for the whole cluster.',
    `5. Set youtube_url to exactly: ${v.youtube_url}`,
    'Compliance: English only; classify by the video\'s real substance; obey market integrity.',
  ].filter(Boolean).join('\n')

phase('Classify')
log(`classifying ${videos.length} video(s) — one agent each, reading its transcript`)

const specs = await parallel(
  videos.map((v) => () =>
    agent(buildPrompt(v), { label: `classify:${v.youtube_url}`, phase: 'Classify', schema: SPEC_SCHEMA })
      .then((s) => (s ? { ...s, youtube_url: v.youtube_url, source_transcript_path: v.transcript_path, target: 'blog' } : null))
  )
)

const classified = specs.filter(Boolean)
log(`classified ${classified.length}/${videos.length}`)
return { count: classified.length, specs: classified }

// codebase-security-audit.js
//
// Exhaustive security discovery + adversarial verification, powered by the Workflow tool.
// Invoked by the `/codebase-security-scan audit` skill mode.
//
// CONTRACT: this workflow RETURNS structured findings as JSON. It does NOT write the
// report, assign SEC-### IDs, or re-evaluate previous findings — the skill's main loop
// does all of that, so the report format stays identical and the resolver/check-specs
// keep working. All agents use agentType 'Explore' (read-only: Read/Grep/Glob, no Write),
// which enforces the no-file-writes boundary at the tool level.
//
// Runtime constraints honored: plain JS (not TS); meta is a pure literal; schemas are
// JSON Schema; no Date.now()/Math.random()/new Date() (only Math.floor is used).

export const meta = {
  name: 'codebase-security-audit',
  description: 'Exhaustive security discovery (loop-until-dry over 6 categories) + multi-skeptic adversarial verification. Returns deduped, verified findings as JSON for the skill to format.',
  phases: [
    { title: 'Context' },
    { title: 'Discovery' },
    { title: 'Verify' },
  ],
}

const CATEGORIES = ['auth', 'injection', 'secrets', 'api', 'config', 'file']
const K_EMPTY = 2          // consecutive dry rounds to stop discovery
const MAX_ROUNDS = 5       // budget guard
const SKEPTICS = ['exploitability', 'compensating-controls', 'spec-intentional']

const FINDER_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['category', 'severity', 'title', 'description', 'file', 'line', 'recommendation'],
        properties: {
          category: { type: 'string', enum: CATEGORIES },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'info'] },
          title: { type: 'string' },
          description: { type: 'string' },
          file: { type: 'string' },
          line: { type: 'integer', minimum: 0 },
          cwe: { type: 'string' },
          codeSnippet: { type: 'string' },
          recommendation: { type: 'string' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['lens', 'verdict', 'reason'],
  properties: {
    lens: { type: 'string', enum: SKEPTICS },
    verdict: { type: 'string', enum: ['refuted', 'upheld'] },
    reason: { type: 'string' },
    specReference: { type: 'string' },
  },
}

// Composite dedup key: same file + same line-window + same category collapse to one.
const key = (f) => `${f.file}::${Math.floor(f.line / 5)}::${f.category}`

// --- Phase 1: Context ---
phase('Context')
const context = await agent(
  'Read /knowledge-base/reference and /knowledge-base/specs (if present). Summarize: architecture, auth model, '
  + 'trust boundaries, untrusted entry points, and an explicit list of SPEC\'D-INTENTIONAL '
  + 'behaviors that must NOT be reported as vulnerabilities. Return prose.',
  { label: 'context', phase: 'Context', agentType: 'Explore' }
)

// --- Phase 2: Discovery (exhaustive, loop-until-dry over the 6 categories) ---
phase('Discovery')
const seen = new Set()
const all = []
let dry = 0
let round = 0
while (dry < K_EMPTY && round < MAX_ROUNDS) {
  round++
  const known = JSON.stringify([...seen])
  const results = await parallel(CATEGORIES.map((cat) => () =>
    agent(
      `Category: ${cat}. Context: ${context}. Already found (skip these dedup keys): ${known}. `
      + `Exhaustively scan the codebase for NEW ${cat} vulnerabilities on uncovered surface. `
      + `Return { findings: [...] } matching the schema; empty array if nothing new.`,
      { label: `find:${cat}`, phase: 'Discovery', schema: FINDER_SCHEMA, agentType: 'Explore' }
    )
  ))
  const fresh = results
    .filter(Boolean)
    .flatMap((r) => r.findings || [])
    .filter((f) => !seen.has(key(f)))
  if (!fresh.length) {
    dry++
    log(`round ${round}: dry (${dry}/${K_EMPTY})`)
    continue
  }
  dry = 0
  fresh.forEach((f) => { seen.add(key(f)); all.push(f) })
  log(`round ${round}: +${fresh.length} new (total ${all.length})`)
}

// --- Phase 3: Verify (N diverse-lens skeptics per finding; unanimous-refute drops) ---
phase('Verify')
const verified = await parallel(all.map((f) => () =>
  parallel(SKEPTICS.map((lens) => () =>
    agent(
      `Finding: ${JSON.stringify(f)}. Spec-intentional context: ${context}. Lens: ${lens}. `
      + `Your job is to REFUTE this finding, not confirm it. Return verdict "refuted" or `
      + `"upheld" with a reason (and specReference if spec-intentional).`,
      { label: `verify:${f.file}:${lens}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'Explore' }
    )
  )).then((verdicts) => {
    const vs = verdicts.filter(Boolean)
    const upheld = vs.filter((v) => v.verdict === 'upheld').length
    const total = vs.length || SKEPTICS.length
    const specRefute = vs.find((v) => v.lens === 'spec-intentional' && v.verdict === 'refuted')
    let disposition
    if (specRefute) disposition = 'intentional-design'
    else if (upheld * 2 > total) disposition = 'confirmed'   // majority upheld
    else if (upheld === 0) disposition = 'drop'              // unanimous refute -> false positive
    else disposition = 'needs-review'                        // split / inconclusive
    return {
      ...f,
      disposition,
      specReference: specRefute && specRefute.specReference,
      verification: { upheld, total, lenses: SKEPTICS },
    }
  })
))

// Return survivors only. 'drop' (unanimous refute) never leaves the workflow, so the
// skill/resolver never sees false positives.
return verified.filter(Boolean).filter((r) => r.disposition !== 'drop')

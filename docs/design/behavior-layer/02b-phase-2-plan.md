# Phase 2 — Plan 1: Close the Loop (testbed cucumber-js + BEH-003) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SPEC-001's guard behavior **BEH-003** ("unknown email → generic options; no user enumeration") a real, passing, instrumentable cucumber-js test driven at the HTTP layer, then mark it `accepted` — giving Phase 2 its first observed-coverage target and closing the Phase-1 loop.

**Architecture:** Add cucumber-js (+ tsx, already a devDep) to the **testbed** (`/Users/main/Documents/projects/viva-croatia-testbed`, a throwaway Next.js sandbox — production is untouched). Author real Gherkin steps that invoke the Next.js route handler `app/api/auth/passkey/authenticate/start/route.ts` **in-process** (no browser), asserting the unknown-email response is a valid generic options payload. Flip BEH-003 `proposed → accepted` and confirm deterministic `verify` stays green.

**Tech Stack:** Next.js 16 / TypeScript, Prisma 7 (SQLite `dev.db`), pnpm, `@cucumber/cucumber`, `tsx` (TS loader for step defs), V8 coverage via `c8` (installed here, *used* in Plan 2).

## Global Constraints

- Work ONLY in the testbed `/Users/main/Documents/projects/viva-croatia-testbed`. Never touch `/Users/main/Documents/areas/viva-croatia/webapp` (production).
- The freya-devkit plugin is the **symlinked local-dev install**; scripts are invoked by absolute path under `${CLAUDE_PLUGIN_ROOT}` (the repo).
- Behavior lifecycle: a Gherkin behavior is `accepted` ONLY when its scenario has real steps and **no `TODO(scaffold)` marker** — `verify_links.py` hard-errors otherwise.
- Adapter stays runner-agnostic at the model level: `adapter: cucumber`, `locator: features/auth/passkey-login.feature#<scenario-slug>`.
- Commit in the testbed repo (its own git); these are testbed commits, not freya-devkit commits.

---

### Task 1: Install cucumber-js + coverage tooling in the testbed

**Files:**
- Modify: `package.json` (devDependencies + a `test:bdd` script)
- Create: `cucumber.mjs` (cucumber-js config)
- Create: `features/steps/support/world.ts` (placeholder support file so the loader path resolves)

**Interfaces:**
- Produces: a `pnpm test:bdd` script that runs cucumber-js with tsx-loaded step definitions from `features/**/*.ts`, and `c8` available for Plan 2.

- [ ] **Step 1: Install dependencies**

Run:
```bash
cd /Users/main/Documents/projects/viva-croatia-testbed
pnpm install
pnpm add -D @cucumber/cucumber c8
pnpm prisma generate
```
Expected: install completes; `node_modules/@cucumber/cucumber` exists; Prisma client generated (the start route imports `@/lib/prisma`).

- [ ] **Step 2: Add the cucumber config**

Create `cucumber.mjs`:
```js
export default {
  import: ['features/steps/**/*.ts'],
  loader: ['tsx/esm'],
  paths: ['features/**/*.feature'],
  format: ['progress'],
}
```

- [ ] **Step 3: Add the test script**

Modify `package.json` `scripts` (add this line):
```json
"test:bdd": "cucumber-js"
```

- [ ] **Step 4: Verify cucumber runs and sees the scaffold as UNDEFINED**

Run: `pnpm test:bdd`
Expected: cucumber runs, reports the 3 BEH scaffolds with **undefined steps** (placeholders like `Given <initial state>`). This confirms wiring works before we write real steps. (Non-zero exit is fine here.)

- [ ] **Step 5: Commit**

```bash
git add package.json pnpm-lock.yaml cucumber.mjs
git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com" commit -m "test(bdd): add cucumber-js + tsx + c8 tooling"
```

---

### Task 2: Make BEH-003 a real, passing HTTP-layer scenario

**Files:**
- Modify: `features/auth/passkey-login.feature` (replace ONLY the BEH-003 scenario body; leave BEH-001/002 scaffolds intact)
- Create: `features/steps/passkey_auth_steps.ts` (step definitions invoking the route handler in-process)

**Interfaces:**
- Consumes: `app/api/auth/passkey/authenticate/start/route.ts` — `export async function POST(request: NextRequest)`; on an unknown email it returns `NextResponse.json({ options, challenge })` (HTTP 200) with generic options (verified by reading the handler).
- Produces: a passing scenario tagged `@BEH-003` with no `TODO(scaffold)` marker.

- [ ] **Step 1: Write the real BEH-003 scenario (the failing test)**

In `features/auth/passkey-login.feature`, replace the `@BEH-003` scenario block (the one titled `Unknown email does not reveal whether a user exists`) with:
```gherkin
  @BEH-003
  Scenario: Unknown email does not reveal whether a user exists
    Given the passkey authentication endpoint
    When authentication is started for the unregistered email "nobody-xyz@example.com"
    Then the response status is 200
    And the response returns generic authentication options with a challenge
```
Leave the `@BEH-001` and `@BEH-002` scenarios as their existing `TODO(scaffold)` placeholders.

- [ ] **Step 2: Run to verify it fails (undefined steps)**

Run: `pnpm test:bdd`
Expected: the `@BEH-003` scenario fails/undefined — cucumber prints step-definition snippets for the four new steps. (BEH-001/002 remain undefined; that's expected.)

- [ ] **Step 3: Write the step definitions (in-process handler call)**

Create `features/steps/passkey_auth_steps.ts`:
```ts
import { Given, When, Then } from '@cucumber/cucumber'
import assert from 'node:assert/strict'

// Env the route + webauthn config + prisma need when run outside `next`.
process.env.WEBAUTHN_RP_ID ??= 'localhost'
process.env.WEBAUTHN_RP_NAME ??= 'Viva Croatia CMS'
process.env.DATABASE_URL ??= 'file:./dev.db'

let response: Response
let body: any

Given('the passkey authentication endpoint', function () {
  // No setup needed; the handler is imported lazily in the When step.
})

When(
  'authentication is started for the unregistered email {string}',
  async function (email: string) {
    // Import lazily so env vars above are set before the module initializes.
    const { POST } = await import(
      '../../app/api/auth/passkey/authenticate/start/route.ts'
    )
    const req = new Request('http://localhost/api/auth/passkey/authenticate/start', {
      method: 'POST',
      headers: { 'content-type': 'application/json', origin: 'http://localhost' },
      body: JSON.stringify({ email }),
    })
    response = await POST(req as any)
    body = await response.json()
  },
)

Then('the response status is {int}', function (status: number) {
  assert.equal(response.status, status)
})

Then(
  'the response returns generic authentication options with a challenge',
  function () {
    // No-enumeration: an unknown email still yields a normal options payload.
    assert.ok(body.options, 'expected an options object')
    assert.ok(body.challenge, 'expected a challenge')
    assert.equal(body.options.challenge, body.challenge)
  },
)
```

- [ ] **Step 4: Run to verify BEH-003 passes**

Run: `pnpm test:bdd`
Expected: the `@BEH-003` scenario **passes** (4 steps green). If it errors on Prisma/env, fix the env values in Step 3 to match `.env.example` (e.g. correct `DATABASE_URL` path) and re-run until green — the behavior itself already works in the app, so a failure here is a harness/wiring issue, not a code regression.

- [ ] **Step 5: Commit**

```bash
git add features/auth/passkey-login.feature features/steps/passkey_auth_steps.ts
git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com" commit -m "test(bdd): real BEH-003 scenario (no user enumeration) via HTTP layer"
```

---

### Task 3: Promote BEH-003 to `accepted` and confirm integrity

**Files:**
- Modify: `knowledge-base/specs/auth/SPEC-001-passkey-login.md` (BEH-003 `state` + the Behavior table row)

**Interfaces:**
- Consumes: `verify_links.py` — errors if an `accepted` Gherkin behavior still carries `TODO(scaffold)` in its scenario block (scoped per-scenario).
- Produces: BEH-003 `state: accepted`; deterministic `verify` green.

- [ ] **Step 1: Flip BEH-003 to accepted**

In `knowledge-base/specs/auth/SPEC-001-passkey-login.md` frontmatter, change BEH-003's `state: proposed` → `state: accepted`. In the `## Behavior` table, change the BEH-003 row's State cell `proposed` → `accepted`. Leave BEH-001/002 as `proposed`.

- [ ] **Step 2: Run deterministic verify (expect OK)**

Run:
```bash
python "/Users/main/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/spec-manager/scripts/verify_links.py" --dir /Users/main/Documents/projects/viva-croatia-testbed/knowledge-base/specs --format text
```
Expected: `OK — all behavior links pass Tier-1 integrity checks.` (exit 0). BEH-003 is accepted AND its scenario has real steps (no `TODO(scaffold)`), so the `accepted-but-scaffold` gate does not fire; BEH-001/002 remain proposed scaffolds (allowed).

- [ ] **Step 3: Confirm the test still passes**

Run: `pnpm test:bdd`
Expected: `@BEH-003` passes.

- [ ] **Step 4: Commit (artifacts: the accepted test joins code; the spec is an artifact)**

```bash
git add knowledge-base/specs/auth/SPEC-001-passkey-login.md
git -c user.name="Alex" -c user.email="claude.stifle198@simplelogin.com" commit -m "spec(SPEC-001): accept BEH-003 (real cucumber test in place)"
```

---

## Self-Review

**Spec coverage (§7 of `02-phase-2.md` — "close the loop"):** Task 1 stands up cucumber-js (HTTP-layer, no browser ✓); Task 2 makes a **guard** behavior real (BEH-003, not the happy-path BEH-001 ✓) driving the route in-process ✓; Task 3 marks it `accepted` and confirms `verify` ✓. The observed-coverage *capture* itself is Plan 2 (correctly out of scope here — it needs this running test first).

**Placeholder scan:** No TBD/TODO in steps. The `TODO(scaffold)` references are the literal marker string for BEH-001/002, intentionally left.

**Type/name consistency:** Step phrases in the `.feature` (Step 2.1) exactly match the `Given/When/Then` patterns in `passkey_auth_steps.ts` (Step 2.3), including `{string}`/`{int}` params. The locator slug `unknown-email-does-not-reveal-whether-a-user-exists` matches SPEC-001's BEH-003 `locator` (unchanged).

**Known iteration point (honest):** Task 2 Step 4 may need env/DB-wiring adjustment on first run (Prisma `DATABASE_URL`, generated client). This is harness wiring, not production logic — hence the "fix env and re-run" instruction rather than a guess presented as fact.

## Execution outcome (2026-06-29) — deviation recorded

Executed inline. Task 1 landed as written (with two necessary wiring fixes:
tsx via `NODE_OPTIONS="--import tsx/esm"` not the deprecated `loader:`, and `.mts`
step files to avoid Node 24's `require(esm)` cycle). **Tasks 2–3 deviated:** the
planned *in-process route-handler import* proved non-viable on a CommonJS-default
project (Node `require(esm)` across `next/server`'s cycle — see dogfooding-notes
**F10**). Replaced with the framework-agnostic correct design: a `BeforeAll`/`AfterAll`
**app-under-test harness** boots `next dev` once and step defs drive the route over
**real HTTP**. BEH-003 is real, passing, and `accepted`; `verify` green. This
reshapes Phase 2 coverage capture (instrument the app process, not the test process)
— fold into Plan 2 before writing it.

## Next plan

After this lands (BEH-003 accepted, cucumber green), **Plan 2** specifies the behavior-graph capability — `behavior.json`, the behavior-run capability capturing **observed** coverage from this exact cucumber setup (V8/c8 output now observable), Direction A/B, incremental execution + freshness caching, measurement, and the F5/F3 fixes — written against the real coverage output rather than a guess.

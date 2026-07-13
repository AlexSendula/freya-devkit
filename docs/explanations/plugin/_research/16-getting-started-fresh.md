# Getting Started — Fresh (Greenfield)

**Research brief for the freya-devkit plugin explainer.**
Topic: the end-to-end story of starting a *new* (greenfield) project with the
toolkit — install → first code-graph bootstrap → docs-manager create →
spec-manager greenfield bootstrap + author-forward specs/behaviors → first
wrap-up.

Sources read (all paths repo-relative to `freya-devkit/`):
- `README.md`
- `docs/conventions.md`
- `skills/spec-manager/SKILL.md`
- `skills/code-graph/SKILL.md`
- `skills/docs-manager/SKILL.md`
- `skills/wrap-up/SKILL.md`
- `skills/behavior-graph/SKILL.md`
- `skills/spec-manager/scripts/project_shape.py`
- `skills/spec-manager/references/spec-template.md`
- `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md`

> **Path convention in this brief:** script invocations are shown with the
> `${CLAUDE_PLUGIN_ROOT}` prefix (the plugin's install root). Some SKILL.md steps
> hardcode an absolute per-machine cache path instead; that is an inconsistency in
> the source, noted under Gotchas. The `${CLAUDE_PLUGIN_ROOT}` form is the portable one.

---

## What this is

The "fresh start" is the greenfield onboarding path of freya-devkit: bringing the
seven-skill toolkit up on a brand-new project that has little or no real code yet.
The defining property of greenfield is **intent-first / BDD**: because there is no
existing code to infer intent *from*, the toolkit **does not** run inference. It
sets up the knowledge-base structure and empty graphs, then you **author behaviors
forward** with `spec-manager create` as you build, and keep everything in sync with
`wrap-up`.

This contrasts with the brownfield path (a substantial existing codebase), which
runs a `scan` to infer a large pile of `proposed` candidate behaviors. Greenfield
deliberately skips that step — inference on a bare scaffold would only produce
low-certainty noise.

> "**Greenfield / scaffold-only** (little or no code): **skip inference** — set up
> structure + empty graphs and message clearly ('greenfield — author behaviors
> forward as you build'). This is the *easier* path (intent-first/BDD), not an
> error." — `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` §4

---

## Why it exists

The behavior layer's central design problem is **adoption** (design doc §1–2): how
does intent get captured without either (a) the AI fabricating authoritative intent
it cannot actually know, or (b) drowning the engineer in a hundreds-of-specs review
queue on day one. The answer is to **decouple inference from validation**.

On a greenfield project there is nothing to infer, so the flood problem does not
exist — you simply author intent as first-class behaviors *before or alongside* the
code that satisfies them (BDD). Every behavior a human authors is trusted; there is
no `proposed` review backlog to drain because you never inferred one.

> "`certainty` here is the **prioritizer** of the proposed pile … not a trust
> signal — trust is the lifecycle `state`." — design doc §4

---

## The command sequence (greenfield, end to end)

### 0. Install the plugin

```text
/plugin marketplace add AlexSendula/freya-devkit
/plugin install freya-devkit@freya-devkit
```

Skills are then invoked namespaced: **`/freya-devkit:<skill>`** (`README.md`).
(For local development the README points to `CONTRIBUTING.md`.)

### 1. Bootstrap: `/freya-devkit:spec-manager bootstrap`

`bootstrap` is the unified "bring the plugin up on this project" flow. It replaces
running `init` / `code-graph build` / `scan` by hand and is **one-time** — day-to-day
syncing is `update`, and new code acquires intent lazily via wrap-up.

Its flow (`skills/spec-manager/SKILL.md`, "bootstrap" section):

1. **Init structure.** Runs the `init` flow — creates the `knowledge-base/` layout
   and `principles.md`. Idempotent; never clobbers existing files.
2. **Build the code graph.** Runs `/freya-devkit:code-graph build` — the shape
   detector needs it, and it is cheap and useful regardless of shape.
3. **Detect shape and recommend.** Runs:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py" --project . --format text
   ```
   Shows the engineer the recommendation **and its evidence** (source-file count,
   internal-edge count, detected stack), then asks them to **confirm the branch or
   override**. The detector never forces a branch.
4. **Branch → Greenfield:** skip `scan`. Build an (essentially empty) behavior graph
   so the machinery is initialized:
   `/freya-devkit:behavior-graph --build --project .` (with no `accepted`/`confirmed`
   behaviors this yields an empty `behavior.json`, which is correct). Prints:
   *"Greenfield project — no inference run. Author behaviors forward as you build
   with `spec-manager create`."*
5. **Summary.** Reports the knowledge-base layout created and the graph built.

**How the greenfield/brownfield decision is actually made** (`project_shape.py`):
The classifier is objective and transparent. It counts **internal import edges** in
the code graph — imports that code-graph resolved to a real project file (NOT tagged
`external:` or `unresolved:`). Raw file count is deliberately *not* the signal,
because a bare scaffold can have many boilerplate files yet zero real wiring.

| Condition | `recommendation` | `reason` (verbatim shape) |
|---|---|---|
| no `graph.json` present | `unknown` | "no code-graph at knowledge-base/.graph/graph.json — run code-graph build first" |
| graph present, `internal_edges == 0` | `greenfield` | "N source file(s) but 0 internal import edges — no real feature wiring yet" |
| graph present, `internal_edges > 0` | `brownfield` | "N source file(s) with M internal import edge(s) — existing codebase" |

`project_shape.py` shells out to `docs-manager/scripts/detect_project.py` for the
stack summary (runtime, package manager, frontend/backend framework, db/orm, test
runners), degrading to an empty dict on any failure. It is stdlib-only. Flags:
`--project <dir>` (required), `--format json|text` (default `json`).

> **Design-doc framing of the branch:** "Detection uses `detect_project.py` +
> code-graph file counts." — design doc §4. (Note: the *shipped* detector keys on
> **internal import edges**, not raw file counts — the file-count phrasing in the
> design doc is looser than the implementation.)

#### What `init` (inside bootstrap) creates

From `spec-manager init` (`skills/spec-manager/SKILL.md`):
1. `/knowledge-base/specs/` (if absent).
2. Category subdirs: `auth/`, `api/`, `data/`, `features/`, `infra/`,
   `integration/`, `ui/` — each with an empty `.gitkeep` so the empty dir survives Git.
3. `README.md` with the index template + search instructions.
4. `/knowledge-base/principles.md` from `references/principles-template.md` (the
   project constitution) if absent.
5. `/knowledge-base/decisions/` from `references/decisions-readme.md` (home for
   cross-cutting ADRs); scaffolds its `README.md` index via:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adr.py" list --project .
   ```
6. Reports what was created.
7. `/knowledge-base/intents/` (home for `INTENT-NNN` declared-intent records; starts
   empty with a `.gitkeep`).

#### The code-graph build (step 2, greenfield-relevant behavior)

`/freya-devkit:code-graph build` classifies directories (rules → AI → user
confirmation), detects the project root, scans source, parses imports/exports, and
stores the graph in `knowledge-base/.graph/` (`graph.json` +
`classifications.json`). When invoked non-interactively (auto-enabled when stdin is
not a TTY, e.g. by wrap-up), uncertain directories default to **source** so real
code is never silently dropped. On a bare greenfield scaffold this build is nearly
empty — which is exactly what yields the `internal_edges == 0` → greenfield signal.

### 2. Documentation: `/freya-devkit:docs-manager init`

`docs-manager init` creates the initial documentation structure for a new project,
then reviews it (`skills/docs-manager/SKILL.md`). Architecture is **coordinator +
parallel workers**:
- **Phase 1 (coordinator):** project detection (runtime/framework/db/infra),
  business-context collection (asks the user: what is this project, who are the
  users, any domain rules), existing-docs scan, plan generation.
- **Phase 2 (parallel workers):** one worker per doc type — `PROJECT_OVERVIEW.md`,
  `ARCHITECTURE.md`, `DATABASE.md` (if a db is present), `API.md` (if an API is
  present), `ENVIRONMENT.md`, `DEPLOYMENT.md`, `DEVELOPER.md`, `TESTING.md`,
  `STYLE_GUIDE.md`, `INFRASTRUCTURE.md`, `SECURITY.md`, `TROUBLESHOOTING.md`.
- **Phase 3:** build `knowledge-base/README.md` index.
- **Phase 4:** placeholder resolution — scans for `[TODO:` markers, groups them by
  topic (business/infra/deployment/contacts/services), asks **one batched question
  per group**.
- **Phase 5:** review (consistency, completeness, accuracy, links, currency) →
  report with ✅ / ⚠️ / ❌.

Output layout: `knowledge-base/README.md` (index at root) + `knowledge-base/reference/*.md`
(all other docs). docs-manager **owns** `README.md` and `reference/`; the other
`knowledge-base/` siblings belong to other skills.

> Greenfield caveat: on a near-empty project many workers have little to document
> and will emit `[TODO:` placeholders for you to resolve interactively. This is
> normal — the docs skeleton is scaffolded early and filled in as the project grows.
> `docs-manager` best-practice #1 is "Run `init` early — create docs when project
> structure is stable."

### 3. Author intent forward: `/freya-devkit:spec-manager create <name>`

This is the heart of the greenfield workflow. Because bootstrap ran no inference,
you author each feature's intent as you build it. `create` (`skills/spec-manager/SKILL.md`):

1. **Surface the constitution first** (soft injection — draft against the rules):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
   ```
   (Empty output ⇒ no constitution yet.)
2. Ask clarifying questions: what feature, what it should do, why it is needed, any
   intentional design decisions, category + tags.
3. Generate the spec ID (next sequential `SPEC-NNN`).
4. Create the spec file from `references/spec-template.md`. **If the feature has
   observable behavior, add `behaviors:` records; leave the list empty for a purely
   declarative spec. New behaviors normally start as `proposed`.**
5. Set `certainty` to **100** (user-created).
6. Update the README index.
7. **Contradiction check (governance G3)** — a freshly authored spec must not
   contradict a principle or a same-category peer's decision.

**Author-forward behaviors — the spec/behavior model** (`spec-template.md`,
spec-manager SKILL.md "Spec File Format" + "Adapters"):

- A spec owns a `behaviors:` list of first-class `Behavior` records. Each carries a
  stable `BEH-NNN` id (allocated as the next sequential number across all behaviors;
  **stable across renames**), a lifecycle `state`, a test `level`
  (`unit|component|integration|e2e`), an `adapter`, and a `locator`.
- **Lifecycle states:** `proposed | confirmed | accepted | quarantined | deprecated`.
  For greenfield authoring the meaningful transitions are:
  - `proposed` → drafted intent, not confirmed, no test, not in blast radius, does
    not gate.
  - `confirmed` → a human confirmed the intent is correct; **test owed**; advisory
    (does not gate); gets a static fingerprint if an `entry` is declared.
  - `accepted` → confirmed **and** a real passing linked test exists; authoritative;
    **blocks wrap-up on failure**.
- **Two adapters (Phase 1):**
  - **Gherkin** (`cucumber` / `behave` / `pytest-bdd`) — the default for *new*
    behavior. When an `accepted` behavior needs a new test, spec-manager writes a
    **skeleton `.feature`** (never real scenarios — authoring real steps is human
    forward-design work) via:
    ```bash
    python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adapters.py" gherkin-scaffold \
      --spec-id SPEC-012 --title "Passkey Login" \
      --spec-path knowledge-base/specs/auth/SPEC-012-passkey-login.md \
      --behavior "BEH-007:Successful passkey login"
    ```
    This emits `features/<category>/<name>.feature` in the **code tree** with a
    required `@SPEC-NNN` tag on `Feature` and `@BEH-NNN` on each `Scenario` (the
    reverse links), a `TODO(scaffold)` marker, and placeholder `Given/When/Then`.
    Step definitions are **not** generated. The behavior's `locator` becomes
    `features/<category>/<name>.feature#<scenario-slug>`.
  - **Native** (`jest`, `playwright`, `pytest`, …) — when a behavior is already
    covered by a real test, **link it by `locator`** (`path/to/test#case`, or
    `path::node` for pytest); no `.feature` is written.
- A spec with no testable behavior leaves `behaviors:` empty → a **purely
  declarative spec**. `related_code` is still expected on declarative specs (it is
  the key the declarative-drift check uses).

**Where intent is enforced (context for greenfield authors):**
- `principles.md` is the project **constitution** — the highest-authority intent
  record. spec-manager owns `principles.md`, `specs/`, and `decisions/`.
- Authority order for contradiction checks (G3): **principle > ADR > spec**.
- `Intentional Design Decisions` sections in a spec are the **false-positive filter**
  the security scan reads — e.g. "No Password Fallback" tells a scanner to ignore a
  "missing password authentication" flag.

### 4. First wrap-up: `/freya-devkit:wrap-up`

After implementing a feature, run `/freya-devkit:wrap-up` (optionally with a commit
message). It orchestrates the post-implementation pipeline with a **two-commit
pattern** (`skills/wrap-up/SKILL.md`):

- **Commit 1 — Code:** stage + commit code files only.
- Then artifact generation, in order:
  1. `/freya-devkit:code-graph update`
  2. `/freya-devkit:docs-manager update`
  3. `/freya-devkit:spec-manager update`
  3.5. Behavior integrity & accepted-behavior run + governance gates (see below)
  4. `/freya-devkit:codebase-security-scan update`
- **Commit 2 — Artifacts:** docs, specs, security report, dependency graph, tracking
  files, `proposed`/unaccepted behavior scaffolds, `BACKLOG.md`, ADRs, resolution logs.

**Never-synced guard (F5) — the greenfield gotcha that matters most.** The wrap-up
`update` commands are incremental and assume a prior sync. If a project has **never
been synced** (no `.spec-last-update`, no `.graph/`, no `.security-last-scan`),
wrap-up must **not** let `update` silently run a full-codebase generation. Instead it
reports the project is unsynced and either runs the explicit first-time command
(`scan` / `build`) deliberately or skips that phase with a clear message.
**Practical consequence:** running `spec-manager bootstrap` first (which builds the
graph and initializes structure) is what makes the first `wrap-up` behave correctly.

**Phase 3.5 governance stack** (deterministic hard-blocks first, then procedural
resolve-to-proceed gates):
1. Deterministic link integrity (`verify_links.py`) + ADR integrity (`adr.py verify`)
   — **hard-block**.
2. Declared-intent gate (`verify_intent.py`, governance G1) — **hard-block** if an
   `accepted` behavior's test was modified/deleted without a new `INTENT-NNN` record.
   (With no `.intent-last-verified` baseline the gate skips — true on a fresh project.)
3. Build/refresh behavior graph, then run **affected accepted** behaviors
   (Direction-A regression check) — **hard-block** on a `test-failed`. On greenfield
   with no `accepted` behaviors yet, this is effectively a no-op.
4. **Validate-on-hit (advisory, never blocks)** via
   `behavior_graph.py --surface --base "$BASE"`: surfaces the `proposed`/`confirmed`
   behaviors the change touched (`validate_candidates`) and touched code no behavior
   covers (`recall_gaps`) — each skippable.
5. **Principle checkpoint (G2)** — model judgment; wrap-up must not complete while a
   finding is unresolved. Skipped if `principles.md` is empty.
6. **Contradiction check (G3)** — over changed `specs/**` and `decisions/**`.
7. **Declarative-drift check (P4b)** — code vs declared intent, blast-radius-scoped.

**Skipping steps:** `--no-security`, `--no-docs`, `--no-specs`, `--no-graph` (combinable).

**BACKLOG.md.** wrap-up Phase 5 regenerates the git-tracked
`knowledge-base/BACKLOG.md` via:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" --project . --write-backlog
```
It lists behaviors-to-confirm, tests-owed, and open security findings. On greenfield
it starts near-empty and grows as you author behaviors.

---

## How it composes with other skills

- **code-graph is the keystone.** docs-manager, spec-manager, and the security scan
  all query it for blast radius and **degrade gracefully to plain `git diff`** when
  it is unavailable. On greenfield the graph is nearly empty at first, so blast-radius
  analysis has little to chew on until real code + imports exist.
- **behavior-graph** owns `behavior.json` (a generated projection at
  `knowledge-base/.graph/behavior.json`). It projects only `accepted`/`confirmed`
  behaviors, so on a fresh greenfield project it stays ≈empty until you author and
  accept behaviors. Directions: A (`--affected <files>` → which behaviors a change
  touches) and B (`--implements <BEH-NNN>` → which code a behavior exercises). Query
  results reflect the last `--build`.
- **specs are the security scan's false-positive filter** — the scan reads
  `knowledge-base/specs/` and marks spec'd behavior as *intentional design* rather
  than a vulnerability. An `accepted`, test-backed behavior is the *strongest*
  intentional evidence (a verified guarantee, design doc §7).
- **wrap-up orchestrates** code-graph → docs → specs → behavior → security with the
  two-commit pattern.

---

## Inputs / outputs / artifacts

**Artifact tree** (`docs/conventions.md`, spec-manager SKILL.md):
```
knowledge-base/
├── README.md                  ← docs index (docs-manager)
├── principles.md              ← project constitution (spec-manager)
├── reference/                 ← descriptive docs (docs-manager)
├── specs/                     ← per-feature specs + behaviors (spec-manager)
│   ├── README.md
│   ├── auth/ api/ data/ features/ infra/ integration/ ui/   (each with .gitkeep)
│   └── .spec-last-update      ← incremental tracking file
├── decisions/                 ← cross-cutting ADRs (spec-manager)
├── intents/                   ← INTENT-NNN records + .intent-last-verified
├── security/                  ← security findings (codebase-security-scan)
│   └── <scanner-name>/YYYY-MM-DD.md
├── BACKLOG.md                 ← generated, git-tracked (status / wrap-up)
└── .graph/                    ← graph.json, classifications.json, behavior.json (code-graph / behavior-graph)
```

- Behavior `.feature` scaffolds are written into the **code tree** at
  `features/<category>/<name>.feature` — NOT into `knowledge-base/`.
- `.graph/` may be git-ignored ("Add `knowledge-base/.graph/` to `.gitignore` if you
  don't want to commit the generated graph." — code-graph SKILL.md).

**Tracking files** (incremental-update convention, `docs/conventions.md`): each
skill records the last processed commit in a dotfile (e.g.
`knowledge-base/specs/.spec-last-update` with `commit`, `timestamp`, counts).

---

## Degradation behavior

- **code-graph absent** → docs/spec/security skills fall back to plain `git diff`
  (directly changed files only, no transitive dependents). "reduced coverage but
  remains functional" (`docs/conventions.md`).
- **project_shape unknown** (no graph, or unreadable `graph.json`) → bootstrap "asks
  outright with no recommendation." `detect_project.py` failure → empty stack dict,
  classification still proceeds on edge count.
- **Non-interactive code-graph build** → uncertain dirs default to **source** (never
  silently dropped).
- **Never-synced wrap-up** → refuses to silently full-generate; reports unsynced and
  runs the explicit first-time command or skips with a message (F5 guard).
- **behavior-graph `--surface` with no graph / no changes** → returns a `note`;
  wrap-up prints it and continues.
- Governance gates (G2/G3/P4b) are **fail-open** on no git / no diff / no principles /
  tooling error — note and continue.

---

## Honest limits

- **code-graph language support:** TypeScript/JS, Python, Go only. May miss dynamic
  `import()` / `require(variable)`. Tracks only local file relationships (not
  npm/pip packages). Monorepos: each subproject needs its own graph.
- **No test generation.** The toolkit scaffolds skeleton `.feature` files and links
  existing tests, but **never writes real test steps or step definitions** — that is
  human forward-design work. Fully automated `confirmed → accepted` test generation
  is explicitly out of scope (design doc §10).
- **spec-manager `verify` is deterministic-only in Phase 1.** Model-based
  contradiction checking against principles/decisions is Tier-2 / Phase 3 and not
  part of the `verify` command.

---

## Quotable lines (verbatim, tagged with source)

- "**Greenfield →** skip `scan`. … Print: *'Greenfield project — no inference run.
  Author behaviors forward as you build with `spec-manager create`.'*"
  — `skills/spec-manager/SKILL.md`
- "It is **one-time**: for day-to-day syncing use `update`, and after the first run
  newly-written code acquires intent lazily via wrap-up's 'touched code with no
  covering behavior' prompt." — `skills/spec-manager/SKILL.md` (bootstrap)
- "Inference is cheap and can be done up front; **validation is the scarce resource**
  and must be spent lazily, in the flow of work." — design doc §2
- "This is the *easier* path (intent-first/BDD), not an error."
  — design doc §4
- "trust is the lifecycle `state`." — design doc §4
- "`scan` produces a **review queue of `proposed` candidates** — never `accepted`,
  and **never files written into the code tree.**" — `skills/spec-manager/SKILL.md`
  (greenfield skips this entirely)
- "When an `accepted` behavior needs a new test, spec-manager writes a **skeleton
  `.feature`** — never real scenarios (authoring real steps is forward-design work
  for a human)." — `skills/spec-manager/SKILL.md`
- "Two-commit pattern — code changes land in one commit; generated artifacts (graph,
  docs, specs, security reports) in a second." — `README.md`

---

## Gotchas / UNVERIFIED

- **UNVERIFIED — exact `bootstrap` greenfield console string.** The SKILL.md quotes
  the greenfield message; I did not confirm a script actually prints it verbatim
  (bootstrap is an agent-driven flow described in prose, not a single script).
- **Path inconsistency in source (verified).** Most script calls use
  `${CLAUDE_PLUGIN_ROOT}/skills/...`, but several SKILL.md steps (e.g. `verify_intent.py`,
  `adr.py` in `init` step 5, `intent.py`) hardcode an absolute per-machine cache path
  of the form `/…/plugins/cache/freya-devkit/freya-devkit/0.1.0/skills/...`. These are
  equivalent at install time but the absolute form is non-portable. Sanitized here to
  `${CLAUDE_PLUGIN_ROOT}`; the absolute machine path is intentionally not reproduced.
- **`bootstrap`, `status`, `behavior-graph` invocation styles differ.** spec-manager
  is invoked as `/freya-devkit:spec-manager bootstrap`; behavior-graph is invoked via
  its Python script `behavior_graph.py --build --project .` (the SKILL.md also writes
  `/freya-devkit:behavior-graph --build --project .` as a skill-style call). Treat the
  Python script path as the authoritative CLI.
- **Greenfield → brownfield transition is not a discrete command.** There is no
  "re-bootstrap." As the project grows, new code acquires intent lazily through
  wrap-up's validate-on-hit + recall-gap prompts (design doc §5); a full inference
  `scan` is a brownfield-only, one-time action.
- **`project_shape.py` recommendation is advisory, not enforced** — a human confirms
  or overrides; an unusually-structured repo can be branched manually.
- **`level` field required in behavior records** per `spec-template.md`, but the
  `behaviors:` example in the spec-manager SKILL.md "Spec File Format" omits `level`.
  Minor doc drift; `frontmatter.validate_behaviors` rejects an unknown `level`.
- **Design-doc vs implementation drift:** design §4 says detection uses "code-graph
  file counts"; the shipped `project_shape.py` keys on **internal import edges**, not
  file counts. The implementation is the source of truth.

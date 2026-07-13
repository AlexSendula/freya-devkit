# Getting Started — Existing (Brownfield) Adoption

**Research brief for the freya-devkit plugin-wide explainer.**
Topic: adopting the toolkit on an EXISTING codebase — install, code-graph full
scan, docs-manager create-from-existing, spec-manager scan (reverse-engineer
specs), security baseline, behavior-layer brownfield bootstrap (internal-edge
detector), then incremental day-to-day.

Sources read (all paths relative to repo root
`/Users/main/Documents/projects/freya-devkit`):
- `docs/conventions.md`
- `docs/migrations/knowledge-base.md`
- `skills/spec-manager/SKILL.md`
- `skills/code-graph/SKILL.md`
- `skills/codebase-security-scan/SKILL.md`
- `skills/status/SKILL.md`
- `skills/docs-manager/SKILL.md`
- `skills/spec-manager/scripts/project_shape.py` (the internal-edge shape detector)
- `skills/wrap-up/SKILL.md` (composition of the incremental pipeline)

---

## 1. What this is

"Brownfield adoption" is the one-time flow that brings the freya-devkit plugin up
on a codebase that **already exists** (has real code, history, maybe tests) — as
opposed to greenfield, where you author intent forward as you build. The end state
is a populated `knowledge-base/` root containing a dependency graph, descriptive
docs, reverse-engineered specs + a queue of candidate behaviors, a security
baseline report, and an initialized (initially near-empty) behavior graph. After
that first pass, the project switches to **incremental** upkeep driven by
`/freya-devkit:wrap-up` and checked by `/freya-devkit:status`.

The single most important brownfield-specific piece is the **shape detector**
(`project_shape.py`), which uses the code-graph's **internal import-edge count** —
not raw file count — to recommend the brownfield vs greenfield branch. That is the
"internal-edge detector" named in the task.

## 2. Why it exists

Two problems it solves:

1. **A new codebase has intent that was never written down.** The specs, the
   "why is this code like this", the intentional design decisions that look like
   bugs — all live only in people's heads or git history. Brownfield `scan`
   reverse-engineers *candidate* records so the security scan, future agents, and
   new developers stop re-litigating settled decisions.
2. **You must not fabricate authoritative intent from code.** The plugin's core
   thesis (the "behavior layer") is that tests/behaviors must not merely mirror
   the implementation. So brownfield inference produces a **review queue of
   `proposed` candidates**, never `accepted` guarantees and never files written
   into the code tree. Intent becomes authoritative only when a human confirms it.

> "`scan` produces a **review queue of `proposed` candidates** — never `accepted`,
> and **never files written into the code tree.** Intent cannot be reliably
> inferred from code; auto-generating authoritative-looking scaffolds from the
> implementation would reintroduce the 'tests mirror code' problem the behavior
> layer exists to fix." — `skills/spec-manager/SKILL.md`

## 3. The knowledge-base layout (the shared output root)

All skills read/write under a single `knowledge-base/` root (migrated from the old
scattered `docs/` layout — see `docs/migrations/knowledge-base.md`). Ownership:

```
knowledge-base/
├── README.md          ← docs index (docs-manager)
├── principles.md      ← project constitution (spec-manager)
├── reference/         ← descriptive architecture/API/schema docs (docs-manager)
├── specs/             ← per-feature intent + behavior records (spec-manager)
├── decisions/         ← cross-cutting ADRs (spec-manager)
├── intents/           ← INTENT-NNN declared-intent records (spec-manager)
├── security/          ← security findings + findings.json (codebase-security-scan)
│   └── codebase-security/YYYY-MM-DD.md
├── BACKLOG.md         ← generated outstanding-work view (status / wrap-up)
└── .graph/            ← dependency + behavior graph data (code-graph)
    ├── graph.json
    └── classifications.json
```

(Sources: `docs/conventions.md` "Artifact Location Convention"; `skills/spec-manager/SKILL.md`
"Knowledge-Base Layout"; `skills/code-graph/SKILL.md` "Graph Storage"; `skills/status/SKILL.md`.)

**Note on `.graph/`:** `code-graph`'s SKILL says the graph is version-controlled
alongside code by default, with a note to add `knowledge-base/.graph/` to
`.gitignore` if you don't want to commit it. The migration doc calls the graph "a
regenerable cache … keyed to a commit" and says rebuilding is cheaper than moving
it. (Slight tension between the two docs; flagged in gotchas.)

## 4. Install

Per the user's global CLAUDE.md, install the plugin via the Claude Code plugin
system, then invoke skills **namespaced** as `/freya-devkit:<skill>`:

```
/plugin marketplace add   (add the freya-devkit marketplace)
/plugin install freya-devkit@freya-devkit
```

Scripts are then reachable via `${CLAUDE_PLUGIN_ROOT}` (e.g.
`${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py`). A plugin
code change requires a **session restart** to reload (per the project's memory
index). Skills are invoked by their slash commands; the Python scripts they call
are stdlib-only where noted (e.g. `project_shape.py` header: "Stdlib-only.").

---

## 5. The recommended brownfield sequence

There are two ways to run this: the **one-shot `bootstrap`** (recommended — it
orchestrates the steps below for you) or **step-by-step** (run each skill by
hand). Both produce the same end state.

### 5.0 One-shot: `/freya-devkit:spec-manager bootstrap`

`bootstrap` is the unified "bring the plugin up on this project" flow. It is
**one-time** and idempotent. Its flow (verbatim structure from
`skills/spec-manager/SKILL.md`):

1. **Init structure** — runs the `init` flow (knowledge-base layout + `principles.md`);
   never clobbers existing files.
2. **Build the code graph** — runs `/freya-devkit:code-graph build` (the shape
   detector needs it).
3. **Detect shape and recommend** — runs:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/project_shape.py" --project . --format text
   ```
   Shows the engineer the recommendation **and its evidence** (source-file count,
   internal-edge count, detected stack), then asks them to **confirm the branch or
   override**. On `unknown` (no graph / unreadable) it asks outright.
4. **Branch:**
   - **Brownfield →** run the `scan` flow to infer candidate behaviors at the
     **per-observable-behavior grain** (one `proposed` behavior per observable
     behavior/scenario). All candidates are `proposed` records written into
     `knowledge-base/specs/` — **never** `.feature` scaffolds in the code tree.
     On a partially-onboarded repo this is **additive** (infer only for areas with
     no existing spec). Then run `/freya-devkit:behavior-graph --build --project .`.
     **Warns first** that scan over a large repo spawns discovery agents and can
     take a while.
   - **Greenfield →** skip `scan`; build an essentially-empty behavior graph.
5. **Summary** — reports the layout created, the graph built, and (brownfield) a
   count of `proposed` candidates by category, with the reminder that **nothing
   needs review now** (the queue is drained lazily).

> "The unified 'bring the plugin up on this project' flow — it replaces running
> `init` / `code-graph build` / `scan` by hand. It is **one-time**." — `skills/spec-manager/SKILL.md`

### The shape detector (internal-edge detector) — how it decides

`project_shape.py` returns `{recommendation, evidence, reason}`. It counts, from
`knowledge-base/.graph/graph.json`, **internal import edges** — imports that
code-graph resolved to a project file (i.e. NOT tagged `external:` or
`unresolved:`). Verbatim thresholds from the script:

- **No graph present** → `recommendation: "unknown"`, reason
  `"no code-graph at knowledge-base/.graph/graph.json — run code-graph build first"`.
- **`internal_edges == 0`** → `recommendation: "greenfield"`, reason
  `"{n} source file(s) but 0 internal import edges — no real feature wiring yet"`.
- **`internal_edges > 0`** → `recommendation: "brownfield"`, reason
  `"{n} source file(s) with {m} internal import edge(s) — existing codebase"`.

Rationale from the script's own docstring:

> "An internal edge is an import code-graph resolved to a project file — i.e. NOT
> tagged `external:` or `unresolved:`. Internal edges (real wiring) are the
> brownfield signal; raw file count is not (a bare scaffold can have many
> boilerplate files yet zero internal wiring)." — `project_shape.py`

Flags: `--project <dir>` (required), `--format json|text` (default `json`). The
`text` format prints recommendation, reason, source files, internal edges, graph
present, and a `stack:` line (runtime/pkg/frontend/backend/db/orm/test) sourced
from `docs-manager/scripts/detect_project.py`. **The detector never forces a
branch** — a human confirms/overrides on sight.

---

### 5.1 Step-by-step (equivalent to bootstrap, done by hand)

If not using `bootstrap`, the manual brownfield order is:

**Step 1 — Build the code graph (foundation).**
```
/freya-devkit:code-graph build
```
Full scan: classifies directories (rules → AI → user confirmation; `<80%`
confidence prompts), detects project root, parses imports/exports for
TS/JS, Python, Go (`**/*.ts`, `**/*.tsx`, `**/*.js`, `**/*.jsx`, `**/*.py`,
`**/*.go`), builds the reverse dependents map, and stores
`knowledge-base/.graph/graph.json` + `classifications.json`. Excludes
`node_modules`, `dist`, `build`, `.next`, `venv`, `.git`, etc., plus `.gitignore`
patterns and anything classified "exclude".

> Non-interactive note (matters for automation/wrap-up): "`--non-interactive`, and
> auto-enabled when stdin is not a TTY … never prompts; uncertain directories
> default to **source** so real code is never silently dropped." — `code-graph/SKILL.md`

Underlying script call:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --build --dir /path/to/project
```
Import edges are tagged internal / `external:<pkg>` / `unresolved:<import>` (the
last is surfaced, not dropped — this is exactly what the shape detector reads).

**Step 2 — Create docs from the existing codebase.**
```
/freya-devkit:docs-manager init
```
Coordinator + parallel workers: detects stack, asks a few business-context
questions, then spawns workers for `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`,
`DATABASE.md`, `API.md`, `ENVIRONMENT.md`, `DEPLOYMENT.md`, `DEVELOPER.md`,
`TESTING.md`, `STYLE_GUIDE.md`, `INFRASTRUCTURE.md`, `SECURITY.md`,
`TROUBLESHOOTING.md` (only the relevant ones). Output goes to
`knowledge-base/reference/*.md` with the index at `knowledge-base/README.md`.
Undetectable details become `[TODO: …]` placeholders, then Phase 4
(placeholder resolution, batched questions grouped by topic) and Phase 5 (review:
consistency/completeness/accuracy/links/currency) run automatically.

Why docs first, before specs/security: the security scan and spec scan both read
`knowledge-base/reference/` for architecture/auth/data-flow context. Docs raise
the accuracy of everything downstream. (`codebase-security-scan/SKILL.md` Step 1;
`spec-manager` certainty is raised by "matching docs in `/knowledge-base/reference/`".)

**Step 3 — Reverse-engineer specs.**
```
/freya-devkit:spec-manager init      # if not already done by bootstrap
/freya-devkit:spec-manager scan
```
`init` scaffolds `specs/` (category subdirs `auth/ api/ data/ features/ infra/
integration/ ui/`, each with `.gitkeep`), `README.md`, `principles.md` (from
`references/principles-template.md`), `decisions/`, and `intents/`.

`scan` ("**the big one**") is a coordinator + parallel discovery-agent flow:
- **Phase 1:** load the constitution (`principles.py list`), coordinator globs the
  codebase and identifies feature areas (auth / api / ui / data / infra).
- **Phase 2:** parallel area agents infer per-feature What/Why + a **certainty
  score (0–100)**, flag potential intentional decisions, and mark
  `[NEEDS CLARIFICATION]`.
- **Phase 2.5:** intent classification into a review queue — observable behavior →
  a `proposed` Behavior (recommend a Gherkin scaffold or link an existing native
  test); non-observable → declarative (Intentional Design Decision inline, or note
  for `decisions/` ADR).
- **Phase 3:** certainty evaluation (cross-ref `reference/` docs, comments, tests).
- **Phase 4:** interactive clarification — for specs `<70%` certainty, ask
  questions one at a time.
- **Phase 5:** update `knowledge-base/specs/README.md`.

Certainty bands: 90–100 auto-accept, 70–89 brief review, 50–69 confirm, 0–49
detailed review. Specs get `BEH-NNN` behavior records with lifecycle
`state: proposed → confirmed → accepted`. **`accepted` = confirmed intent verified
by a real linked test; `confirmed` = a human confirmed the intent, test owed.**

**Step 4 — Build the behavior graph.**
```
/freya-devkit:behavior-graph --build --project .
```
Projects `accepted`/`confirmed` behaviors into `behavior.json`. **On a fresh
brownfield scan this is expected to be ≈empty**, because scan only produces
`proposed` records — nothing is `accepted` yet. That is correct, not a failure.

> "The 'full proposed behavior graph' is this corpus of `proposed` records in
> `knowledge-base/specs/`, *not* `behavior.json` (which projects only
> `accepted`/`confirmed`, so it stays ≈empty at first run — expected)." — `spec-manager/SKILL.md`

**Step 5 — Establish the security baseline.**
```
/freya-devkit:codebase-security-scan scan
```
Full scan: reads `reference/` docs (Step 1 context) and `specs/` (intentional
design), spawns 6 parallel category agents (Auth/AuthZ; Injection; Secrets;
API/Network; Config/Deps; File/Resource), runs the validation phase (WebSearch +
spec cross-reference to kill false positives) and **Step 3.5 standard adversarial
verification** (2–3 refutation lenses per finding; unanimous refute drops a
finding). Writes `knowledge-base/security/codebase-security/YYYY-MM-DD.md` plus a
machine-readable `findings.json`, and the `.security-last-scan` tracking file.
On first run there is no prior report, so:

> "**No previous report found.** This is the first security scan. Future scans will
> compare findings against this baseline." — `codebase-security-scan/SKILL.md`

The scan cross-references `accepted` behaviors as the **strongest** "intentional"
evidence (a verified guarantee beats a prose spec); `proposed`/`confirmed`
behaviors only add an advisory note and leave the finding open — so on a fresh
brownfield project (no `accepted` behaviors yet) findings will lean on declarative
specs, not behaviors.

---

## 6. What to expect after the first pass (drain lazily, then go incremental)

**Nothing needs review immediately.** The `proposed` queue is drained lazily, two ways:

- **Validate-on-hit at wrap-up:** when you next touch code that a `proposed`
  behavior covers, wrap-up prompts you to confirm/accept it.
- **The worklists via `/freya-devkit:status`:** work the tail deliberately.

`/freya-devkit:status` (read-only) aggregates outstanding work and refreshes
`knowledge-base/BACKLOG.md`:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
  --project . --format text --write-backlog
```
It prints a census (`proposed / confirmed / accepted / quarantined / deprecated`),
the two worklist sizes, coverage gaps, Tier-1 verify failures, stale fingerprints,
and open security findings. Worklist commands:
- `status review intent` — proposed → **confirm** (one at a time, certainty-sorted).
- `status review tests` — confirmed → link/write a test → **accept**.
- `status gaps` — whole-repo uncovered-code audit via
  `behavior_graph.py --gaps --project .`.

**Day-to-day incremental** replaces `scan`/`build` with git-aware `update`s, all
orchestrated by `/freya-devkit:wrap-up` after each feature (two-commit pattern:
code commit, then artifacts commit):
1. `/freya-devkit:code-graph update` — re-parse only changed files (reads last
   commit from stored graph, `git diff <last>..HEAD --name-only`).
2. `/freya-devkit:docs-manager update` — impact-aware doc refresh.
3. `/freya-devkit:spec-manager update` — git-aware incremental spec sync (reads
   `knowledge-base/specs/.spec-last-update`; **falls back to full `scan` if the
   tracking file is missing or there's no git repo**).
3.5. Behavior integrity + run accepted behaviors (deterministic link checks
   hard-block; see `verify`).
4. `/freya-devkit:codebase-security-scan update` — incremental scan (reads
   `.security-last-scan`; **falls back to full `scan` if missing**).

Each `update` uses code-graph **impact/blast-radius** to include *dependent* files,
not just directly changed ones — that is the main reason code-graph is the
foundation tier.

Update-vs-scan guidance (verbatim spirit from `docs/conventions.md` +
`spec-manager` "Update Workflow Comparison"): use `scan`/`build`/`init` once for
first-time setup or a complete refresh; use `update` for everything after.

---

## 7. How the skills compose (dependency tiers)

```
code-graph (foundation: graph.json + classifications.json)
    ↓ impact / dependents / dependencies
docs-manager · spec-manager · behavior-graph   (consume impact for incremental)
    ↓ specs (intentional design) + reference docs
codebase-security-scan   (reads reference/ for context, specs/ + accepted behaviors to cut false positives)
    ↓
status (read-only census + BACKLOG.md) · wrap-up (orchestrates all updates + 2 commits)
```

- **spec-manager scan** uses code-graph `dependents`/`impact` to suggest
  `related_code` and find feature boundaries; **degrades to plain git diff** if
  code-graph is absent.
- **security-scan** uses code-graph for incremental scope + blast-radius priority
  (1–3 files Low, 4–10 Medium, 10+ High) and uses spec-manager specs/behaviors to
  reclassify findings as **INTENTIONAL DESIGN**.
- **docs-manager** uses code-graph impact to update only affected docs; **degrades
  to git diff** if unavailable.

## 8. Degradation behavior (honest)

- **No code-graph** → shape detector returns `unknown` and bootstrap asks outright;
  spec/docs/security `update` fall back to **directly changed files only** (reduced
  coverage; security-scan warns "code-graph not available - scanning only directly
  changed files"; `impact` returns a "code-graph not available" error).
- **No `reference/` docs** → security scan proceeds but notes reduced context;
  spec certainty is lower.
- **No `specs/`** → security scan proceeds but warns findings may include
  intentional design decisions.
- **Missing tracking file** (`.spec-last-update`, `.security-last-scan`) or no git
  repo → the corresponding `update` **falls back to a full scan**.
- **`impact_source` degrades to `changed-only`** in drift checks when code-graph is
  absent — "**never a silent empty set**"; the engineer is told.
- Every `status` source "degrades to a `note` if unavailable, and the command never
  blocks."

## 9. Honest limits / gotchas

- **code-graph is not exhaustive:** misses dynamic `import()` / `require(variable)`;
  only tracks local file relationships (not npm/pip packages); languages are
  **TS/JS, Python, Go only**; monorepos should give each subproject its own graph.
  A brownfield repo in another language (Rust, Java, Ruby, …) will produce a sparse
  or empty graph → the shape detector may see `internal_edges == 0` and **recommend
  greenfield even for a large existing codebase**. This is exactly why the detector
  is advisory and the human confirms/overrides. (UNVERIFIED as an explicit doc
  statement, but follows directly from the language list + the `internal_edges==0 →
  greenfield` threshold.)
- **`.graph/` commit policy is ambiguous across docs:** `code-graph/SKILL.md` says
  it's version-controlled by default (with an opt-out to `.gitignore`);
  `docs/migrations/knowledge-base.md` calls it "a regenerable cache … keyed to a
  commit" that need not be migrated. Treat committing it as optional.
- **Brownfield `scan` can be slow/expensive:** it spawns parallel discovery agents
  across the whole codebase; bootstrap explicitly "**Warn[s] first**." Not a
  background job — it runs interactively.
- **`scan` never writes into the code tree.** `.feature` scaffolds appear **only on
  acceptance** (via an adapter), never from inference. Reverse-engineered output is
  `proposed` records in `knowledge-base/specs/` plus declarative decisions.
- **`behavior.json` ≈empty after first brownfield run is correct**, not a bug (see §5 Step 4).
- **Partial/re-onboarding is additive:** bootstrap's brownfield branch infers only
  for areas with no existing spec — it never overwrites or re-infers existing specs,
  so re-running is safe.
- **`bootstrap` is one-time.** After it, use `update`/`wrap-up`/`status`, not
  another `bootstrap` or `scan` (except for a deliberate complete refresh).
- **`audit` is NOT part of this flow.** The exhaustive multi-agent security `audit`
  (loop-until-dry + 3-skeptic verification, Workflow-powered) is on-demand /
  pre-release only and is deliberately kept out of the wrap-up pipeline. The
  brownfield baseline uses `scan`.
- **Certainty ≠ behavior state.** `certainty` gates review of *inferred, unconfirmed*
  specs and declarative decisions; executable-behavior trust is the lifecycle
  `state` (`proposed → confirmed → accepted`). A human-confirmed spec is trusted
  regardless of the number.
- **UNVERIFIED — exact install/marketplace names:** the precise `/plugin marketplace
  add <arg>` argument is not in the read sources; taken from the user's global
  CLAUDE.md description. Confirm against the plugin's marketplace manifest before
  publishing.

## 10. Quick command reference (brownfield)

| Step | Command | Produces |
|---|---|---|
| Install | `/plugin install freya-devkit@freya-devkit` | plugin available as `/freya-devkit:*` |
| One-shot | `/freya-devkit:spec-manager bootstrap` | init + graph + shape detect + (brownfield) scan + behavior-graph |
| 1. Graph | `/freya-devkit:code-graph build` | `knowledge-base/.graph/{graph.json,classifications.json}` |
| Shape | `python .../spec-manager/scripts/project_shape.py --project . --format text` | greenfield / brownfield / unknown + evidence |
| 2. Docs | `/freya-devkit:docs-manager init` | `knowledge-base/README.md`, `reference/*.md` |
| 3. Specs | `/freya-devkit:spec-manager init` then `scan` | `knowledge-base/specs/**` (`proposed` behaviors), `principles.md`, `decisions/`, `intents/` |
| 4. Behavior graph | `/freya-devkit:behavior-graph --build --project .` | `behavior.json` (≈empty at first — expected) |
| 5. Security | `/freya-devkit:codebase-security-scan scan` | `security/codebase-security/YYYY-MM-DD.md` + `findings.json` + `.security-last-scan` |
| Status | `/freya-devkit:status` | `knowledge-base/BACKLOG.md` + census |
| Incremental | `/freya-devkit:wrap-up` | code commit + artifacts commit (all `update`s) |

---

*Sanitization note: all examples above are generic (auth/WebAuthn, `src/lib/...`).
No proprietary business content, secrets, or absolute machine paths from any real
project are reproduced. `${CLAUDE_PLUGIN_ROOT}` is the plugin's own path variable,
not a user path.*

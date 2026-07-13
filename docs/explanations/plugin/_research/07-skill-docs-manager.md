# Skill Brief: docs-manager

> Research backing for the freya-devkit plugin-wide explainer.
> Topic: **Skill: docs-manager** — standardized project documentation; create/update; impact-aware; knowledge-base/reference outputs; placeholder resolution; diagram upgrade; review; evals.

## Sources read

- `skills/docs-manager/SKILL.md` — main skill definition + frontmatter + full workflow
- `skills/docs-manager/references/templates.md` — per-document templates (README, PROJECT_OVERVIEW, ARCHITECTURE, DATABASE, API, DEPLOYMENT, DEVELOPER, STYLE_GUIDE, INFRASTRUCTURE, SECURITY, CHANGELOG, ENVIRONMENT, TESTING, TROUBLESHOOTING)
- `skills/docs-manager/scripts/detect_project.py` — project-type / stack / test-runner detection helper
- `skills/docs-manager/evals/evals.json` — 4 behavioral evals

Aux files discovered: `scripts/__pycache__/detect_project.cpython-312.pyc` (compiled bytecode, ignored). No other scripts, references, or eval files exist.

---

## What it is

docs-manager is the freya-devkit skill that **creates and maintains standardized project documentation** in a fixed directory layout. Its frontmatter description (`SKILL.md:3-4`):

> "Manages all project documentation in a standardized `knowledge-base/` directory structure."

It is invoked namespaced as `/freya-devkit:docs-manager <mode>`. It is prose/agent-driven — the bulk of the skill is instructions the agent follows, not executable code. The only real code is one Python detection helper (`detect_project.py`).

Architecturally it is a **coordinator + parallel workers** skill (`SKILL.md:19`):

> "This skill creates and maintains comprehensive, standardized project documentation using a **coordinator + parallel workers** architecture. A coordinator agent first analyzes the codebase, then spawns specialized agents in parallel for each documentation type."

## Why it exists

- Give a project (and future AI assistants) a consistent, discoverable documentation set so an engineer or agent can understand the domain, architecture, DB, API, deployment, etc. `PROJECT_OVERVIEW.md` is explicitly framed as "the 'north star' for AI assistants" (`SKILL.md:495`).
- Keep docs **in sync** with the codebase via an `update`/`sync` workflow rather than one-time generation.
- Only produce docs that are relevant: "Not all docs are needed for every project. The skill detects project type and creates only relevant documentation." (`SKILL.md:53`).

## Standard output structure

Per `SKILL.md:34-51` the canonical layout is:

```
knowledge-base/
├── README.md                  # Documentation index and navigation (at root)
└── reference/                 # All project documentation (descriptive, reverse-synced)
    ├── PROJECT_OVERVIEW.md
    ├── ARCHITECTURE.md
    ├── DATABASE.md
    ├── API.md
    ├── ENVIRONMENT.md
    ├── DEPLOYMENT.md
    ├── DEVELOPER.md
    ├── TESTING.md
    ├── STYLE_GUIDE.md
    ├── INFRASTRUCTURE.md
    ├── SECURITY.md
    ├── TROUBLESHOOTING.md
    └── CHANGELOG.md
```

Ownership boundary (`SKILL.md:55`):

> "The README.md stays at the `knowledge-base/` root level as the index, while all other documentation files go in `knowledge-base/reference/`. The `knowledge-base/` root also holds sibling directories owned by other skills (`specs/`, `security/`, `decisions/`, `principles.md`, `.graph/`); docs-manager owns `README.md` and `reference/`."

So docs-manager owns exactly two things inside `knowledge-base/`: the top-level `README.md` index and the `reference/` subtree. Sibling dirs belong to spec-manager (`specs/`, `decisions/`, `principles.md`), the security skills (`security/`), and code-graph (`.graph/`).

## Modes / CLI

From `SKILL.md:21-30` (verbatim mode list):

| Mode | Behavior |
|------|----------|
| `init` | Create initial documentation structure for a new or existing project, then review |
| `update` | Update all documentation to reflect current codebase state, then review |
| `update <doc>` | Update a specific documentation file (e.g., `update api`), then review it |
| `review` | Review docs for consistency, completeness, and accuracy (standalone mode) |
| `sync` | Full sync: analyze codebase and update all docs, then review |
| `resolve` | Scan existing docs for placeholders and help resolve them (standalone mode) |
| `upgrade-diagrams` | Scan all docs and convert ASCII/text diagrams to mermaid format (standalone mode) |
| `help` | Display help information about available commands and usage |

Verbatim invocation examples (`SKILL.md:363-405, 464-470`):

```
/freya-devkit:docs-manager init
/freya-devkit:docs-manager update
/freya-devkit:docs-manager update api
/freya-devkit:docs-manager review
/freya-devkit:docs-manager sync
/freya-devkit:docs-manager resolve
/freya-devkit:docs-manager upgrade-diagrams
/freya-devkit:docs-manager help
/freya-devkit:docs-manager --help
/freya-devkit:docs-manager -h
```

`help` / `--help` / `-h` all trigger the help output (`SKILL.md:431-441`).

## How it works — the pipeline

The full flow (for `init` / `update` / `sync`) runs in phases (`SKILL.md:57-133`):

**Phase 1 — Coordinator agent (analysis)** (`SKILL.md:59-72`): one coordinator does:
1. Project Detection (runtime, framework, database, infrastructure)
2. Business Context Collection — asks the user questions like "What is this project?", "Who are the target users?", "Any specific business rules or domain knowledge to document?"
3. Existing Docs Scan
4. Plan Generation (which docs to create/update)

**Phase 2 — Parallel worker agents** (`SKILL.md:73-96`): coordinator spawns workers IN PARALLEL, one per doc type (up to ~12 listed: PROJECT_OVERVIEW, ARCHITECTURE, DATABASE [if DB present], API [if API present], ENVIRONMENT, DEPLOYMENT, DEVELOPER, TESTING, STYLE_GUIDE, INFRASTRUCTURE, SECURITY, TROUBLESHOOTING). Each worker receives: project analysis from coordinator, business context from user prompts, relevant code paths, and the template from `references/templates.md`. `SKILL.md:227-334` gives each worker a "Context to gather" + "Output" spec (e.g. the API worker gathers route definitions, controller/handler files, auth approach, request/response schemas).

**Phase 3 — Index & summary** (`SKILL.md:98-104`): create the README index with navigation to all docs in `reference/`, brief descriptions, and an onboarding reading order.

**Phase 4 — Placeholder resolution** (`SKILL.md:106-166`): runs automatically for `init`, `update`, `sync`; standalone for `resolve`. Process: scan all docs for `[TODO:` patterns → group placeholders by topic → ask ONE batched question per group (not per placeholder) → apply answers → iterate until resolved or user opts to handle manually. Topic groups: Business Context, Infrastructure, Deployment, Team/Contacts, External Services. Example: three separate `[TODO:` hosting placeholders across INFRASTRUCTURE/DEPLOYMENT/API become one question ("Where is this project hosted…?").

**Phase 5 — Review** (`SKILL.md:114-133`): runs automatically after placeholder resolution for `init`/`update`/`sync`; standalone for `review`. Checks: Consistency, Completeness, Accuracy (cross-reference documented endpoints/schemas/configs against actual codebase), Links, Currency. Output report uses markers: `✅` checks passed, `⚠️` warnings (minor, non-blocking), `❌` issues requiring attention.

**Phase 6 — Diagram upgrade** (`SKILL.md:168-221`): standalone `upgrade-diagrams` mode only. Scans `knowledge-base/reference/` for ASCII/text diagrams (boxes `+--+`, `|`, arrows `-->`/`->`, indented hierarchies), classifies each (Flow/Process→`flowchart TD|LR`, Architecture→`graph TD`, Sequence→`sequenceDiagram`, ER/Database→`erDiagram`, State→`stateDiagram-v2`), converts to mermaid preserving labels/connections, replaces the old diagram, and reports changes.

### Output-format contract (`SKILL.md:498-513`)

Always: (1) create `knowledge-base/` and `knowledge-base/reference/` if absent; (2) write files with the Write tool — `knowledge-base/README.md` index + `knowledge-base/reference/*.md`; (3) summarize what changed; (4) attempt placeholder resolution; (5) run review; (6) report remaining unresolved placeholders + review findings.

## Project detection (`scripts/detect_project.py`)

A standalone, dependency-free Python 3 CLI. Entry point: `python3 detect_project.py [project_dir]` (defaults to `.`), prints a JSON blob (`detect_project.py:380-388`). `analyze_project()` aggregates these detectors:

- **`detect_package_manager`** — runtime + package manager from lockfiles/manifests: Node (`package.json` → pnpm/yarn/bun/npm via lockfile), Python (`pyproject.toml`→poetry/pip, or `requirements.txt`→pip), Go (`go.mod`), Rust (`Cargo.toml`), PHP (`composer.json`). (`detect_project.py:13-55`)
- **`detect_framework`** — reads `package.json` deps for frontend (next/nuxt/react/vue/svelte/angular) and backend (express/fastify/nestjs/hono; Next.js API routes as full-stack fallback); Python deps text for django/fastapi/flask. (`detect_project.py:58-121`)
- **`detect_database`** — Prisma (`prisma/schema.prisma`, parses for postgresql/mysql/sqlite), Drizzle (`drizzle.config.*`), Django models (`**/models.py`), SQLAlchemy (`**/*models*.py`), Mongoose→mongodb from `package.json`. (`detect_project.py:124-170`)
- **`detect_infrastructure`** — containerization (Dockerfile, docker-compose, kubernetes via `apiVersion` in `*.yaml`), CI/CD (github_actions / gitlab_ci / circleci), hosting (vercel.json / netlify.toml / railway.{json,toml}). (`detect_project.py:179-219`)
- **`detect_test_runners`** — returns `{"runners": [...], "evidence": [...]}`. Detects JS runners (jest, vitest, mocha, jasmine, cypress, playwright, cucumber via deps or config files), Python (pytest, pytest-bdd, behave, unittest via test-file naming), and Gherkin `*.feature` files. Notable docstring (`detect_project.py:222-229`): an **empty** runners list is a valid explicit answer — "the Behavior Layer treats 'none' as a loud result, not a missing one. No state is persisted; callers re-run detection whenever they need it." This ties detect_project.py to the newer behavior layer (behavior-runner / behavior-graph skills), not just docs.
- **`detect_existing_docs`** — looks for a `docs/` dir + root-level `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`. (`detect_project.py:308-326`)
- **`get_needed_docs`** — decides the doc set: always README/ARCHITECTURE/DEVELOPER/STYLE_GUIDE/SECURITY; adds DATABASE if DB detected, API if backend detected, DEPLOYMENT+INFRASTRUCTURE if containerization/hosting/ci_cd detected. (`detect_project.py:329-350`)

## Composition with other skills

**code-graph (impact-aware updates).** Frontmatter INTEGRATION line (`SKILL.md:13-14`):

> "Uses /freya-devkit:code-graph skill (when available) for impact-aware documentation updates. Analyzes blast radius of code changes to determine which docs need updating."

Enhanced update workflow (`SKILL.md:407-422`): (1) get changed files from git diff, (2) call `/freya-devkit:code-graph impact <changed-files>` to get blast radius, (3) only regenerate docs for affected areas, (4) update architecture diagrams if dependencies changed. Used by `update` (impact analysis picks which docs) and `sync` (module relationships for architecture docs).

**wrap-up.** docs-manager is one of the post-implementation steps orchestrated by `/freya-devkit:wrap-up` (per the plugin skill tiers: code-graph → docs-manager/spec-manager → security scan → wrap-up). The recommended manual workflow mirrors this (`SKILL.md:473-482`): implement → test → `docs-manager update` → review → commit docs alongside code. (Confirmed by plugin architecture / CLAUDE.md tiering; docs-manager itself only documents the manual side.)

**detect_project.py ↔ behavior layer.** The `detect_test_runners` docstring explicitly references "the Behavior Layer," so this shared detection helper also feeds behavior-runner/behavior-graph. (See gotchas — the docs pipeline text never wires `detect_test_runners` into a doc.)

## Degradation behavior

- **No code-graph / no cached graph:** "fall back to simple git diff analysis." (`SKILL.md:417-418`)
- **Undetectable info:** two-track handling (`SKILL.md:336-361`): key business context → ask the user interactively; technical details → emit a contextual placeholder `[TODO: describe X - e.g., "..."]` with a hint. After creation, Phase 4 attempts automatic batched resolution.
- **Unresolved placeholders:** if resolution can't complete, the skill reports remaining `[TODO:` placeholders rather than blocking (`SKILL.md:147, 513`).
- **Manual triggering:** "This skill uses **manual triggering** — run `/freya-devkit:docs-manager update` after completing features" (`SKILL.md:475`). There is no automatic file-watcher; the human decides when docs regenerate.

## Honest limits

- Almost entirely **prose/agent-executed**: quality of docs depends on the LLM following the SKILL.md instructions. The only deterministic code is `detect_project.py` (detection), and even that is invoked implicitly — SKILL.md never names the script or shows a command to run it.
- Review "Accuracy" and "Links" checks are described as agent behaviors, not automated validators — there's no link-checker or schema-diff tool in the repo.
- `detect_infrastructure` reads **every** `*.yaml` under the project looking for `apiVersion` (`detect_project.py:192-200`), which can be slow / noisy in large repos; it uses a bare `except:`.
- The doc set is opinionated toward web/app stacks (Node/Python/Prisma/Next.js flavored templates); other stacks get generic placeholders.

## Gotchas / UNVERIFIED

- **Path inconsistency between SKILL.md and its own artifacts.** SKILL.md standardizes on `knowledge-base/` + `knowledge-base/reference/`, but `references/templates.md` still writes the README to `docs/README.md` and links to `./project/PROJECT_OVERVIEW.md` etc. (`templates.md:7, 18-37`), and the update snippet in that template says `/docs-manager update` (un-namespaced, `templates.md:43`). Likewise `evals/evals.json` asserts "Creates docs/ directory" and "Creates docs/README.md as index" (`evals.json:7-14`). So the templates + evals reflect an **older `docs/` layout** that lags the current `knowledge-base/reference/` structure in SKILL.md. An engineer should treat SKILL.md as authoritative and regard templates/evals as not-yet-migrated. (CONFIRMED inconsistency by direct comparison.)
- **PROJECT_OVERVIEW/ENVIRONMENT/TESTING/TROUBLESHOOTING/CHANGELOG** are in the SKILL.md structure and templates, but the Phase-2 worker list only enumerates 12 workers and omits an explicit CHANGELOG worker; CHANGELOG appears in the structure and templates but not as a spawned worker. UNVERIFIED whether CHANGELOG is generated automatically or only templated.
- **`detect_test_runners` / `detect_project.py` are not referenced anywhere in SKILL.md.** The detection script exists and is thorough, but the SKILL.md workflow describes detection in prose without invoking the script. UNVERIFIED whether the agent is expected to run `detect_project.py` or just replicate its logic manually.
- **Certainty scoring:** the task focus mentions "certainty scoring," but docs-manager's SKILL.md, templates, and evals contain **no** certainty/confidence scoring mechanism. Certainty scoring is a spec-manager concept (per plugin docs), not docs-manager. docs-manager's nearest analog is placeholder `[TODO:]` markers + the ✅/⚠️/❌ review report. (CONFIRMED absent from docs-manager sources.)
- **Evals are behavioral specs, not an automated harness.** `evals.json` lists 4 prompt/expectation cases (init a Next.js+Postgres project; update API docs; review for completeness; sync after auth feature). There is no runner script in the skill dir — these are evaluated via the plugin's external eval tooling / skill-creator. (UNVERIFIED how they're executed.)

## Verbatim quotable lines

- (`SKILL.md:19`) "This skill creates and maintains comprehensive, standardized project documentation using a **coordinator + parallel workers** architecture."
- (`SKILL.md:53`) "Not all docs are needed for every project. The skill detects project type and creates only relevant documentation."
- (`SKILL.md:55`) "docs-manager owns `README.md` and `reference/`."
- (`SKILL.md:145`) "Batch Questions - Ask the user one question per group, not one per placeholder"
- (`SKILL.md:417-418`) "If `/freya-devkit:code-graph` is not available or no cached graph exists, fall back to simple git diff analysis."
- (`SKILL.md:475`) "This skill uses **manual triggering** - run `/freya-devkit:docs-manager update` after completing features or making significant changes."
- (`SKILL.md:495`) "Keep PROJECT_OVERVIEW.md updated - It's the 'north star' for AI assistants"
- (`detect_project.py:227-229`) "the Behavior Layer treats 'none' as a loud result, not a missing one. No state is persisted; callers re-run detection whenever they need it."

# Project Overview

> Last updated: 2026-08-21

## What freya-devkit is

freya-devkit is a suite of ten skills that an AI coding agent runs against a codebase to keep
the things *around* the code — a dependency graph, reference documentation, feature specs and
ADRs, intended behavior, and security findings — coherent with the code as it changes. The
skills are instruction files (`SKILL.md`) plus stdlib-only Python scripts. There is no service,
no daemon and no model of our own: the agent reads the instructions, the scripts do the
deterministic work, and the output lands in a `knowledge-base/` directory in the target
project — all of it committed except the rebuildable parse cache under `.graph/`, which
ignores itself by name (see [ARCHITECTURE.md](ARCHITECTURE.md)).

It is **agent-neutral**. One set of skill files serves every host that reads the
[Agent Skills standard](https://agentskills.io/specification): no host path, no vendor slash
command, no host tool name. That is a property of the *files*; the installer is narrower and
knows two skills directories by name (below). Every script under `skills/` is reached through
one self-locating launcher, `freya <command>` —
[ADR-013](../decisions/ADR-013-single-freya-launcher.md), the decision every other portability
decision assumes.

Why any of this exists — the argument about monolithic prompts, intent versus implementation,
and what a green test suite does and does not prove — is
[philosophy.md](../philosophy.md). This document covers the concrete: what the thing is, who
runs it, and where its edges are.

## Who it is for

| User | Who they are | What they need from it |
|---|---|---|
| **The coding agent** | Claude Code, GitHub Copilot, or another Agent Skills host, working in a real repository | Instructions it can follow without knowing which host it is; artifacts it can read at the start of a session instead of being told everything; one command surface (`freya …`) that resolves the same way everywhere |
| **The engineer supervising the agent** | The person who will review the diff and own the result | A reviewable change: code in one commit and generated artifacts in another; confidence signals on inferred content; checkpoints where model judgment must be resolved rather than merged; a read-only way to ask "where do I stand" |
| **A repository that has adopted it** | The clone, and CI | Committed artifacts that survive a clone — the chosen graph backend, the observed behavior coverage, the security findings — so CI resolves what the author resolved |

The supervising human is a first-class constraint, not an afterthought:

- A skill writes its artifacts and stops, so the human decides when the second commit happens
  (see the invariants table below).
- AI-inferred specs carry a 0–100 certainty score with a review action attached to each band
  ([patterns.md](../patterns.md#pattern-certainty-scoring)).
- The security driver spends real money and says so before it does: it prints a cost plan
  (`skills/freya-codebase-security-scan/scripts/audit.py:418`) and, with no tty to prompt at,
  refuses rather than defaulting to yes (`audit.py:427`).
- Which graph backend to use is a person's answer: asked once per machine at install
  (`bin/backend_setup.py:104`), resolved project-then-machine-then-floor
  (`skills/freya-code-graph/scripts/settings.py:346`), and never scored automatically —
  `auto` means the floor and nothing else (`skills/freya-code-graph/scripts/backends.py:166`,
  [ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md)).
- Model-judgment checks are *resolve-to-proceed* procedures, not script exit codes; only
  deterministic facts hard-block ([ADR-009](../decisions/ADR-009-two-enforcement-tiers.md)).

## The problem it solves

Artifact drift, change-impact blindness, intentional design getting "fixed" every scan,
AI output arriving without a confidence signal, and tests that mirror the implementation
rather than the intent — the argument for each is [philosophy.md](../philosophy.md), already
linked above.

A sixth was the toolkit's own: **tooling locked to one host.** The suite began as a Claude Code
plugin; the explainer's account of the port is that on Copilot it did not install, and the
parts that did install would not run (`knowledge-base/explanations/index.html`, "Tooling is
locked to one host"). The deterministic Python was already portable — it was the layer telling
an agent *how to use* it that had been written for one vendor. Agent-neutrality is therefore a
construction constraint rather than a compatibility layer, argued in
[philosophy.md](../philosophy.md#7-agent-neutral-by-construction).

## The ten skills, and what each is made of

Ten directories under `skills/`, one per skill. The tier map and what each owns are
[ARCHITECTURE.md](ARCHITECTURE.md); the command surface of each is
[SKILL_REFERENCE.md](SKILL_REFERENCE.md). What this table adds is the engine behind each name.

| Tier | Skill | Engine |
|---|---|---|
| 1 | `freya-code-graph` | 5 scripts |
| 2 | `freya-docs-manager` | 2 scripts |
| 2 | `freya-spec-manager` | 12 scripts |
| 2 | `freya-behavior-graph` | 1 script |
| 2 | `freya-behavior-runner` | 1 script |
| 3 | `freya-codebase-security-scan` | 4 scripts (the audit driver) |
| 3 | `freya-dependency-vulnerability-check` | prose only |
| 4 | `freya-wrap-up` | prose only |
| 4 | `freya-status` | 1 script |
| 5 | `freya-codebase-security-resolver` | prose only |

**Seven skills ship Python; three are prose the agent follows and nothing else.** Which kind a
skill is changes what you can expect of it: a Python engine does the same thing on every host,
and a prose skill does what the host in front of it decides to do. Where that difference is
load-bearing the work was moved into code — the security scan's fan-out
([ADR-015](../decisions/ADR-015-driver-owned-fan-out.md)).

They compose through artifacts on disk, never by calling each other, which is why a missing
sibling costs precision rather than function: with no `code-graph` and no cached graph,
`docs-manager` falls back to plain `git diff` analysis
(`skills/freya-docs-manager/SKILL.md:448`).

## Domain and the rules that shape the implementation

The domain is software maintenance performed by an agent, under review by a person. There is no
end-user product here and no business logic; what stands in for business rules are a handful of
invariants that constrain every skill.

| Rule | What it means in the code |
|---|---|
| Nothing under `skills/` may name a host-specific construct | `bin/check_skill_conformance.py` enforces thirteen rules, R1–R13 (`bin/check_skill_conformance.py:29`), with no exemptions, and CI runs it on every push and pull request (`.github/workflows/ci.yml:18`) |
| Every fact is owned exactly once | A generated projection is allowed; a hand-maintained duplicate is forbidden ([ADR-002](../decisions/ADR-002-authority-order-single-ownership.md)) |
| Specs are authoritative, reference docs are descriptive | Code conforms to specs; docs mirror code. The two are never conflated (ADR-002) |
| Only deterministic facts hard-block | Link integrity, ADR validity, the declared-intent gate, and a regressed accepted behavior block. Model judgment resolves-to-proceed ([ADR-009](../decisions/ADR-009-two-enforcement-tiers.md)) |
| Only `wrap-up` commits generated artifacts | Every other artifact-writing skill writes and stops; `codebase-security-resolver` commits the code fix first (`skills/freya-codebase-security-resolver/SKILL.md:534`). Stated in each SKILL.md, enforced by no script |
| Code and generated artifacts land in separate commits | The two-commit pattern ([patterns.md](../patterns.md)) |
| An answer says what it could not read | A backend that cannot parse an in-scope file names it rather than returning a quiet zero ([ADR-029](../decisions/ADR-029-an-answer-says-what-it-could-not-read.md)) |
| Prose citations are load-bearing | `docs_graph.py` parses `path:line` out of prose into doc-section → code edges, and only resolves a path that is actually in the graph (`skills/freya-docs-manager/scripts/docs_graph.py:199`) |

## What it runs on, and what it talks to

Python **3.9 or newer** is the only requirement
([STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39)). No third-party
runtime dependency: every import in `bin/` and `skills/` is stdlib. The test suite needs
`pytest` as a runner, though the test files themselves are `unittest`.

| External thing | Used for | Required? |
|---|---|---|
| `git` | Incremental updates, the two commits, `freya update` | Yes, in practice |
| An Agent Skills host | Reading the skills. `install.sh` knows two targets by name: `~/.claude/skills` and the shared `~/.agents/skills` (`bin/installer.py:36`) | Yes |
| `claude` / `copilot` CLI | The security driver's headless workers only; without one it exits 1, which the skill reads as "fall back to the in-loop scan" (`skills/freya-codebase-security-scan/scripts/audit.py:66`) | No |
| `graphify` | The optional graph backend — 40 languages (`skills/freya-code-graph/scripts/backend_graphify.py:227`) across 93 extensions (`skills/freya-code-graph/scripts/backend_graphify.py:203`), against the built-in floor's 4 languages across 6 (`skills/freya-code-graph/scripts/graph_ops.py:35`) | No |
| `npm` / `yarn` / `pnpm` | `freya-dependency-vulnerability-check`, which detects the package manager from the lockfile and tells the user it needs a Node project when there is none (`skills/freya-dependency-vulnerability-check/SKILL.md:43`, `:49`) | No |
| The git remote | `freya update`, and a throttled `ls-remote` behind the daily update notice, opt-out via `FREYA_NO_UPDATE_CHECK` (`bin/updater.py:450`) | No |

Three install paths: `./install.sh` and `install.ps1` for any agent (the checkout is the store;
skills are symlinked into the agent's directory, or copied with `--copy`), and a Claude Code
plugin + marketplace under `.claude-plugin/`.

## Measured shape

Counted on 2026-08-21, on the working tree of `test/dogfood-polyglot`:

| Measure | Value | How it was measured |
|---|---|---|
| Skills | 10 | `ls skills/` |
| Launcher commands | 17 in the manifest, plus 6 built into the launcher (`help`, `doctor`, `init`, `install`, `update`, `uninstall`) | `bin/commands.json`; `bin/freya_cli.py:26` |
| Non-test Python | 16,423 lines | `git ls-files '*.py'` minus `test_`/`conftest`, `wc -l` |
| Test Python | 22,200 lines | the same list, `test_`/`conftest` only |
| SKILL.md prose | 5,540 lines across ten files | `git ls-files 'skills/*/SKILL.md' \| xargs wc -l` |
| Tests | 1,759 passed, 1,012 subtests | `python3 -m pytest bin/ skills/ -q` — wall clock and the per-area breakdown are [TESTING.md](TESTING.md#what-the-suite-is-measured) |
| Conformance gate | 13 rules, exit 0 | `python3 bin/check_skill_conformance.py` |
| Citation gate | 1,311 `path:line` citations resolved | `python3 bin/check_doc_citations.py` |
| Tree invariants | stdlib-only, no bare-name `subprocess` argv[0] | `python3 bin/check_invariants.py` |
| ADRs | 29 | `ls knowledge-base/decisions/ADR-*.md` |

CI runs the suite, three static gates and an end-to-end install → launcher → uninstall
([TESTING.md § CI](TESTING.md#ci)).

## What it deliberately is not

- **Not a running system.** No database, no HTTP API, no container. Nothing is tracked in this
  repository that would build or ship one. The scripts run on a developer machine or a CI
  runner and exit. The only deployment tracked here is `.github/workflows/pages.yml`, which
  uploads the static explainer site under `knowledge-base/explanations/` to GitHub Pages.
- **Not enforcement.** The patterns and conventions are guidelines; skills adapt them.
  [philosophy.md](../philosophy.md) names agent-neutrality as the one convention promoted to a
  gate and says why, and [ADR-009](../decisions/ADR-009-two-enforcement-tiers.md) defines the
  separate deterministic tier that hard-blocks in wrap-up.
- **Not a test framework.** `behavior-runner` drives the project's own runner through an
  adapter. Where it cannot observe an edge it emits `unknown` rather than claiming coverage.
- **Not infrastructure tooling.** No resource graph over Dockerfiles, compose files or
  Kubernetes manifests; no Helm; no HCL parser of our own; migrations get no treatment at all.
  The reasoning, including a measured re-run showing graphify's config edges are all intra-file
  and so contribute zero edges, is
  [ADR-027](../decisions/ADR-027-what-is-not-graph-material.md).
- **Not a general dependency auditor.** `dependency-vulnerability-check` wraps `npm`/`yarn`/
  `pnpm audit` and nothing else; on a project with no `package.json` the skill tells the agent
  to say so (`skills/freya-dependency-vulnerability-check/SKILL.md:49`) — it is prose, so
  nothing makes the run stop there. Python, Go, Java and the rest
  have no equivalent here.
- **Not multi-repo.** A graph is built from one `project_dir`
  (`skills/freya-code-graph/scripts/graph_ops.py:389`) and every path in it is relative to that
  root, so a system split across repositories gets one graph per repo and no edge between them
  (open defect 12 in [roadmap.md](../roadmap.md)).
- **Not autonomous.** It does not call a model on its own except in the security driver, which
  refuses to spend money unattended.
- **Not finished, and not uniformly proven.** The live-validation gaps are enumerated under
  "Platform-blocked" in [roadmap.md](../roadmap.md) — most sharply, the toolkit has been
  installed and tested on Windows by CI since 2026-08-18, but **no live agent run has ever
  happened on Windows.**

## Project status

- **Version:** 0.3.0 (`.claude-plugin/plugin.json`). `freya update` consumers do not see
  versions at all — that path fast-forwards the checkout, so every pushed commit is live for
  them.
- **First commit:** 2026-06-19.
- **Current state:** the polyglot graph substrate landed on `test/dogfood-polyglot` on
  2026-08-21 — still `Unreleased` in [CHANGELOG.md](../../CHANGELOG.md) and not yet on `main` —
  and the documentation tree moved from `docs/` to `knowledge-base/` on the same day, which is
  when the toolkit began running on itself. What is outstanding lives in
  [roadmap.md](../roadmap.md) and nowhere else.
- **Maintainer:** one, `AlexSendula` on GitHub. MIT licensed.
- [TODO: Is there a stated adoption target beyond the maintainer's own projects — a team size,
  a repository size, a language ecosystem the toolkit expects? Nothing in the repository names
  one, and the answer changes which of the gaps above are urgent.]

## Related documentation

- [philosophy.md](../philosophy.md) — why the skills exist, and the argument behind each of the
  problems above
- [ARCHITECTURE.md](ARCHITECTURE.md) — tiers, data flow, what is tracked and what is ignored
- [SKILL_REFERENCE.md](SKILL_REFERENCE.md) — every skill's commands, and what each reads and
  writes
- [DEVELOPER.md](DEVELOPER.md) — the conventions a new skill has to fit
- [patterns.md](../patterns.md) — the two-commit pattern, certainty scoring, resolve-to-proceed
- [decisions/](../decisions/) — thirty ADRs, each with the alternative it beat
- [roadmap.md](../roadmap.md) — the single live backlog, including open defects

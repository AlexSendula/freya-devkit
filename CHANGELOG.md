# Changelog

Versions are the ones in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json), which
is what a Claude marketplace consumer sees. **`freya update` consumers do not see versions
at all** — that path fast-forwards the checkout to the tracked branch's head, so every
pushed commit is live for them the moment they run it. See
[CONTRIBUTING.md § Releasing updates](CONTRIBUTING.md#releasing-updates).

## 0.3.1 — the security pass, and what auditing your own corrections turns up (2026-08-24)

Twenty-one findings from the 2026-08-21 scan, plus two more found while fixing them. All
closed or recorded as intentional. Nothing here changes what the toolkit is for; it changes
what it will believe.

**The scanned repository no longer chooses which binary runs.** On Windows `CreateProcess`
searches the current directory before `PATH`, and the toolkit runs its subprocesses with `cwd`
set to the project being scanned — so a repository that committed `graphify.exe` or
`claude.exe` at its root got code execution as the operator. Every external program is now
resolved to an absolute path or refused. The rule is *refuse*, not *absolutise*: a `which()`
result that is not already absolute is rejected, because making it absolute is the fix
backwards. Accepted cost, on one matrix leg: `NoDefaultCurrentDirectoryInExePath` is 3.12+, so
on Windows with Python 3.9–3.11 a hostile repository gets a refusal rather than an execution.

**Gates that reported a clean run they never performed.** The declared-intent gate took five
separate fixes: a marker of `--output=/tmp/victim` truncated that file; forty zeros passed the
hash check and left an empty change-set; a committed file named `deadbeef` made git read the
value as a *pathspec*; a tree hash walked past the regex, `--end-of-options` and `--` alike;
and an empty `commit:` value looked exactly like a fresh repository, so `--advance` erased the
finding. Each vector passed the fix written for the one before it, and each was found by
re-running the attack rather than re-reading the patch.

**Crossing the project root is a declared act.** Discovery inside the root stays automatic —
zero-config on a fresh repository is not traded away — but an import that reaches outside comes
back `unresolved:` unless the project declares the target in `knowledge-base/settings.json`, and
the answer says what it read from outside. The declaration buys *resolution only*: no file under
a declared root is read and no directory under one is enumerated.

**A security finding is harder to silence.** The downgrade path trusted a committed record that
a test covered the flagged file. It now requires that a test actually *ran* — an `exercises`
entry inferred from the import graph no longer counts — requires a locator, carries the named
functions that ran rather than only the file, and can re-run the linked behavior to check.

**One containment gap this release found in its own new feature:** a symlink committed inside
the project pointing outside it was followed and read, with nothing declared. Fixed here, and
worth naming because the claim "nothing crosses the root undeclared" had already been written
into the README and two explainer pages before anyone tested it against a symlink.

Also: path containment is one rule in one place instead of two copies that agreed by luck; the
status census counts an unrecognised finding status instead of silently reporting zero; secrets
are redacted where a finding is created rather than at each of the three places it leaves; every
GitHub Action is SHA-pinned; and the docs walk is bounded, refuses symlinks, and reads bytes
rather than decoding.

**The most useful thing this release found was in its own corrections.** The pass whose entire
job was accuracy wrote three new unqualified safety claims — "validate_graph now *rejects* any
non-project-relative key" (it reports, and the graph is written anyway), "*every* containment
question goes through one module" (one deliberately does not), "*no* symlink crosses on its
own" (one did). Same shape as the defects being fixed. The only thing that caught any of them
was going and running it.

## 0.3.0 — the polyglot substrate, and the toolkit run on itself (2026-08-23)

The code graph everything else stands on was one hand-written resolver reading four languages.
Point it at a Java project and it found nothing, printed *"Built dependency graph: 0 files
scanned"*, and exited 0 — and the shape detector, which decides whether a project is new by
counting internal edges, then classified a decade-old codebase as an empty scaffold. That was
the wall, hit on the first attempt to use the toolkit on a work laptop.

**The graph is now produced through a contract with interchangeable backends.**

- `homegrown` ships with the toolkit, needs nothing but Python, reads 4 languages across 6
  extensions, and is the floor — it always runs unless something else is named. The driving
  case is a locked-down machine where a package install is blocked, and the floor is what
  guarantees the toolkit degrades to *something* everywhere rather than to nothing.
- `graphify` is opt-in, needs its binary on `PATH`, and reads **40 languages across 93
  extensions** plus `calls`/`inherits`/`references` relations the floor has no notion of.

**Choosing one is a person's decision.** `freya install` asks once and records the answer as
your machine default; the first build in a project writes it into that project's committed
`knowledge-base/settings.json`, so a clone and CI resolve the same backend you do. It is never
scored automatically — installing a binary anywhere on `PATH` must not silently change every
blast radius on the machine.

```bash
uv tool install "graphifyy[sql,terraform]"
freya code-graph --use graphify --global
```

**Every answer now says what it could not read.** `build`, `update`, `query` and `impact` may
carry an `unmapped_source` block naming the in-scope source the backend could not parse and the
directories to grep instead; `dependents`/`dependencies` keep their bare arrays and say it on
stderr. The key is absent when there is nothing to say, so its presence means the answer above
it is computed over an incomplete graph.

**Also in this change**

- An edge is an object carrying `kind` and `provenance` behind a versioned schema, instead of a
  bare path string. Measured: the old shape could express 2,102 of graphify's 5,027 connections.
- Optional symbol refinement on edges — which symbol an edge leaves and arrives at — off by
  default, and never replacing the file anchor.
- Every built-in exclusion is now a default a project can overrule, in two tiers.
- Each backend writes its own `graph.<backend>.json` beside the active graph, so a substrate
  swap can be diffed rather than destroying the baseline it should be measured against.
- Fixed: `--update` silently no-opped whenever the project sat below the git root, freezing the
  graph while reporting success. Fixed: transitive traversal was recursive and raised
  `RecursionError` on repositories past roughly 1,200 connected files.

**Migration:** none. Existing graphs are read and brought forward; a project that names no
backend gets the floor, which is what it already had.

**Decisions:** ADR-018 through ADR-029.

### freya-devkit now runs on itself

The toolkit had never been pointed at its own repository, because its documentation lived in a
hand-maintained `docs/` and the skills read and write `knowledge-base/`. That tree has moved:

| Was | Is |
|---|---|
| `docs/architecture.md` | `knowledge-base/reference/ARCHITECTURE.md` |
| `docs/conventions.md` | `knowledge-base/reference/DEVELOPER.md` |
| `docs/skill-reference.md` | `knowledge-base/reference/SKILL_REFERENCE.md` |
| `docs/backlog.md` | `knowledge-base/roadmap.md` |
| everything else under `docs/` | the same path under `knowledge-base/` |

This affects anyone who linked to a file in this repo's `docs/` — including the explainer site,
which now points at the new paths. `backlog.md` is `roadmap.md` because `freya status` writes
`knowledge-base/BACKLOG.md` by full overwrite, and a hand-written backlog parked there would be
destroyed on the first run.

**Three defects surfaced the moment it ran on itself**, all of them in the shipped tool rather
than in this repo:

- `docs-manager` could not see its own output. Its stack detector looked only for `docs/`, so
  on any project that had already adopted `knowledge-base/` it reported no documentation at all
  and planned a from-scratch create instead of a reverse-sync.
- `freya principles list` printed a blank line and exited 0 for a project with no
  `principles.md` — indistinguishable from a file that exists and declares nothing.
- `freya doctor` reported a `freya` on `PATH` as healthy without checking it was the same tree
  it had just inspected, so running it from a checkout while a released copy was installed gave
  a green row for a binary the shell would never run.

Also: `**/.graph/` is gone from this repo's `.gitignore`. `code-graph` writes its own
`.gitignore` inside `knowledge-base/.graph/` naming the regenerable files individually so
`behavior.json` stays committable (ADR-017) — but git never descends into a directory an
ancestor ignored, so the root rule silently won. Any adopting project that added `**/.graph/`
by hand has the same problem.

### The toolkit was run against itself, and found what it is for

The hand-written `docs/` tree became `knowledge-base/` — the same layout freya creates in any
adopting project — so the toolkit could finally read its own documentation. The full flow then
ran end to end for the first time: code graph, docs graph, a brownfield scan producing **30
specs and 149 proposed behaviors**, and a security scan.

Everything reported clean. Three things were not.

- **`freya verify-links` printed "all behavior links pass" while 17 of 149 were broken.** A
  locator is `path#Class.method`; `parse_locator` returns both halves and the caller bound the
  second to a discard, so for every non-Gherkin adapter the entire check was "does the file
  exist". `adapter: manual` skipped the check altogether rather than skipping the runner.
  Proven by renaming all 132 locator targets out of existence: exit 0, suite green. Both holes
  are closed and the fragment now resolves by AST.
- **The behavior-runner could not execute a Python test.** It had an executor for vitest and
  none for Python, so of 132 unittest behaviors, 106 were never run, 26 got a static guess, and
  zero executed. `accepted` was unreachable. A pytest adapter now exists, degrading cleanly
  when `coverage.py` is absent rather than reporting empty coverage.
- **`freya status` reported 57 coverage gaps where 24 were real** — it was counting its own
  test files, `conftest.py` and three non-Python files, and `BACKLOG.md` carried the wrong
  number to the user.

The security scan raised 22 findings against the toolkit. The two most severe are the same
defect twice: workers are invoked by the bare name `claude` with the *scanned* repository as
their working directory, so on Windows that repository can supply its own `claude.exe` and have
it run as the operator. The read-only allowlist is expressed in argv, and argv only binds the
program you meant to start. Filed, not yet fixed.

### Three gates that did not exist

- `bin/check_doc_citations.py` resolves every `path:line` citation in the tracked prose — 1,311
  of them. It found 55 broken on landing, all repaired by reconstructing each file at the commit
  its document was authored against rather than moving numbers to the nearest non-blank line.
- `bin/check_invariants.py` reads the AST for two whole-tree properties: every import is stdlib
  or a sibling, and no `subprocess` call takes a bare-name `argv[0]`. The stdlib rule was the
  repo's most load-bearing convention and was checked by nothing; its violation is invisible on
  the machine that commits it.
- Both run in CI beside the suite and the conformance gate.

Suite 1,435 → 1,759 tests, 52 → 1,012 subtests. The subtest jump is the real change: registries
were tested by naming a few members by hand — `RELATIONS` declared 32 relation kinds and named
twelve — and are now driven off the registry itself, so a member added later is covered the day
it lands. Six tests were found green and vacuous, each proven so by mutation before repair; one
was the only guard on a path traversal in the security scan's own disposition path.

## 0.2.0 — portability (2026-08-18)

The toolkit stops being a Claude Code plugin that happens to be portable and becomes an
agent-neutral suite that happens to ship as a Claude plugin too. Validated live on
**GitHub Copilot CLI** and **Claude Code**.

### Breaking — every skill was renamed

The Agent Skills spec requires a skill's frontmatter `name` to equal its directory name,
and a shared `~/.agents/skills/` has no namespace to keep `status` or `code-graph` from
colliding with someone else's skill. So the directories themselves carry the prefix now,
rather than the installer applying one:

| Before | After |
|---|---|
| `/freya-devkit:code-graph` | `/freya-devkit:freya-code-graph` |
| `/freya-devkit:docs-manager` | `/freya-devkit:freya-docs-manager` |
| `/freya-devkit:spec-manager` | `/freya-devkit:freya-spec-manager` |
| `/freya-devkit:behavior-graph` | `/freya-devkit:freya-behavior-graph` |
| `/freya-devkit:behavior-runner` | `/freya-devkit:freya-behavior-runner` |
| `/freya-devkit:codebase-security-scan` | `/freya-devkit:freya-codebase-security-scan` |
| `/freya-devkit:codebase-security-resolver` | `/freya-devkit:freya-codebase-security-resolver` |
| `/freya-devkit:dependency-vulnerability-check` | `/freya-devkit:freya-dependency-vulnerability-check` |
| `/freya-devkit:wrap-up` | `/freya-devkit:freya-wrap-up` |
| `/freya-devkit:status` | `/freya-devkit:freya-status` |

There is no alias and no deprecation period: the old names are directory names that no
longer exist. Anything that referenced one — a saved prompt, a team runbook, a project's
`AGENTS.md`, a `CLAUDE.md` — needs the new name. Full migration notes, including the
non-Claude install paths:
[`knowledge-base/migrations/skill-rename.md`](knowledge-base/migrations/skill-rename.md).

### Added

- **`freya`, a launcher.** One command surface for every agent
  (`freya code-graph --build`, `freya status`, …), self-locating via `__file__` and
  running targets with `sys.executable`. Commands are declared in `bin/commands.json`.
- **`install.sh` / `install.ps1`.** The checkout is the canonical store; the installer
  symlinks (or `--copy`-materializes) each skill into an agent's skills directory and
  places the launcher in `~/.local/bin`. `--agent`, `--copy`, `--force`, `--dry-run`,
  `--uninstall`.
- **`freya update`** — fast-forward-only refresh of the store plus a re-link, with a
  throttled, notify-only "update available" line on ordinary commands
  (`FREYA_NO_UPDATE_CHECK=1` disables it).
- **`freya doctor`** — suite root, Python, launcher on PATH, per-agent links, orphaned
  entries, duplicate installs.
- **`freya init`** — writes a marker-delimited freya-devkit section into a project's
  `AGENTS.md`, replacing it in place on re-runs and leaving every other byte alone.
- **The audit driver** (`freya security scan|audit`) — a Python driver that owns the
  security fan-out on its own worker pool of headless agent processes, under a read-only
  tool allowlist, with schema validation, bounded retry, cross-round dedup and N-skeptic
  majority voting. It replaces the Claude Workflow engine and it is why the security
  scan's guarantee no longer depends on the agent choosing to delegate.
- **CI** (`.github/workflows/ci.yml`) — the suite, the conformance gate and a real
  end-to-end install, on Linux and Windows, Python 3.9 and 3.13.

### Changed

- Every `SKILL.md` invocation moved from `python "${CLAUDE_PLUGIN_ROOT}/…"` to
  `freya <command>`. `bin/check_skill_conformance.py` fails the build if a Claude-only
  construct comes back.
- Fan-out prose is agent-neutral: run in parallel where the agent supports subagents,
  one at a time otherwise. Where the guarantee is load-bearing (the security scan) the
  prose was replaced outright by the driver.

### Removed

- `workflows/codebase-security-audit.js` — the Claude Workflow implementation of `audit`,
  superseded by the driver above. `audit` now runs on any supported agent CLI.

## 0.1.0

The Claude Code plugin as it stood before the portability track: ten skills invoked as
`/freya-devkit:<skill>`, scripts located through `${CLAUDE_PLUGIN_ROOT}`, `audit` running
on the Claude Workflow tool.

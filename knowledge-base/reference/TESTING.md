# Testing

> Measured 2026-08-21 against commit `f407251`, on macOS with CPython 3.12.5 and pytest 9.0.1.
> Every number below is reproducible with the command printed beside it.

## Overview

There is one suite. It is stdlib `unittest`, it lives beside the code it covers, and it is
normally run with pytest. There is no second tier of "integration tests", no e2e harness, no
fixture framework and no coverage tool — the project has no database, no HTTP surface and no
container, so the template sections for those are absent rather than empty.

Two gates guard a commit, and they are not the same gate: the suite, and
`bin/check_skill_conformance.py`. Both run in CI.

## The stack

| Tool | Role |
|---|---|
| `unittest` (stdlib) | How every test is written — 29 files, `unittest.TestCase` throughout. No pytest fixtures, no `assert` rewriting. |
| `pytest` | The runner CI uses, and the only package installed anywhere in this project (`.github/workflows/ci.yml:79`). |
| `python3 -m unittest discover` | The no-install fallback. Works per directory; see below for what it loses. |
| `unittest.mock` | The only mocking available, and used sparingly — see "Real dependencies". |

Nothing under test imports a third-party module. That is not an aspiration; it is why the CI
job can install exactly one package and why `unittest discover` remains a real fallback.

## Running the tests

```bash
python3 -m pytest -q                      # everything, from the repo root
python3 -m pytest bin/ skills/ -q         # what CI runs (.github/workflows/ci.yml:82)
python3 -m pytest skills/freya-code-graph/scripts/test_graph_ops.py -q   # one file
python3 -m pytest -k unmapped -q          # one subject
python3 bin/check_skill_conformance.py    # the second gate; must exit 0
```

`python3 -m unittest discover -s bin -p 'test_*.py'` also works, and so does the same command
against any single `skills/*/scripts/` directory — measured: 456 tests in `bin/`, 216 in
`skills/freya-spec-manager/scripts/`, both green. What it loses is the root `conftest.py`,
which unittest does not know about; see "conftest.py" below for why that matters less than it
used to.

## What the suite is, measured

`python3 -m pytest -q` from the repo root at `f407251`:

```
1435 passed, 52 subtests passed in 24.74s
```

Broken down by area (`python3 -m pytest <dir> -q` in each):

| Area | Tests | Wall clock |
|---|---:|---:|
| `bin/` | 456 (+52 subtests) | 11.2s |
| `skills/freya-code-graph/` | 384 | 9.6s |
| `skills/freya-spec-manager/` | 216 | 1.9s |
| `skills/freya-codebase-security-scan/` | 207 | 1.3s |
| `skills/freya-docs-manager/` | 68 | 0.05s |
| `skills/freya-behavior-runner/` | 46 | 0.5s |
| `skills/freya-behavior-graph/` | 43 | 0.05s |
| `skills/freya-status/` | 15 | 0.02s |

`bin/` and `freya-code-graph/` are 21s of the 24.7s, and almost all of that is real
subprocesses: `git` against real repositories, the launcher run end to end, and the `graphify`
binary when it is installed. The other six areas together finish in under four seconds, so
`python3 -m pytest skills/freya-spec-manager -q` while iterating costs nothing.

The **52 subtests** are `self.subTest(...)` loops, all in `bin/` — nine loops across
`bin/test_agents_md.py` and `bin/test_freya_cli.py`. pytest reports each iteration's outcome
separately from the 1435 test items; `unittest` reports only the enclosing test methods, which
is why `unittest discover -s bin` says `Ran 456` where pytest says `456 passed, 52 subtests
passed`. Neither total double-counts.

**How the number moves.** Remove `graphify` from `PATH` and the same command gives
`1421 passed, 14 skipped` — the fourteen are guarded by `unittest.skipUnless(HAVE_GRAPHIFY, ...)`
(`skills/freya-code-graph/scripts/test_backend_graphify.py:31`). That is the shape CI runs in,
since the runner installs nothing but pytest. Measure against a clean export
(`git archive HEAD | tar -x -C …`) if you want a number tied to a commit rather than to whatever
is currently in your working tree.

## Where tests live

Beside the code they test, never in a separate tree:

```
bin/installer.py                                  ← bin/test_installer.py
bin/check_skill_conformance.py                    ← bin/test_check_skill_conformance.py
skills/freya-code-graph/scripts/graph_ops.py      ← .../test_graph_ops.py
skills/freya-spec-manager/scripts/frontmatter.py  ← .../test_frontmatter.py
```

29 files in total: 6 under `bin/`, 23 under `skills/*/scripts/`. Three consequences of that
layout are worth knowing before you add a file.

**There are no packages.** No `__init__.py` exists anywhere in `bin/` or `skills/`, so pytest
imports each test module under its default `prepend` mode with the file's directory on
`sys.path`. Test-file **basenames must therefore stay unique across the whole repo** — two
`test_utils.py` in different skills would collide at import. All 29 names are currently
distinct.

**A test imports its subject by bare name, from the subject's own directory.** Nineteen of the
29 make that explicit with one line:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

The other ten simply write `import installer` or `import audit_io` and rely on pytest's
`prepend` mode putting the test file's own directory on `sys.path` — which is also what
`unittest discover -s <dir>` and a direct `python3 bin/test_installer.py` do. Both work; the
explicit form is the safer default for a new file.

This is not boilerplate that could be hoisted into a conftest. There is no packaged cross-skill
import path in the shipped layout, so a skill that needs another skill's Python either shells out
to it or puts that skill's `scripts/` on `sys.path` by relative path first. ADR-004 states the
first half as the rule — "cross-skill access is a subprocess call against the suite root, not a
Python import" — but the shipped tree contains four such imports, all intra-store and all
resolved the same way: `skills/freya-behavior-runner/scripts/run_behaviors.py:20`,
`skills/freya-behavior-graph/scripts/behavior_graph.py:20` and `:28`, and
`skills/freya-status/scripts/collect_status.py:20`. Three reuse `freya-spec-manager`'s
frontmatter parser rather than duplicate it; the fourth reuses the runner's `load_behaviors`.

**`unittest.main()` goes at the very bottom of the file.** Twelve of the 29 carry it, and only
those twelve can be run as `python3 <file>`. The placement is load-bearing and was learned by
losing tests: in `bin/test_check_skill_conformance.py` the call once sat mid-file, so running
the file directly executed it before the last class was defined and silently skipped five tests
— every R10 case, including the regression guard for the defect R10 exists for. 86 reported, 91
collected (`bin/test_check_skill_conformance.py:936`).

## conftest.py — what the session isolates

The repository root holds a single `conftest.py` (27 lines). It does one thing: point
`FREYA_HOME` at a fresh throwaway directory before collection begins
(`conftest.py:26`, `conftest.py:27`).

The reason is that `settings.load()` consults a machine-level default at
`~/.freya/settings.json` — the graph backend the engineer chose once at install time
(`skills/freya-code-graph/scripts/settings.py:59`, ADR-019). Backend selection reads it, and
every graph build reads backend selection. Without the sandbox, the answer to "does a project
with no settings resolve to the floor?" depends on whose laptop is running the tests. A suite
whose result depends on unversioned state outside the checkout is not a regression gate.

It is claimed at module scope rather than in a fixture so that a module reading settings at
**import** time is covered too.

**Know its one hole.** A `conftest.py` is only collected when pytest's rootdir is at or above it,
so `cd skills && python3 -m pytest .` routes around it entirely. That hole was once expensive —
ten tests failed that way against a real `~/.freya/settings.json`. It is currently harmless, and
that is a property of the tests, not of the net: measured today,
`cd skills && FREYA_HOME=<dir containing a graphify-selecting settings.json> python3 -m pytest .`
gives `979 passed`. The tests that depend on the machine default now isolate themselves.

## FREYA_HOME sandboxing in `setUp`

This is the convention the hole above forced, and it is the mechanism — `conftest.py` is the
safety net.

**If a test asserts what happens with nothing configured, or drives code that reads settings,
it sandboxes `FREYA_HOME` in its own `setUp` and restores it on cleanup.** The shape, from
`bin/test_backend_setup.py:26`:

```python
def setUp(self):
    self.home = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
    self.previous = os.environ.get("FREYA_HOME")
    os.environ["FREYA_HOME"] = self.home
    self.addCleanup(self._restore)      # pops it if it was unset, else restores
```

Three placements are in the tree:

- A shared base class, where several test classes need it:
  `MachineHome` in `skills/freya-code-graph/scripts/test_substrate.py:552`, inherited by
  `TestSettings`, `TestTheMachineLevelDefault` and `TestBackendSelection`. Its docstring is the
  canonical statement of the rule.
- A per-file `Base.setUp`: `bin/test_backend_setup.py:26`.
- A single class that needs it: `skills/freya-code-graph/scripts/test_graph_ops.py:1914`,
  `skills/freya-behavior-runner/scripts/test_run_behaviors.py:413`.

Restoration is `addCleanup` everywhere except `test_run_behaviors.py:416`, which restores in
`tearDown`; either way it restores the *previous* value rather than deleting the variable,
because the session-level sandbox has already set it.

**A subprocess does not inherit an isolation you only applied in-process if you also pass a
trimmed `env`.** Tests that shell out build it explicitly:
`env=dict(os.environ, FREYA_HOME=self.home)`
(`skills/freya-code-graph/scripts/test_graph_ops.py:1925`,
`skills/freya-code-graph/scripts/test_graph_ops.py:2352`). The second of those carries the
measurement that justifies it: on a machine that answered the install question with `graphify`,
every fixture builds with a backend that reads `.java`, the census correctly reports nothing, and
six assertions about twelve unmapped files fail — green here, red on a colleague's laptop
(`skills/freya-code-graph/scripts/test_graph_ops.py:2339`).

Writing the isolation where the test is, rather than only in `conftest.py`, is also better
documentation: a test asserting "with nothing configured" should say so at the point it asserts it.

## Vacuous tests, and the mutation check

The second convention this repo learned the hard way.

**A test whose fixture is discarded before the line it names is reached passes for the wrong
reason.** The worked example is the unmapped-source census.
`substrate.CENSUS_PRUNE` (`skills/freya-code-graph/scripts/substrate.py:865`) is a set of
directory names — `node_modules`, `dist`, `build`, `vendor`, `target` and others — that the walk
prunes *before* it calls `_should_exclude`
(`skills/freya-code-graph/scripts/graph_ops.py:2625`). An earlier version of
`test_it_honours_the_build_s_own_exclusions` built its fixture under `node_modules/` and `dist/`.
The assertion passed. It would also have passed with `_should_exclude` deleted, because no
fixture file ever reached it (`skills/freya-code-graph/scripts/test_graph_ops.py:2011`). The fix
was to rebuild the fixture out of paths only `_should_exclude` rejects, and to add a separate
test pinning that the prune list and the scope rule *both* apply
(`skills/freya-code-graph/scripts/test_graph_ops.py:2027`).

The same shape has been found twice more:

- The dotfile guard. The fixture used `.env.local` and `.eslintrc.json`, whose extensions are in
  neither tier list, so every file was dropped by the extension check before the guard ran
  (`skills/freya-code-graph/scripts/test_graph_ops.py:2050`).
- The graph contract's reverse-edge validator: two `dependents` checks that could be deleted with
  the whole suite still green (`skills/freya-code-graph/scripts/test_substrate.py:324`).

**So: mutation-check a new test. Break the code it claims to cover and confirm the test goes
red.** Two lines, and it is the only evidence that the test does anything.

Worked, measured, on this checkout:

```bash
# delete the two-line dotfile guard at graph_ops.py:2627-2628, then:
python3 -m pytest skills/freya-code-graph/scripts/test_graph_ops.py -q
# → 1 failed, 163 passed
#   FAILED ...::TestUnmappedSourceWalk::test_dotfiles_and_extensionless_files_are_skipped
# restore, re-run → 164 passed
```

Weak assertions fail this check even when the fixture is right. The graphify edge-translation
gate is the measured case: pinning `(from, to)` pairs alone, it caught **one of six** deliberate
mapping mutations, because the fixture carried each pair on several relations and dropping one
changed nothing the assertion could see. Pinning `(from, to, kind)` over a fixture that exercises
each guard is what made it bite (`skills/freya-code-graph/scripts/test_backend_graphify.py:582`).

ADR-016 states the underlying clause: guards that protect against a measured external finding are
mutation-tested, not merely unit-tested.

## Real dependencies, injected only where honesty requires it

Also ADR-016. **Drive the real dependency wherever a real one can be produced honestly.** The
updater's tests run actual `git` in temporary directories — an origin repo plus a clone — and
cover fast-forward, dirty refusal, missing upstream, non-git store and a diverged branch. Mocks
model a well-behaved dependency, and almost everything interesting about an update command is a
refusal.

Where a real dependency may be absent, skip rather than fake:

```python
HAS_GIT = shutil.which("git") is not None          # bin/test_updater.py:17
@unittest.skipUnless(HAS_GIT, "git is not installed")   # bin/test_updater.py:50
```

`skills/freya-code-graph/scripts/test_backend_graphify.py:31` does the same for the `graphify`
binary — those are the 14 skips CI takes.

Injection is reserved for three cases, and each is argued rather than assumed:

- **Behaviour a real dependency cannot produce honestly.** A hang. The update-notify check takes
  an injected runner to assert that a fresh cache makes no network call and that a raising runner
  cannot change the command's exit code.
- **Calls that cost money or are non-deterministic.** The audit driver's `ask` is a parameter, so
  `skills/freya-codebase-security-scan/scripts/test_audit_engine.py` never invokes a real agent
  CLI. The tests there also pin those constants to literals rather than assert against the
  module's own values — "Literals, not the constants under test: asserting against
  `audit_engine.K_EMPTY` would adapt to a mutation of it and prove nothing"
  (`skills/freya-codebase-security-scan/scripts/test_audit_engine.py:181`).
- **A cross-skill subprocess boundary.** `freya-behavior-graph`'s tests patch
  `_run_behavior_runner` and never execute a real test runner. That is only possible because the
  graph layer *executes* the runner through exactly one subprocess call
  (`skills/freya-behavior-graph/scripts/behavior_graph.py:206`) — the seam ADR-004 exists to
  preserve. It also imports `run_behaviors` directly for `load_behaviors`
  (`skills/freya-behavior-graph/scripts/behavior_graph.py:29`), but that path only reads specs
  and runs no tests, so it is left unpatched.

## The conformance gate

The second gate. Its scope, its thirteen rules and its output are
[DEVELOPER.md § The conformance gate](DEVELOPER.md#the-conformance-gate); what belongs here is
its relationship to the suite.

It has its own test file — 120 tests, the largest in `bin/` — which builds fixture trees per
rule, plus one test that runs the real scan over the real tree:
`ShippedTreeTest` (`bin/test_check_skill_conformance.py:919`).

**A claim repeated in two places about this gate does not survive measurement.**
`.github/workflows/ci.yml:84` says the test suite "passes with an R1 violation live in a shipped
SKILL.md", and `CONTRIBUTING.md:139` says a shipped SKILL.md "can violate most of R1–R13 with the
whole pytest suite green". Measured at `f407251`: appending a `${CLAUDE_PLUGIN_ROOT}` invocation
to `skills/freya-wrap-up/SKILL.md` and running `python3 -m pytest bin/ skills/ -q` gives
`1 failed, 1434 passed` — `ShippedTreeTest::test_the_shipped_skill_layer_is_conformant`. The same
happens for an R2 violation. `ShippedTreeTest` calls `csc.scan(root)` with no rule filter
(`bin/check_skill_conformance.py:374`), so it catches everything the standalone gate catches.
`ShippedTreeTest` and `ci.yml` were added by the same commit (`51bdadb`, 2026-08-18), so the
comment was inaccurate when it was written.

What is still true, and is the reason to keep running both:

- The gate runs **without pytest installed**, and is what CONTRIBUTING asks a contributor to run
  before committing.
- `--root` points it at a different checkout — an installed tree, for instance. `ShippedTreeTest`
  only ever scans its own.
- `pytest skills/` alone would miss it, since `ShippedTreeTest` lives in `bin/`. CI runs
  `pytest bin/ skills/`.
- CI keeps them as separate steps so a conformance failure is legible as one, rather than as a
  line in a test summary (`.github/workflows/ci.yml:86`).

Resolved 2026-08-21: both were wrong and both are corrected. `ShippedTreeTest` calls
`csc.scan(root)` with no rule filter, so there is no violation it cannot reach in the tree it
scans. Verified by mutation — appending a `${CLAUDE_PLUGIN_ROOT}` reference to
`skills/freya-status/SKILL.md` makes `pytest -k ShippedTree` fail with
`skills/freya-status/SKILL.md:83: R1`, and the standalone gate exits 1 on the same input and 0
once it is reverted. The reason to keep running the script separately is legibility, not
coverage.

## CI

`.github/workflows/ci.yml` runs on every push and pull request. The job matrix is
[CONTRIBUTING.md § Tests and the CI gate](../../CONTRIBUTING.md#tests-and-the-ci-gate); what
each job actually runs is below.

The `tests` job installs pytest and nothing else (`.github/workflows/ci.yml:79`), then runs two
steps: `python -m pytest bin/ skills/ -q` and `python bin/check_skill_conformance.py`.

The `install` job is deliberately separate rather than more steps on `tests`, so a failing test
cannot hide the install's answer behind an early exit. It drives `install.sh` (symlink mode) on
Linux and `install.ps1 --copy` on Windows, asserts a skill landed, resolves `freya` **by name off
`PATH`**, runs `freya help` and `freya doctor`, then uninstalls and asserts the skills came back
out — plus the launcher on Linux; the Windows leg only reports what is left in `bin/`
(`.github/workflows/ci.yml:203`). The installer's `--target-dir` / `--bin-dir` hooks keep it off
the runner's real `~/.claude`.

**pytest is left unpinned on purpose.** pytest 9 requires 3.10+, and pip's `Requires-Python`
resolution is what hands the 3.9 legs of the matrix the 8.x line — so the runner differs
between legs by design. Why 3.9 is the floor at all is
[STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39).

`GIT_TERMINAL_PROMPT: '0'` is set workflow-wide so anything shelling out to git fails rather than
hanging at a credential prompt until the step times out.

## What a green tick does not prove

Beyond what [CONTRIBUTING.md § Tests and the CI gate](../../CONTRIBUTING.md#tests-and-the-ci-gate)
already lists — the unexercised install diagonal, the absent agent CLI, and Windows-exclusive
code that cannot go red on a POSIX run — two are the suite's own:

- **No coverage is measured at all.** No coverage tool is installed, configured or run. The
  template's line/branch/function thresholds have no counterpart here, and inventing one would be
  a number nobody computes.
- **No `graphify` on the runner**, so the 14 backend tests skip there. Backend-translation
  regressions are caught only on a machine that has the binary.

## The behavior layer, and why this repo has none

The behavior layer is the project's other notion of "test", and it is not a second suite. A
behavior record is bound to a test that already exists, through an **adapter plus a locator**
(ADR-004): a Gherkin scenario, or a native test named by path and identifier. Native adapters
rewrite nothing — that is the whole point, since re-authoring an existing suite into Gherkin is
the adoption cost that would have killed the layer. Gherkin scaffolds are the only shape that
carries a written `TODO(scaffold)` marker
(`skills/freya-spec-manager/scripts/adapters.py:26`), which is what lets integrity checks tell an
unwritten scaffold from a real linked test.

Running is split from graphing (ADR-004): `freya-behavior-runner` executes accepted behaviors and
emits coverage fingerprints on stdout; `freya-behavior-graph` owns `behavior.json`. Coverage
provenance follows ADR-006 — `observed` at unit level from the runner's native coverage output,
`static` import closure at integration level, merged in trust order `observed` > `static`
(`skills/freya-behavior-graph/scripts/behavior_graph.py:37`), with `OBSERVED_CONFIDENCE = 0.8`
against `STATIC_CONFIDENCE = 0.5` (`skills/freya-behavior-runner/scripts/run_behaviors.py:26`).
ADR-006 names a third and higher tier, `explicit`, but marks it "reserved, unimplemented"
(`knowledge-base/decisions/ADR-006-real-interface-execution-and-coverage.md:24`) and no shipped
script mentions it. A behavior with no usable coverage is emitted `coverage: unknown` with a
reason, never as a silently empty result.

**This repo currently has zero behaviors defined for itself.** There is no
`knowledge-base/specs/` directory, `behavior.json` holds an empty `behaviors` map, and
`freya status --project .` reports `behaviors: 0 proposed, 0 confirmed, 0 accepted, 0
quarantined, 0 deprecated` and a `test-owed worklist` of `0`, alongside **65 coverage gaps** —
which is every source file in the code graph, because nothing exercises anything in the behavior
layer's sense. So none of the 1435 tests above is traceable to a behavior record, and the
behavior-link half of `wrap-up`'s Phase 3.5 has nothing to verify here (its ADR-integrity step
still does).

**And the runner could not execute one today even if it existed.** `KNOWN_ADAPTERS` allow-lists
`pytest` and `unittest` (`skills/freya-spec-manager/scripts/frontmatter.py:94`), so such a
behavior would validate and could be authored. But the only implemented execution path is
unit level with `adapter: vitest`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:392`). Nothing else is ever run: a
`confirmed` behavior and an `integration`-level one get a static fingerprint from their `entry`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:391`,
`skills/freya-behavior-runner/scripts/run_behaviors.py:397`), and every remaining shape falls
through to `reason="level-deferred"`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:399`) — unknown coverage. A Python
behavior here would get a static fingerprint from its `entry` at best. This is deliberate and
recorded: [`roadmap.md`](../roadmap.md) § P4c says a
`pytest` adapter is the interesting missing one because it adds Python as a second language
(`coverage.py --cov-report=json` and a small parser), and says the if-ladder should become a
runner-adapter registry when it is picked up.

[TODO: now that the toolkit runs on itself, should this repo author behaviors for its own
user-visible commands — accepting that they stay `coverage: unknown` until P4c lands — or wait
for the pytest adapter first?]

## Related documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — what the pieces are and which artifacts they write
- [DEVELOPER.md](DEVELOPER.md) — conventions for writing a skill that fits
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — the commit-time checklist and the release paths
- [ADR-016](../decisions/ADR-016-prove-it-against-the-real-thing.md) — real dependencies,
  mutation-testing guards, dogfooding, committed evidence
- [ADR-004](../decisions/ADR-004-behavior-adapters-and-execution-split.md) — adapters, and the
  runner/graph split
- [ADR-006](../decisions/ADR-006-real-interface-execution-and-coverage.md) — the execution
  contract and coverage provenance
- [ADR-019](../decisions/ADR-019-the-floor-and-choosing-a-backend.md) — the machine-level backend
  default that `FREYA_HOME` isolates

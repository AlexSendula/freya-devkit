# Testing

> Re-measured 2026-08-24 against the working tree at `9b7a3bc`, on macOS with CPython 3.12.5 and
> pytest 9.0.1. Every number below is reproducible with the command printed beside it — and
> several of them moved by 20–40% in the three days since the previous pass, so run the command
> rather than quoting the page.

## Overview

There is one suite. It is stdlib `unittest`, it lives beside the code it covers, and it is
normally run with pytest. There is no second tier of "integration tests", no e2e harness, no
fixture framework and no coverage tool — the project has no database, no HTTP surface and no
container, so the template sections for those are absent rather than empty.

Four gates guard a commit and none of them substitutes for another: the suite,
`bin/check_skill_conformance.py` (the shipped skill layer, fourteen rules),
`bin/check_doc_citations.py` (every `path:line` in the prose) and `bin/check_invariants.py`
(stdlib-only, and no `subprocess` call with a bare-name argv[0]). All four run in CI.

**Know what the third and fourth gates do *not* see, because both blind spots have cost this
repository real drift.** `check_doc_citations` reports three things — a missing file (C1), a
line past end-of-file (C2), and a blank line (C3), all three declared at
`bin/check_doc_citations.py:56` — so a citation that drifts
onto the *wrong non-blank line* stays green. Recorded in this branch's own commit log at
`1c4adcd`: one wave moved 374 citations and the gate saw 56 of them. And INV-2 sees only a
literal bare name in argv[0], so routing a spawn through `exec_path.resolve` makes that site
structurally invisible to it forever; ADR-030 records that cost, and it is why the converted
sites were **deleted** from `KNOWN_BARE_BINARIES` rather than left in it as cover. Diffed
against `main` on 2026-08-24: the map lost `bin/updater.py` and
`skills/freya-code-graph/scripts/backend_graphify.py` outright — three entries, since the
latter carried a `graphify` count as well as a `git` one — and shrank from nine files to seven.

A fifth, `freya verify-links`, is not in CI — it runs at wrap-up, because it checks the
spec corpus against the tests rather than checking the code.

## The stack

| Tool | Role |
|---|---|
| `unittest` (stdlib) | How every test is written — 37 files, `unittest.TestCase` throughout. No pytest fixtures, no `assert` rewriting. |
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
against any single `skills/*/scripts/` directory — measured 2026-08-24: `Ran 652 tests` in
`bin/`, `Ran 323 tests` in `skills/freya-spec-manager/scripts/`, both `OK`. What it loses is the
root `conftest.py`, which unittest does not know about; see "conftest.py" below for why that
matters less than it used to.

## What the suite is, measured

`python3 -m pytest -q` from the repo root on 2026-08-24, on the working tree at `9b7a3bc`:

```
2089 passed, 1345 subtests passed in 42.44s
```

Broken down by area (`python3 -m pytest <dir> -q` in each, same session):

| Area | Tests | Subtests | Wall clock |
|---|---:|---:|---:|
| `bin/` | 652 | 111 | 15.3s |
| `skills/freya-code-graph/` | 502 | 656 | 17.0s |
| `skills/freya-spec-manager/` | 323 | 106 | 6.3s |
| `skills/freya-codebase-security-scan/` | 269 | 138 | 1.4s |
| `skills/freya-docs-manager/` | 161 | 282 | 0.2s |
| `skills/freya-behavior-runner/` | 90 | 36 | 0.5s |
| `skills/freya-behavior-graph/` | 63 | 16 | 0.1s |
| `skills/freya-status/` | 29 | 0 | 0.1s |

The eight rows sum to exactly the whole-suite figures, 2089 and 1345, which is the check worth
doing: an area that does not add up is a test file pytest is not collecting. The per-area runs
total ~41s against the whole suite's 42s, so there is no shared setup cost hiding anywhere.

`bin/` and `freya-code-graph/` are 32s of the 41s, and almost all of that is real subprocesses:
`git` against real repositories, the launcher run end to end, and the `graphify` binary when it
is installed. The other six areas together finish in under nine seconds, so
`python3 -m pytest skills/freya-spec-manager -q` while iterating costs nothing.

The **1,345 subtests** are `self.subTest(...)` loops — 157 call sites across 26 files, counted by
AST and reproducible as `grep -rn '\.subTest(' bin skills --include='test_*.py' | wc -l`. Count
the calls, not the word: dropping the `\.` and the `(` from that pattern reads 162 over the same
files, because five of the hits are prose about subtests rather than a call. pytest
reports each iteration's outcome separately from the 2,089 test items; `unittest` reports only
the enclosing test methods, so the two runners give different totals for the same work and
neither double-counts.

That ratio is deliberate and it moved sharply on 2026-08-21, from 52 subtests to 1,012, and has
grown with the tree since. Most of this repo's registries were tested by naming three or four
members by hand — `RELATIONS` declared 32 relation kinds and its test file named twelve;
`CODE_EXTENSIONS` declared twenty and named none — so a member added later was covered by
nothing and nobody found out. Those tables are now driven off the registry itself, which is why
the subtest count is larger than the test count.

One trap is worth recording, because the obvious form of that table is silently broken: a
plain `for member in REGISTRY` loop cannot detect a **deletion**. Empty the registry and the
loop body never runs, so the test passes. Every table here iterates
`set(registry) | set(literal_expectations)` instead, which fails in both directions — a member
added upstream is red until somebody records what it must do, and a member removed is red
because the recorded behaviour stops happening. Measured, not assumed: dropping one row from
`RELATIONS` stayed green until the union fixed it.

**How the number moves.** Remove `graphify` from `PATH` and the same command gives
`2075 passed, 14 skipped, 1342 subtests passed` — measured 2026-08-24 by re-running with the
`graphify` directory stripped out of `PATH`. The fourteen are guarded by
`unittest.skipUnless(HAVE_GRAPHIFY, ...)`
(`skills/freya-code-graph/scripts/test_backend_graphify.py:33`). That is the shape CI runs in,
since the runner installs nothing but pytest. Measure against a clean export
(`git archive HEAD | tar -x -C …`) if you want a number tied to a commit rather than to whatever
is currently in your working tree — but note that an export carries no `.git`, and
`bin/test_check_doc_citations.py`'s two whole-repository tests go red without one, because the
citation gate reads git history for its exemptions. Two failures there are the export, not the
tree.

## Where tests live

Beside the code they test, never in a separate tree:

```
bin/installer.py                                  ← bin/test_installer.py
bin/check_skill_conformance.py                    ← bin/test_check_skill_conformance.py
skills/freya-code-graph/scripts/graph_ops.py      ← .../test_graph_ops.py
skills/freya-spec-manager/scripts/frontmatter.py  ← .../test_frontmatter.py
```

37 files in total: 9 under `bin/`, 28 under `skills/*/scripts/`. Three consequences of that
layout are worth knowing before you add a file.

**There are no packages.** No `__init__.py` exists anywhere in `bin/` or `skills/`, so pytest
imports each test module under its default `prepend` mode with the file's directory on
`sys.path`. Test-file **basenames must therefore stay unique across the whole repo** — two
`test_utils.py` in different skills would collide at import. All 37 names are currently
distinct, checked 2026-08-24 with `basename | sort | uniq -d`.

**A test imports its subject by bare name, from the subject's own directory.** 23 of the 37 make
that explicit with one line:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

Twenty-five call `sys.path.insert` at all; the two extras are not this idiom — they put a
*sibling skill's* `scripts/` on the path and leave their own subject to pytest
(`bin/test_workflow_pins.py:60`, `skills/freya-codebase-security-scan/scripts/test_findings_index.py:19`–`:20`).
The other fourteen simply write `import installer` or `import audit_io` and rely on pytest's
`prepend` mode putting the test file's own directory on `sys.path` — which is also what
`unittest discover -s <dir>` and a direct `python3 bin/test_installer.py` do. Both work; the
explicit form is the safer default for a new file.

This is not boilerplate that could be hoisted into a conftest. There is no packaged cross-skill
import path in the shipped layout, so a skill that needs another skill's Python either shells out
to it or puts that skill's `scripts/` on `sys.path` by relative path first. ADR-004 states the
first half as the rule — "cross-skill access is a subprocess call against the suite root, not a
Python import" — and the shipped tree now contains **nine** such imports, all intra-store and
all resolved the same way, by a `parents[2]` constant and a `sys.path.insert` beside it:

| Importer | Reaches into | For |
|---|---|---|
| `skills/freya-behavior-runner/scripts/run_behaviors.py:26` | `freya-spec-manager` | `frontmatter` |
| `skills/freya-behavior-graph/scripts/behavior_graph.py:20` | `freya-spec-manager` | `frontmatter`, `adapters` |
| `skills/freya-behavior-graph/scripts/behavior_graph.py:30` | `freya-code-graph` | `containment` |
| `skills/freya-behavior-graph/scripts/behavior_graph.py:37` | `freya-behavior-runner` | `load_behaviors` |
| `skills/freya-status/scripts/collect_status.py:20` | `freya-spec-manager` | `frontmatter` |
| `skills/freya-spec-manager/scripts/verify_links.py:41` | `freya-code-graph` | `containment` |
| `skills/freya-codebase-security-scan/scripts/audit_adapter.py:51` | `freya-code-graph` | `containment`, `exec_path` |
| `skills/freya-behavior-runner/scripts/run_behaviors.py:36` | `freya-code-graph` | `containment` |
| `skills/freya-spec-manager/scripts/project_shape.py:30` | `freya-code-graph` | `substrate.IMPORT_SIGNALS` |

Five of the nine are new, and all three import a **shared primitive** rather than a feature:
one body of the containment rule and one body of the program-resolution rule, placed in
`freya-code-graph/scripts/` by ADR-030 because that is the only location that survives every
install mode. `verify_links.py` used to carry its own copy of `escapes` with a docstring
claiming the two were "deliberately identical" and nothing holding them to it, which is the
duplicate-security-predicate shape ADR-002 forbids. The two `freya-code-graph` importers that
can be reached on a damaged tree guard the import and refuse rather than falling back —
`audit_adapter.py:52`, and `bin/updater.py:75` outside `skills/`.

**`unittest.main()` goes at the very bottom of the file.** 36 of the 37 carry it on their last
non-empty line — 19 spelled `unittest.main()` and 17 `unittest.main(verbosity=2)` — and those 36
can be run as `python3 <file>`. The exception is `bin/test_agents_md.py`, which has no call and so
runs only under the suite. (An earlier draft of this paragraph said 19 of 37, which counted the
bare-parens spelling and read as a statement about the whole convention.) The placement is load-bearing and was learned by
losing tests: in `bin/test_check_skill_conformance.py` the call once sat mid-file, so running
the file directly executed it before the last class was defined and silently skipped five tests
— every R10 case, including the regression guard for the defect R10 exists for. Measured
2026-08-24, that file now reports the same total both ways: `python3
bin/test_check_skill_conformance.py` gives `Ran 139 tests … OK` and `pytest --collect-only`
gives `139 tests collected` (`bin/test_check_skill_conformance.py:1157`). The figures this page
carried before — 86 reported against 91 collected — were the *symptom*, recorded while the call
was still misplaced.

## conftest.py — what the session isolates

The repository root holds a single `conftest.py` (27 lines). It does one thing: point
`FREYA_HOME` at a fresh throwaway directory before collection begins
(`conftest.py:26`, `conftest.py:27`).

The reason is that `settings.load()` consults a machine-level default at
`~/.freya/settings.json` — the graph backend the engineer chose once at install time
(`skills/freya-code-graph/scripts/settings.py:92`, ADR-019). Backend selection reads it, and
every graph build reads backend selection. Without the sandbox, the answer to "does a project
with no settings resolve to the floor?" depends on whose laptop is running the tests. A suite
whose result depends on unversioned state outside the checkout is not a regression gate.

It is claimed at module scope rather than in a fixture so that a module reading settings at
**import** time is covered too.

**Know its one hole.** A `conftest.py` is only collected when pytest's rootdir is at or above it,
so `cd skills && python3 -m pytest .` routes around it entirely. That hole was once expensive —
ten tests failed that way against a real `~/.freya/settings.json`. It is currently harmless, and
that is a property of the tests, not of the net: re-measured 2026-08-24,
`cd skills && FREYA_HOME=<dir containing a graphify-selecting settings.json> python3 -m pytest .`
gives `1437 passed, 1234 subtests passed`, and the same command with no `FREYA_HOME` at all
gives the identical `1437 passed, 1234 subtests passed`. The tests that depend on the machine
default now isolate themselves. The figures are dated because they move with the suite; what
does not move is that the two runs agree, and that agreement is the property being asserted —
run both, not one.

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

- A shared base class, where several test classes need it: `MachineHome` in
  `skills/freya-code-graph/scripts/test_substrate.py`, inherited by
  `TestSettings`, `TestTheMachineLevelDefault` and `TestBackendSelection`. Its docstring is the
  canonical statement of the rule.
- A per-file `Base.setUp`: `bin/test_backend_setup.py:26`.
- A single class that needs it: `TestRecordingTheBackendChoice` in
  `skills/freya-code-graph/scripts/test_graph_ops.py`, and the `FREYA_HOME` case in
  `skills/freya-behavior-runner/scripts/test_run_behaviors.py`.

Restoration is `addCleanup` everywhere except `test_run_behaviors.py`, which restores in
`tearDown`; either way it restores the *previous* value rather than deleting the variable,
because the session-level sandbox has already set it.

**A subprocess does not inherit an isolation you only applied in-process if you also pass a
trimmed `env`.** Tests that shell out build it explicitly:
`env=dict(os.environ, FREYA_HOME=self.home)`
(`skills/freya-code-graph/scripts/test_graph_ops.py:1989`,
`skills/freya-code-graph/scripts/test_graph_ops.py:2480`). The second of those carries the
measurement that justifies it: on a machine that answered the install question with `graphify`,
every fixture builds with a backend that reads `.java`, the census correctly reports nothing, and
six assertions about twelve unmapped files fail — green here, red on a colleague's laptop
(`skills/freya-code-graph/scripts/test_graph_ops.py:2467`).

Writing the isolation where the test is, rather than only in `conftest.py`, is also better
documentation: a test asserting "with nothing configured" should say so at the point it asserts it.

## Vacuous tests, and the mutation check

The second convention this repo learned the hard way, and the single most valuable one on this
page.

**Break the code a new test claims to cover and confirm the test goes red.** Write it, run it
green, edit the source to break the behaviour, run it again and watch it fail, restore the
source, then `git diff` to prove the restore was exact. Two lines of work, and it is the only
evidence that the test does anything at all.

It is not a formality. **Six tests in this suite were found green-and-vacuous in the week to
2026-08-21**, every one of them by that check, and each repair records the mutation it failed in
the test's own docstring. Three shapes account for five, and all three are recognisable on
sight.

**1. The fixture never reaches the line.** Something upstream — an exclusion list, an extension
filter, a regex that does not match, an unmocked environment — discards the fixture before
execution arrives at the guard.

- **The path-traversal check in the security scan**, and the worst of the six because it was the
  only test on it. `resolve_spec_reference` refuses a cited document that resolves outside the
  project (`skills/freya-codebase-security-scan/scripts/audit_engine.py:196`); the test fed it
  `../../../../../../etc/passwd`, which carries neither a prose suffix nor a `SPEC-NNN`-shaped
  token, so `_CITED_PATH` (`skills/freya-codebase-security-scan/scripts/audit_engine.py:125`)
  matched nothing and the containment check was never consulted. Measured: with the guard
  replaced by `if False:`, all nine tests in the class still passed. That guard is the only thing
  between a skeptic and downgrading a real finding by citing a spec in somebody else's
  repository.
- **The docs-graph link filter.** The fixture linked to `./other.md` with only
  `src/graph_ops.py` in the code-file set, so the link was excluded twice over — by
  `_is_code_path` (`skills/freya-docs-manager/scripts/docs_graph.py:237`) and then again by set
  membership. Deleting the guard the test names left all 36 tests in the file green. The repair
  puts the link target *in* the set, leaving `_is_code_path` the only thing that can keep it out.
- **The `freya doctor` PATH row.** `test_path_check_is_warn_not_fail_when_absent` never mocked
  `shutil.which`, so it ran against the ambient PATH, found the installed launcher and never
  entered the absent branch (`bin/freya_cli.py:346`). Turning that branch into a hard `fail` left
  it green — and so did turning it into `ok`, because `statuses <= {"ok", "warn"}` cannot tell a
  warning from silent approval.

**2. The assertion matches something else.** A substring that occurs in two different messages
proves nothing about which one fired.

- `test_accepted_still_requires_adapter` asserted that some error contained `adapter`. The
  fixture record carried no locator either, so two errors came back and both contained it: the
  locator message quotes it verbatim as `required for accepted adapter 'None'`
  (`skills/freya-spec-manager/scripts/frontmatter.py:372`). Deleting the adapter rule outright
  (`skills/freya-spec-manager/scripts/frontmatter.py:360`) left the assertion green. The repair
  supplies a valid locator, so the adapter rule is the only one that can fire, and pins the
  message rather than a word from it.

**3. The assertion is satisfied by a copy.** The structure under test mirrors the value
somewhere else, so removing the original leaves a second one for the assertion to find.

- `test_an_out_of_vocabulary_kind_is_validated_rather_than_raised` asserted
  `any('mixes_in' in e ...)` over the validator's errors. `link_dependents` mirrors the offending
  kind into the target's `dependents`, where the reverse-edge half of the validator reports it a
  second time (`skills/freya-code-graph/scripts/substrate.py:820`) — so replacing the
  forward-edge vocabulary check (`skills/freya-code-graph/scripts/substrate.py:768`) with
  `if False:` left this test and the other 139 in the file green. The repair asserts the whole
  forward-edge message, which the mirrored copy does not produce.

**The sixth is a cheaper failure, and a fourth shape: the table-driven test that stops early.**
A bare `for` loop over an allow-list aborts on the first member that fails, so the members after
it are never measured at all. `test_all_states_valid` iterated the four members of `ADR_STATES`
(`skills/freya-spec-manager/scripts/frontmatter.py:62`) that way; a rule honouring only the
first two reported one failure and left the fourth unmeasured. `self.subTest` per member fixes
it, plus one assertion that the table is not empty — an allow-list that became empty would
otherwise make the loop pass by iterating nothing.

**A test the exclusion lists prune is the commonest of these by a distance**, which is why
fixtures must not be planted under `docs/`, `scripts/`, `node_modules`, `dist`, `build`,
`vendor` or `knowledge-base` unless pruning is itself the subject. The worked example is the
unmapped-source census.
`substrate.CENSUS_PRUNE` (`skills/freya-code-graph/scripts/substrate.py:907`) is a set of
directory names — `node_modules`, `dist`, `build`, `vendor`, `target` and others — that the walk
prunes *before* it calls `_should_exclude`
(`skills/freya-code-graph/scripts/graph_ops.py:2753`). An earlier version of
`test_it_honours_the_build_s_own_exclusions` built its fixture under `node_modules/` and `dist/`.
The assertion passed. It would also have passed with `_should_exclude` deleted, because no
fixture file ever reached it (`skills/freya-code-graph/scripts/test_graph_ops.py:2075`). The fix
was to rebuild the fixture out of paths only `_should_exclude` rejects, and to add a separate
test pinning that the prune list and the scope rule *both* apply
(`skills/freya-code-graph/scripts/test_graph_ops.py:2091`).

Two older findings sit in the same three shapes:

- The dotfile guard — shape 1. The fixture used `.env.local` and `.eslintrc.json`, whose
  extensions are in neither tier list, so every file was dropped by the extension check before
  the guard ran (`skills/freya-code-graph/scripts/test_graph_ops.py:2114`).
- The graph contract's reverse-edge validator — shape 3, and the neighbour of the `mixes_in`
  case above: two `dependents` checks that could be deleted with the whole suite still green
  (`skills/freya-code-graph/scripts/test_substrate.py:331`).

Worked, measured, on this checkout — this is the whole ritual:

```bash
# delete the two-line dotfile guard at graph_ops.py:2755-2695, then:
python3 -m pytest skills/freya-code-graph/scripts/test_graph_ops.py -q
# → 1 failed, 163 passed      (at f407251 — the total moves as the file grows; the 1 does not)
#   FAILED ...::TestUnmappedSourceWalk::test_dotfiles_and_extensionless_files_are_skipped
# restore, re-run → 164 passed
git diff --stat skills/freya-code-graph/scripts/graph_ops.py   # must print nothing
```

That last line is not optional either. A mutation restored by hand rather than by `git`
is how a deliberate break reaches a commit.

Weak assertions fail this check even when the fixture is right. The graphify edge-translation
gate is the measured case: pinning `(from, to)` pairs alone, it caught **one of six** deliberate
mapping mutations, because the fixture carried each pair on several relations and dropping one
changed nothing the assertion could see. Pinning `(from, to, kind)` over a fixture that exercises
each guard is what made it bite (`skills/freya-code-graph/scripts/test_backend_graphify.py:1046`).

**The check also tells you when a fix is two changes and only one of them works.** That is the
more uncomfortable result and the one worth having an example of.
`ImpactArgvCase` (`skills/freya-spec-manager/scripts/test_drift.py:137`) covers a filename
`git diff --name-only` will happily print — `--build` is legal on every platform this runs on,
and `git add -- --build` is all it takes to commit one. Passed bare into the code-graph child's
argv it was read as a flag, the child exited rc=2, the `CalledProcessError` was swallowed a
frame up, and `compute_impact` returned `changed-only`: every dependent silently out of the
blast radius, and the run reporting success. Two changes went in — spelling each path `./<path>`
so argparse cannot mistake it for a flag, and moving `--impact` last so its `nargs='+'` has
nothing left to swallow. **Measured, only the first is load-bearing**: reverting the reorder
alone leaves both tests green, while dropping the `./` turns one red with or without the
reorder. The security report that raised this says both halves are required; the docstring says
what the mutation says instead (`skills/freya-spec-manager/scripts/test_drift.py:156`). Neither
half is asserted through argv shape, because an `assertLess(argv.index(...), ...)` passes with
either one missing — which is exactly how the defect survived review the first time
(`skills/freya-spec-manager/scripts/test_drift.py:161`).

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
HAS_GIT = shutil.which("git") is not None          # bin/test_updater.py:18
@unittest.skipUnless(HAS_GIT, "git is not installed")   # bin/test_updater.py:51
```

`skills/freya-code-graph/scripts/test_backend_graphify.py:33` does the same for the `graphify`
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
  (`skills/freya-behavior-graph/scripts/behavior_graph.py:215`) — the seam ADR-004 exists to
  preserve. It also imports `run_behaviors` directly for `load_behaviors`
  (`skills/freya-behavior-graph/scripts/behavior_graph.py:38`), but that path only reads specs
  and runs no tests, so it is left unpatched.

## The conformance gate

The second gate. Its scope, its **fourteen** rules and its output are
[DEVELOPER.md § The conformance gate](DEVELOPER.md#the-conformance-gate); what belongs here is
its relationship to the suite. R14 is the newest and the only one that is not about agent
neutrality — it requires a skill that sends a worker at secret-bearing material to state the
redaction rule, and to restate it in the copied-source slot rather than only in prose elsewhere
(`bin/check_skill_conformance.py:50`).

It has its own test file — 139 tests, the largest in `bin/` — which builds fixture trees per
rule, plus one test that runs the real scan over the real tree:
`ShippedTreeTest` (`bin/test_check_skill_conformance.py:919`).

**A claim this page used to chase in two places has now been retracted at both of them, and the
measurement is worth keeping anyway.** Re-measured 2026-08-24 on a full copy of this working
tree — `.git` included, because without it two unrelated citation tests go red — appending a
`${CLAUDE_PLUGIN_ROOT}` line to `skills/freya-wrap-up/SKILL.md` and running
`python3 -m pytest bin/ skills/ -q` gives `1 failed, 2088 passed, 1345 subtests passed`, the
failure being `ShippedTreeTest::test_the_shipped_skill_layer_is_conformant`, and the standalone
gate exits 1 naming the appended line and rule R1 on its own output line. The same happens for
an R2 violation. `ShippedTreeTest` calls `csc.scan(root)` with no rule filter
(`bin/check_skill_conformance.py:491`), so it catches everything the standalone gate catches.

Both original sites are now correct, and this page is the record of what they used to say.
`.github/workflows/ci.yml:84`–`:91` carries the retraction in its own words — "This comment
previously claimed the suite passes with a shipped R1 violation live; it does not, and has not
since ShippedTreeTest landed" — and `CONTRIBUTING.md:142` is now just
`python3 bin/check_skill_conformance.py   # the skill layer, R1–R14`, with no claim attached at
all. Do not quote either as a live defect. One stale detail does survive: `ci.yml:85` cites
`bin/test_check_skill_conformance.py:928` for `ShippedTreeTest`, and the class is at `:919`.

What is still true, and is the reason to keep running both:

- The gate runs **without pytest installed**, and is what CONTRIBUTING asks a contributor to run
  before committing.
- `--root` points it at a different checkout — an installed tree, for instance. `ShippedTreeTest`
  only ever scans its own.
- `pytest skills/` alone would miss it, since `ShippedTreeTest` lives in `bin/`. CI runs
  `pytest bin/ skills/`.
- CI keeps them as separate steps so a conformance failure is legible as one, rather than as a
  line in a test summary (`.github/workflows/ci.yml:86`).

**What R14 does and does not catch, measured rather than assumed.** It has two clauses. The
first is a presence check over the whole file — the sentinel plus a placeholder — and the second
requires the rule to appear *inside a copied-source slot*, because presence alone cannot tell a
rule from an echo of one. Measured 2026-08-23 on a tree copy and recorded beside the clause
(`bin/check_skill_conformance.py:466`): reverting the evidence block to a bare `{code snippet}`
now reports `skills/freya-codebase-security-scan/SKILL.md:871: R14`, while **deleting the whole
`### Redaction` section still exits 0**, because the sentinel inside the slot keeps the
file-level check satisfied. Counting surfaces is not something a presence gate can do. Do not
describe R14 as enforcing the redacted evidence block for the file as a whole; it pins one
slot.

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
(`.github/workflows/ci.yml:209`). The installer's `--target-dir` / `--bin-dir` hooks keep it off
the runner's real `~/.claude`.

**pytest is left unpinned on purpose.** pytest 9 requires 3.10+, and pip's `Requires-Python`
resolution is what hands the 3.9 legs of the matrix the 8.x line — so the runner differs
between legs by design. Why 3.9 is the floor at all is
[STYLE_GUIDE.md § Target CPython 3.9](STYLE_GUIDE.md#target-cpython-39).

**The one install the toolkit prints is pinned, and a test is what holds it.** That sits
directly opposite the paragraph above and is worth reading beside it. `graphifyy` is the only
third-party package this repository ever tells a person to install, and because INV-1 makes the
standard library the whole runtime there is no manifest, lockfile or dependency bot in the tree
— the install is prose inside `bin/backend_setup.py`'s install-time prompt, so the pin is prose
too. `TestTheInstallInstructionIsPinnedAndUnambiguous`
(`bin/test_backend_setup.py:203`) is the gate a manifest would have been. It renders the prompt
as a person on the floor sees it, **enumerates** every install command a regex over the install
verb can find in it (`bin/test_backend_setup.py:257`), and asserts each one equals
`graphifyy[sql,terraform]==0.9.47`. Enumerating rather than searching is the load-bearing part:
the failure to expect is not somebody deleting the pin, it is a second install line added
beside it, and any `assertIn` sails past that. Prose with no gate under it drifts, and this one
already had — the unpinned command resolved to 0.9.48 within two days of the reference
recording 0.9.47.

Two limits, both stated in that class's own docstring rather than hidden. It gates the copy in
`backend_setup.py` and nothing else, so `CHANGELOG.md:33` (a historical release note) and
anything else that prints the command are named there rather than checked
(`bin/test_backend_setup.py:214`). And the regex reads install *verbs*, not "however spelled":
measured 2026-08-23, `uv add`, `poetry add`, `conda install` and `easy_install graphifyy` all
pass it green (`bin/test_backend_setup.py:271`). A third test reads `freya_cli.MIN_PYTHON`
rather than asserting a literal, so raising the floor to 3.10 turns *that* test red instead of
leaving the prompt's `(or pip, on Python 3.10+)` caveat standing as noise
(`bin/test_backend_setup.py:292`).

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

## The behavior layer, and what this repo has of it

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
(`skills/freya-behavior-graph/scripts/behavior_graph.py:46`), with `OBSERVED_CONFIDENCE = 0.8`
against `STATIC_CONFIDENCE = 0.5` (`skills/freya-behavior-runner/scripts/run_behaviors.py`,
the constants at the top of the module).
ADR-006 names a third and higher tier, `explicit`, but marks it "reserved, unimplemented"
(`knowledge-base/decisions/ADR-006-real-interface-execution-and-coverage.md:24`) and no shipped
script mentions it. A behavior with no usable coverage is emitted `coverage: unknown` with a
reason, never as a silently empty result.

**This repo now defines 160 behaviors for itself, and every one of them is `proposed`.**
`spec-manager`'s brownfield scan was run on the toolkit on 2026-08-21 and wrote 30 spec files
under `knowledge-base/specs/`; the corpus has grown by hand since, 149 → 160 as of 2026-08-24.
Twenty-nine of the thirty specs carry behaviors; the thirtieth declares `behaviors: []`
deliberately, because `wrap-up` is prose with no engine and there is nothing for a locator to
bind to (`knowledge-base/specs/features/SPEC-030-wrap-up-orchestration.md:22`).

> **Corrected 2026-08-21.** This section previously opened *"This repo currently has zero
> behaviors defined for itself. There is no `knowledge-base/specs/` directory"*, and reported 65
> coverage gaps. Both were true when written and false the moment the scan committed. Two
> analyses had already quoted the sentence as evidence by then. A reference page that states a
> census is a page that goes stale on somebody else's commit; re-measure it before quoting it.

Re-measured over `knowledge-base/specs/` on 2026-08-24 — reproduce the first four rows with
`grep -rhoE '^ *<field>: *[a-z0-9]+' knowledge-base/specs | sort | uniq -c`, substituting
`state`, `adapter`, `level` and `entry`:

| | |
|---|---|
| state | 160 `proposed`, 0 confirmed, 0 accepted |
| adapter | 143 `unittest`, 17 `manual` |
| level | 105 `unit`, 28 `integration`, 25 `component`, 2 `e2e` |
| `entry:` | declared by 28 behaviors, naming 8 distinct source files |
| locator | 160 of 160 declared, resolving across 24 test files; `verify_links` exits 0 |

The two middle rows cross as **94 unit + `unittest`**, 26 integration + `unittest`, 23 component
+ `unittest`, with the 17 `manual` ones spread over the rest (11 unit, 2 integration, 2
component, 2 e2e). That first figure is the one that matters below.

Both spellings of that grep agree today — every one of the 160 `state:` lines is indented
exactly four spaces, checked 2026-08-24 — so the anchored form is a habit rather than a fix. It
is written that way because nothing enforces the indent, and a literal `    state: ` would
undercount in silence if one spec were ever written differently.

So the suite *is* traceable now — every `unittest` behavior names a real `path#Class.test_method`
— but nothing is executed through the layer, and two separate mechanisms are why:

- `project_behaviors` projects only `accepted` and `confirmed` behaviors into the graph
  (`skills/freya-behavior-graph/scripts/behavior_graph.py`, `project_behaviors`), so
  `behavior.json` still holds an empty `behaviors` map. That is the artifact being correct, not
  a build that needs re-running.
- the runner loads `states=("accepted",)` by default
  (`skills/freya-behavior-runner/scripts/run_behaviors.py`, `load_behaviors`), so it selects
  nothing here whatever adapters exist.

`freya status --project . --write-backlog` therefore records, on 2026-08-24, `160 proposed ·
0 confirmed · 0 accepted · 0 tests owed · 1 open findings · 28 coverage gaps`
(`knowledge-base/BACKLOG.md:5`) — the test-owed worklist is empty because only `confirmed`
reaches it (`skills/freya-status/scripts/collect_status.py:80`) and nothing is confirmed; all
160 sit in the intent worklist instead.

**The coverage-gap number on that line is no longer inflated.** It read 57 when this page was
written, against 24 real, because `gaps()` subtracted covered files from *every* file in the
graph and so counted every `test_*.py`, `conftest.py`, `install.sh`, `install.ps1` and the
extensionless `bin/freya` as files a behavior ought to cover. `gaps()` now filters through
`_is_coverable` (`skills/freya-behavior-graph/scripts/behavior_graph.py:380`), which drops test
files, extensionless scripts and languages no import system can address; roadmap item 15 is
struck as resolved by item 18. Read the current 28 as a worklist rather than as an upper bound.

`wrap-up`'s Phase 3.5 has changed shape as a result. Its **accepted-behavior run** still has
nothing to run and still cannot block. Its **integrity half** now has 160 locators to check
where it previously had none, and every one of them resolves —
`python3 skills/freya-spec-manager/scripts/verify_links.py` exits 0 with *"OK — all behavior
links pass Tier-1 integrity checks"*. That is the first time that gate has had anything to say
on this repository. Tier 1 is not the same check `behavior-graph --covering` makes, and the two
diverge in four measured ways — see
[SECURITY.md § A finding may be downgraded, never deleted](SECURITY.md#a-finding-may-be-downgraded-never-deleted).

**What the runner does with a Python behavior.** Until this batch the only implemented execution
path was `level: unit` with `adapter: vitest`. Of the 160 above, that would have left the 26 at
integration level with a static fingerprint from their `entry` and everything else — the 94 unit
and 23 component `unittest` behaviors included — falling through to `reason="level-deferred"`:
unknown coverage, never run. P4c's `pytest` adapter lands in this same batch and routes `pytest`
and `unittest` at unit level to a real execution path
(`skills/freya-behavior-runner/scripts/run_behaviors.py`, `PYTEST_ADAPTERS` in
`fingerprint_behavior`), which is the shape those 94 were written against. It changes nothing
about today's output, because the state gate above runs first: the blocker on this repo is
confirmation, not the adapter. Both halves are recorded in [`roadmap.md`](../roadmap.md) § P4c,
including the note that the if-ladder should become a runner-adapter registry when a second
adapter arrives.

**The open question, and the TODO that used to stand here.** That TODO asked whether this repo
should author behaviors for its own user-visible commands or wait for the pytest adapter first.
**Closed 2026-08-21**: events overtook both branches in the same week — the scan authored the
corpus, and the adapter is landing — so neither is a decision anyone still has to make.

What is live is about *new* code rather than the corpus: **does a command written from here on
get a hand-authored behavior as it is built?** Today the answer is "on contact, by prompt" —
`wrap-up`'s validate-on-hit step reports the changed files no behavior covers and offers to
author one, skippable (`skills/freya-wrap-up/SKILL.md:209`) — rather than by rule. Making it a
rule is the thing to argue about, and the counter-pressure is the table above: 160 unconfirmed
behaviors is already more recorded intent than anyone has reviewed, and it grew by eleven in the
three days since the last count while the confirmed total stayed at zero. Adding to the pile
before confirming any of it is how a worklist turns into wallpaper.

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

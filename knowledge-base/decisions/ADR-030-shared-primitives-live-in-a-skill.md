---
id: ADR-030
title: Shared primitives live in a skill, and the two bootstrap copies are gated
status: accepted
created: 2026-08-23
updated: 2026-08-23
tags:
  - portability
  - security
  - code-graph
  - install
---
# ADR-030: Shared primitives live in a skill, and the two bootstrap copies are gated

## Decision

A primitive that more than one skill needs lives in `skills/freya-code-graph/scripts/`. It is
reached by the sibling pattern the suite already uses —
`Path(__file__).resolve().parents[2] / "freya-<skill>" / "scripts"` on `sys.path`, then a bare
import (`skills/freya-status/scripts/collect_status.py:17`) — and from `bin/` by the store
pattern `bin/backend_setup.py:56` already uses. It does not live in `bin/`, and it does not live
in a new non-skill directory such as `skills/_shared/`. Every shipped Python module stays inside
a `freya-*` directory so that it travels with a `--copy` install.

The first two primitives placed under that rule are
`skills/freya-code-graph/scripts/containment.py:41` — `escapes`, and `rel_within`, `within` and
`is_anchored` at `` `:67` ``, `` `:101` ``, `` `:145` `` — and
`skills/freya-code-graph/scripts/exec_path.py:84`, the binary resolver.

**What is in force as of this record, and what is not.** `containment.escapes` has a production
caller — `verify_links.py` imports it and its existing `LocatorEscapeCase` tests run against it —
and `containment.is_anchored` has a second body in `check_invariants.is_absolute` that the
invariant gate uses on every run.

- **`exec_path.py` is wired, and G2 is closed.** Amended 2026-08-23. The first draft of this
  record said the resolver had no production caller and that **root-cause group G2 of the
  2026-08-21 security report was therefore unmitigated**; both sentences are now false, and the
  change that falsified them is the one that adopted the resolver at all four sites. `SEC-002`
  is closed at both of `backend_graphify.py`'s spawns — the `graphify` argv
  (`skills/freya-code-graph/scripts/backend_graphify.py:434`) and the `git rev-parse` 300 lines
  below it (`skills/freya-code-graph/scripts/backend_graphify.py:743`), an unreported fourth
  instance in the file SEC-002 was filed against and the one of the four with no availability
  gate in front of it: the `graphify` spawn is reached only through `available()`, and nothing
  is consulted before this one runs. (Three of the four run with the scanned project as their
  working directory on POSIX as well as Windows — those two, and the agent CLI in `audit.py`,
  which threads `cwd=args.project` through `make_ask`. Only `bin/updater.py`'s git runs in the
  store, which is why the contrast that matters is with it and not among these three. An
  earlier draft of this bullet claimed the superlative for `:743` alone and was simply wrong.)
  `SEC-003` is closed in `audit_adapter.py`: argv[0] is
  now the absolute path `main()` resolved (`audit.py:program`), threaded through `make_ask` to
  every `build_argv`, and `_guard` refuses a non-absolute argv[0] on the way past. The unfiled
  third instance in `bin/updater.py` is closed at `git()`.

  **What is *not* closed, said next to what is, because the census dropping 11 → 8 reads as
  more than it is.** G2's *filed* instances are fixed; eight bare-`git` spawns remain, and
  seven of them run with a repository the operator merely named as their working directory.
  Measured on a hostile fixture on 2026-08-23: `graph_ops.py --build` against a repository
  holding a planted `git`, with `.` on `PATH`, still executed it —
  `skills/freya-code-graph/scripts/graph_ops.py:551`, one of the two allowlisted entries in
  that file. `graphify` was never executed and `backend_graphify`'s own `_git_commit`
  correctly returned None in the same run. So "a hostile clone cannot choose which binary we
  run" is now true of `graphify` and of the agent CLIs, and is not yet true of `git`.
- **The one user-visible regression the adoption buys, stated where it cannot be missed.** On
  Windows under CPython 3.9–3.11 the `NoDefaultCurrentDirectoryInExePath` opt-out is ignored, so
  `shutil.which` still returns the working-directory hit first and the absoluteness refusal is
  the *only* control. A hostile repository shipping `graphify.exe` or `claude.exe` at its root
  therefore gets a **refusal** on that leg — a denial of service — where before it got execution.
  That is the accepted trade, and it is the only user-visible *regression* in this branch. It is
  not the only user-visible change, and an earlier draft said so: `freya doctor` and
  `freya update` gained the `NO_RESOLVER` precondition, `doctor`'s `updates` row can now
  report a refusal instead of a repository fact, and `freya security` gained a per-CLI
  refusal-reason block and an `EXIT_NOTHING_TO_DO` path for `--agent <name>`. Those are
  improvements; the refusal is the one thing a user loses.
  On 3.12+ the opt-out removes the working-directory entry outright and the real binary on PATH
  is found normally.
- **The resolver is imported under a guard in two places, and the guard is a decision.**
  `freya_cli` imports `updater` inside `doctor_checks` (`bin/freya_cli.py:359`) and inside the
  `update` branch (`:592`), and neither import is wrapped — only `notify`'s is (`:560`). An
  unguarded `import exec_path` in `updater` therefore turns a missing skill tree into a
  `ModuleNotFoundError` raised out of `freya doctor` and `freya update`: a traceback from the two
  commands whose whole job is to diagnose and repair that state, which is the same argument this
  record makes for the two bootstrap copies below. Measured, not reasoned about: with
  `exec_path.py` moved aside, both commands died at `updater`'s import line while every other
  command survived on `notify`'s existing `except Exception`. So the import is guarded, and the
  resolver's absence is reported as its own precondition (`bin/updater.py:88`, returned first by
  `preconditions`) rather than guessed at.

  **`except Exception`, not `except ImportError`, and the width is the decision rather than a
  slip.** The state being guarded against is "the store's skill tree is damaged", and *absent*
  is only its tidiest spelling. A truncated `exec_path.py` — an interrupted checkout, a partial
  download, a bad merge — raises `SyntaxError`, which is not an `ImportError` and which
  `bin/freya_cli.py:618` does not catch either, so the narrow form let the traceback straight
  back out of `doctor` and `update`. Measured both halves on a scratch store on 2026-08-23:
  deleted file, and a one-line invalid `exec_path.py`. `bin/backend_setup.py:77` is the
  precedent and already reads this way. The `sys.path` insert in front of it is guarded on
  `isdir` and on absence for the same reason `bin/backend_setup.py` guards its own: this runs at
  import of a module nearly every `freya` command loads, and an unconditional prepend puts a
  possibly-nonexistent directory ahead of `bin/` for the life of the process.

  **A guard that survives is not enough: what it survives *into* has to be true.** `updater.git`
  returns `(1, "")` for a missing resolver and for a refused git exactly as it does for a real
  git failure, and `is_git_store` reads `(1, "")` as "not a repository" — so `doctor` answered
  *"the store is not a git checkout"* for a store that was one, on the one command that exists
  to explain this state, while `freya update` on the same machine printed the true reason. That
  is the default outcome on the Windows 3.9–3.11 leg, where a refusal is the expected result of
  a repository-local `git.exe`. Both callers now ask `updater.git_program`, one body returning
  `(path, reason)`, and `bin/freya_cli.py`'s `updates` row prints the reason ahead of
  interpreting any git answer as a fact about the repository. `DoctorCannotRunGitTest`
  (`bin/test_freya_cli.py:1104`) pins it, including that the two commands give the same reason.

  **There is no fallback to a bare name** — no degraded resolver and no third body of the
  absoluteness rule. A store either has the resolver or loses its git-backed features with a
  stated reason, because a fallback that searched `PATH` would reinstate the defect exactly when
  the tree is already damaged. `skills/freya-codebase-security-scan/scripts/audit_adapter.py:55`
  carries the same guard for the same reason and fails closed the same way — `program_for`
  returns a refusal, `detect` finds nothing, `_guard` refuses every argv — because a `--copy`
  install *skips* a skill whose target was occupied or foreign, so a security driver really can
  land in a tree with no `freya-code-graph`. Unguarded it was a raw traceback that exited 1 only
  because Python's uncaught-exception code happens to equal `EXIT_NOTHING_TO_DO`, a coincidence
  nothing recorded. The two imports are guarded identically on purpose: an asymmetry here would
  be two answers to one question about what a damaged tree does.

  A guarded import is the shape `knowledge-base/reference/STYLE_GUIDE.md:47` says must be an ADR
  rather than a bare `except`; this bullet is that ADR, and it covers both sites. Neither is an
  optional *dependency* — `exec_path.py` is first-party and ships in the same commit — both are
  bootstrap guards for a damaged store. That is also why INV-1 grows no carve-out for the shape:
  all four guarded imports in the tree (`bin/freya_cli.py:195`, `bin/updater.py:77`,
  `audit_adapter.py:55`, `run_behaviors.py:271`) wrap a first-party module, so the syntax is not
  evidence of an optional dependency and a rule keyed on it would exempt a future
  `try: import yaml` for free.
- **`containment.rel_within` has no caller either, not even `exec_path`.** Its intended first
  one is the graph-key path, and that path already has a local body of the same rule:
  `graph_ops.py:724` is `_contain`, which `rel_within` is meant to replace, and the
  `try: relative_to(self.project_dir) / except ValueError: continue` shape it also collapses
  survives at `:2017`–`:2024` and `:2079`–`:2080`, with unguarded `relative_to` calls at
  `:2089` and `:2181`. (An earlier draft of this bullet cited a backwards line range that
  pointed at neither.) A local body of a containment rule is exactly what the last paragraph of
  the Decision forbids without a `ContainmentParityTest` row, so the migration is owed rather
  than optional. It ships now because the four questions are argued together
  below and splitting the argument across two records would cost more than the unused function
  does; if that migration does not happen, delete it rather than let it drift from the sites it
  was measured against.

**`bin/` keeps exactly two copies, and both are gated.** `bin/freya_cli.py:55` keeps its own
`_escapes`, and `bin/check_invariants.py:364` keeps its own `is_absolute`, which is
`containment.is_anchored` under another name. Neither may import from the skill tree, because
both are the code that has to work when that tree is missing, half-installed or condemned:
`doctor` and `update` diagnose and repair it, and `load_manifest` is on the path of nearly every
`freya` invocation. Both copies are held to the canonical bodies by `ContainmentParityTest`
(`bin/test_freya_cli.py:1328`, asserting at `` `:1376` `` and `` `:1418` ``), which imports
`containment` with no `skipUnless` so that a missing canonical module is an error rather than a
skip. So: the `escapes` rule has two bodies and the anchoring rule has two, each pair pinned to
its canonical one. Before this change `escapes` also had two — `bin/freya_cli.py` and
`verify_links.py` — and nothing pinned either. A *third* body of either rule is a defect, and so
is a second body that arrives without a row in `ContainmentParityTest`.

Both halves live in that one class even though the second is about
`bin/check_invariants.py`, which has a test module of its own. That is deliberate and it does
bend the sibling-test convention (`knowledge-base/reference/STYLE_GUIDE.md:157`): the assertion
is not *about* `is_absolute`, it is about two modules still agreeing, and splitting it would give
each copy a test that passes while the pair diverges. The cost is that
`bin/test_check_invariants.py` reports green on a rewritten `is_absolute`, so its module
docstring says where the gate actually is.

**The accepted cost, and the rule it imposes on every later change.** Routing `argv[0]` through
`exec_path.resolve` makes INV-2 structurally blind to the sites that adopt it, because the rule
reads `argv[0]` at the call site. So when a spawn site starts going through the resolver, its
`KNOWN_BARE_BINARIES` entry (`bin/check_invariants.py:119`) is **deleted** in the same commit. It
is never left in place as cover.

## Rationale

**`bin/` is not reachable from the skill tree in the install mode most users get.** Measured on
2026-08-23 with a real install: `python3 bin/installer.py --agent claude --copy` into a throwaway
target copied ten `freya-*` directories and one launcher shim, and from the copied
`freya-code-graph/scripts/`, `resolve().parents[2]` is the copied `skills/` — siblings resolve,
the cross-skill pattern works — while `resolve().parents[3] / "bin"` does not exist. Under a
symlink install the same expression follows the link back into the store, where `bin/` is
present, so a skill importing from `bin/` would work on the developer's machine and fail on the
user's. Copy is not the exotic mode: it is the normal one on Windows, where symlinks need a
privileged process or Developer Mode.

**A non-skill directory under `skills/` would be the first shipped module a `--copy` install does
not carry.** `installer.discover_skills` (`bin/installer.py:131`) returns only directories whose
name starts with `SKILL_PREFIX` (`bin/installer.py:21`) *and* which contain a `SKILL.md`, and
`copy_into_place` (`bin/installer.py:399`) copies exactly what that returns. Verified against a
synthetic store on 2026-08-23: with `skills/_shared/` and `skills/freya-a/SKILL.md` both present,
`discover_skills` returned `['freya-a']`. The conformance gate would not have caught it —
`check_skill_conformance` globs `*.md` and `*.py` under `skills/` and never enumerates
directories — so a shared module placed there passes every gate in the repository and is simply
absent at the user's end. That is the worst available failure shape: green here, missing there.

**`freya-code-graph` rather than a new `freya-core` skill.** code-graph is the foundation tier —
it imports no other skill, and three others already reach *into* it: `freya-behavior-graph`
(`skills/freya-behavior-graph/scripts/behavior_graph.py:25`), `freya-behavior-runner`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:25`) and `freya-spec-manager`
(`skills/freya-spec-manager/scripts/drift.py:37`) each build a path to its `graph_ops.py` and
spawn it as a subprocess. None of the three is an *import* — this change adds the first one — but
all three already depend on that directory existing at that relative location, which is the
dependency direction the placement has to be safe in. `bin/backend_setup.py:56` reaches into the
same directory from the store side. A `freya-core` skill would be an eleventh
user-visible entry in every agent's skill list, carrying a `SKILL.md` describing something no
user ever invokes, and would sweep "ten skills" through a dozen documents. The direction of the
new edge is the one thing this decision has to hold: `freya-spec-manager` now imports
`containment` (`skills/freya-spec-manager/scripts/verify_links.py:42`), and code-graph must never
import back. A cycle between two skills would make both unloadable in exactly the install mode
this ADR exists to protect.

**The duplicate this retires was never a decision.** `verify_links.py` carried its own `_escapes`
whose docstring said it was "Deliberately identical to `bin/freya_cli.py:_escapes` — one
containment rule for the repo, not two that disagree at the margin (ADR-002)". Every part of that
sentence was aspiration. Checked on 2026-08-23: no ADR and no spec establishes the duplication;
`git log -S` on the docstring returns only the squashed release commit `2deb4ef`; and no test
anywhere compared the two functions — `test_verify_links.py` mentions `freya_cli._escapes` in
prose only. The two bodies were identical by luck. ADR-002 permits a *generated projection* and
forbids a *hand-maintained duplicate* — "two editable copies that drift" — and a security
predicate maintained by hand in two files, with a docstring asserting a parity nothing measured,
is precisely the second thing wearing the first thing's citation. The migration deleted that copy
and imported the canonical one; the existing `LocatorEscapeCase` tests passed unmodified, which
is what shows the behaviour is unchanged rather than merely re-asserted.

**Four functions, not one.** `containment.py` holds four predicates because there are four
questions, and the shape of the argument does not tell you which one is being asked. `escapes` is
lexical and refuses `..` outright, for a value *declared* in checked-in data. `rel_within`
normalises but deliberately does not resolve, because it produces the project-relative key that
`graph.json`, `behavior.json` and `docs.json` are joined on (ADR-025) — resolving would re-key a
legitimately symlinked in-project file to its realpath, and since the join is a set intersection
the file would stop matching rather than match wrongly, so a blast radius would come back quietly
short. `within` resolves both sides, because it decides whether something gets executed. And
`is_anchored` is not the negation of `escapes`: `escapes("C:x")` is True and `is_anchored("C:x")`
is False, because "may this be joined onto my root" and "does this stand on its own" are
different questions with a value that answers no to both.

**`is_anchored` is drive-and-root, not an `isabs` union, and that is a version fact.** Measured
over an eleven-case table on 3.9.6, 3.12.5 and 3.13.5: `posixpath.isabs(t) or ntpath.isabs(t)`
answers True for `\tools\git.exe` on the first two and False on the third, because `ntpath.isabs`
changed in 3.13 so a rooted path with no drive stopped being absolute; `os.path.isabs` is wrong
for every Windows spelling when the checker runs on Linux. The drive-and-root form gave identical
answers on all three. `bin/check_invariants.py:364` had the union behind a docstring promising
exactly the stability the union does not have; it now has the stable form and a parity test.

**Residual risk, stated because it sits one step from the scenario the fix is named for.**
Containment is scoped to the project the operator *named*, not to wherever the process happens
to be standing. Measured on 2026-08-23: from inside a hostile clone, with that clone's own
directory on `PATH` as an absolute entry, `audit.py scan --project <some other directory>`
resolves the clone's `claude`, passes both the absoluteness rule and containment — the hit is
not inside the named project — and would spawn it. The two neighbouring forms are both refused:
`--project .` refuses on containment (including when the `PATH` entry is outside the repository
and the file there is a symlink back into it), and the relative spelling of the same escape
(`.` on `PATH`) refuses on absoluteness. The realistic trigger is not an exotic `PATH`: it is an
activated in-repository `.venv/bin`, `direnv`, or `node_modules/.bin`.

This is a boundary, not an oversight — `exec_path.resolve` declines to forbid the process
working directory on purpose (`skills/freya-code-graph/scripts/exec_path.py:102`), because
`/usr/bin/git` is "inside" a working directory of `/` and the absoluteness rule already closes
every route by which the working directory *reaches* the answer. What it does not close is a
directory the operator deliberately put on `PATH` that happens to be inside a repository they do
not trust. If that is ever to be closed, the question to ask is "is the hit inside any
repository root at or above the invocation directory", not "is it inside `cwd`".

**The absoluteness rule in `exec_path` refuses, it does not repair.** The security report's
remediation asked for a resolved program to be "resolved to an absolute path". Running `abspath`
over a resolution that came from the working directory produces a fully-qualified path to the
attacker's binary — the same file, spelled more convincingly, and now past any later check that
only asks whether argv[0] looks absolute. So a non-absolute resolution is refused
(`skills/freya-code-graph/scripts/exec_path.py:125` onward), and `containment.is_anchored` is the
test, so the resolver and the tree-invariant checker cannot disagree about what absolute means.

**The cost of that resolver, in full, and it is paid — not deferred.** INV-2 only yields a site
when it can resolve a literal `argv[0]` at the call site (`bin/check_invariants.py:403`), so
`subprocess.run([exec_path.resolve(...).path, ...])` presents a call expression rather than a
constant and stops being counted. The checker's own docstring already records this shape as a
known blind spot (`bin/check_invariants.py:27`); adopting the resolver widens it deliberately.

Say it plainly, because the census going 11 → 8 is the kind of number that reads as progress and
hides this: **INV-2 is now structurally blind to the three fixed call sites, permanently** — the
`graphify` spawn and the `git rev-parse` in `backend_graphify.py`, and `git()` in
`bin/updater.py`. Not "watched more loosely" and not "pending a better rule" — the rule cannot
see a call expression and never will, so no future bare name reintroduced *in those same
statements* would be caught by it either. Those two files bought their safety by leaving the
only static gate that was looking at them.

The fourth adopting site, `audit_adapter._claude_argv`, is not part of that trade and must not
be counted into it: its bare `"claude"` was assembled in a helper and never appeared at a call
site, so it was never in the census to leave (`bin/check_invariants.py:91`). It gained a runtime
guard without losing a static one. What replaces the gate for the other two is not another gate:
it is
`audit_adapter._guard`, a runtime refusal on the one function every worker argv passes through,
and for the other two sites nothing but the resolver's own return value and the tests that pin
it. That asymmetry is the honest description of where this tree stands, and it is the reason
the entries are **deleted** rather than kept as cover. A deletion that reads as "fixed and still
watched" would be a lie about the second half.
What makes that survivable is that `apply_allowlist` (`bin/check_invariants.py:417`) is exact in
both directions: an allowlist entry with no site left to match is itself a violation, so a stale
entry is a red gate rather than a quiet one. Hence the deletion rule in the Decision. An entry
left behind after its site was fixed is worse than the original defect — it is a licence for the
next bare name in that file, dressed as a record of a debt that no longer exists.

## Rejected Alternatives

- **Canonical in `bin/`, imported by skills.** The obvious default: `bin/freya_cli.py:55` is where
  the rule was first written, `bin/` is where the launcher and installer already live, and it
  would need no new import pattern for the two `bin/` copies. Rejected on the measurement above —
  under `--copy` the skill tree has no `bin/` sibling, so every skill that imported from it would
  fail at import on the install mode Windows users get by default. It would also make `bin/` part
  of every skill's runtime, which reopens ADR-014's separation between the store and the payload
  for no gain.

- **A non-skill `skills/_shared/scripts/`.** Reads best: the directory name says what it is, and
  it needs no argument about why a containment predicate lives in the dependency-graph skill.
  Rejected because `discover_skills` cannot see it (`bin/installer.py:131`), so it would ship in
  the repository and be absent from every `--copy` install, with no gate reporting the difference.
  Making the installer copy it would mean teaching the installer about a second kind of
  directory, and the Agent Skills specification has nothing to say about what that directory is.

- **A new `freya-core` skill.** Fixes the installer problem properly and gives shared code an
  honest home. Rejected on cost-to-benefit: an eleventh user-visible skill in every agent's list,
  a `SKILL.md` for something nobody invokes, and a "ten skills" figure to correct across a dozen
  documents — bought for a directory rename. Revisit it when the shared surface outgrows one
  module pair (see below).

- **Keep duplicating the predicate per skill.** The status quo, and it has one real argument:
  every skill stays independently readable and nothing new goes on `sys.path`. It produced two
  ungated copies of a security predicate, one of them carrying a docstring that claimed a parity
  nothing enforced. Duplication is acceptable only where it is *forced* and *gated*, which is why
  the two `bin/` copies survive and no third one may.

- **Import `containment` from `bin/freya_cli.py` and `bin/check_invariants.py` too, and have no
  copies at all.** The cleanest rule to state. Rejected because it inverts the bootstrap: the
  launcher's manifest validation runs on nearly every invocation, including the `doctor` and
  `update` runs whose entire purpose is to report on a skill tree that is broken or absent, and
  the invariant checker may be looking at a tree it is about to fail. A diagnostic that cannot
  run when the thing it diagnoses is broken is not a diagnostic. The parity test is what makes
  the exception honest rather than convenient.

## Revisit Conditions

- **The shared surface outgrows `containment.py` + `exec_path.py`.** Two modules in a foundation
  skill is a placement; six would be a package living in someone else's house, and at that point
  `freya-core` stops being an eleventh skill bought for a rename and starts being the accurate
  description of what exists. Count the modules, not the lines.

- **Anything in `freya-code-graph` needs to import from a skill that imports it.** The moment a
  cycle is even proposed, this placement is wrong and the shared code has to move out from under
  code-graph rather than the cycle be broken by a local import.

- **The installer learns to ship a non-skill directory.** If `discover_skills`
  (`bin/installer.py:131`) ever grows a second category — a shared runtime, a data directory, a
  vendored anything — the `skills/_shared/` alternative becomes real and this decision should be
  re-argued rather than inherited.

- **A third body of a containment predicate appears.** `bin/test_freya_cli.py:1328` pins the two
  that exist. A third would need its own entry there in the same change, or this decision has
  quietly become "duplicate freely and say it is a bootstrap".

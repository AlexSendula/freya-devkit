# Security

> Last updated: 2026-08-24

The security posture of **freya-devkit itself**: what the toolkit executes on your machine,
what capability it hands the processes it spawns, what it refuses to do, and which of those
properties are enforced by tested code rather than by prose.

This is not a vulnerability report of a project the toolkit scanned. Those are written per
scan to `knowledge-base/security/codebase-security/YYYY-MM-DD.md` in the scanned project
(`skills/freya-codebase-security-scan/SKILL.md:824`), alongside a machine-readable
`findings.json` (`skills/freya-codebase-security-scan/references/findings-schema.md`).

**This repository now has one, and it is tracked.** `knowledge-base/security/` holds
`codebase-security/2026-08-21.md`, its `findings.json`, and the `.security-last-scan` tracking
file, all committed at `2deb4ef`. That report is the toolkit's own audit of itself, and most of
what this page has to say about resolvers, containment and redaction exists because of it. This
page states the *posture*; the report states the *findings* and their status. Where they
disagree, the report is dated and this page is not, so this page is the one to fix.

## What there is to attack

There is no service, no daemon, no listening port, no database, no container and no
credential store. A skill is a `SKILL.md` the agent reads plus stdlib Python the agent runs
through one launcher, `freya <command>` (`bin/freya_cli.py:145`, which execs the target with
`sys.executable`). Three properties were re-measured on 2026-08-24 rather than assumed:

- **No third-party runtime dependency, and no networking module.** An AST walk over every
  `.py` under `bin/` and `skills/`, collecting the top-level module of every `import` and
  `from … import`, returns 69 distinct names, all of them stdlib or a sibling module from this
  repository — and none of `socket`, `ssl`, `http` or `urllib` appears among them. `git
  ls-remote`, run by the update check, is the toolkit's only network access and it happens in a
  child process. pytest is the one thing ever installed, and only to run the tests
  (`CONTRIBUTING.md:131`). There is no lockfile to audit and no supply chain to compromise,
  which is also why `freya-dependency-vulnerability-check` has nothing to say about this repo —
  it scans the *target* project's manifests.
- **No shell.** No call anywhere in `bin/` or `skills/` passes a `shell=` keyword — checked by
  AST, not by grep, because grep now finds the string three times and every one is *about* the
  rule rather than an instance of it: the invariant checker's own comment
  (`bin/check_invariants.py:349`) and two fixtures in its test
  (`bin/test_check_invariants.py:351`, `:353`). Every subprocess is an argv list.
- **Two program names still reach an OS search: `git`, and `pnpm` from the behavior runner.**
  Eight `git` spawns name the binary bare and are carried in an explicit allowlist that CI turns
  red on a ninth *git* (`bin/check_invariants.py:119`). A ninth bare name exists anyway and it is
  `pnpm` (`skills/freya-behavior-runner/scripts/run_behaviors.py:228`, spawned at `run_behaviors.py:459`
  with `cwd` set to the project being analysed), and it is in **no** allowlist and in no INV-2
  report: the argv is assembled in a helper and passed by variable, so the checker's argv[0]
  reader resolves nothing and skips the site in silence (`bin/check_invariants.py:411`). Read
  INV-2's `8 violation(s)` as a census of the bare names the checker can see statically, not as a
  census of the tree. Everything else — `graphify`, `claude`, `copilot`, and two of the git
  sites — resolves through `exec_path.resolve` and is *refused* rather than searched. See below,
  and [ENVIRONMENT.md § `shutil.which` is no longer the answer on its
  own](ENVIRONMENT.md#shutilwhich-is-no-longer-the-answer-on-its-own).

What the toolkit does execute:

| What | Where | Notes |
|---|---|---|
| A bundled script, under the current interpreter | `bin/freya_cli.py:145` | argv is `[sys.executable, <script from bin/commands.json>, *args]`; no `python` need be on `PATH` |
| `git`, read-only queries | `skills/freya-status/scripts/collect_status.py:33`, `skills/freya-code-graph/scripts/graph_ops.py:551`, `skills/freya-spec-manager/scripts/verify_intent.py:87` | `rev-parse`, `diff --name-only` and similar; the graph and status layers never write git state. These are bare-`git` sites; the two resolved ones are `bin/updater.py:170` and `skills/freya-code-graph/scripts/backend_graphify.py:743` |
| `git fetch` and `git merge --ff-only` | `bin/updater.py:346`, `:360` | Only during `freya update`, which fast-forwards the checkout to its tracked branch (`CONTRIBUTING.md:222`) |
| An agent CLI as an audit worker | `skills/freya-codebase-security-scan/scripts/audit_adapter.py:123`, `:139` | The subject of most of this document. argv[0] is an absolute path or the worker does not start |
| The project's own test command | `skills/freya-behavior-runner/scripts/run_behaviors.py:228`, `:459` | `pnpm vitest run <test file>`. Running a project's tests is executing project-controlled code, by design and unavoidably. This is the one spawn that is neither resolved nor allowlisted, and the one bare name INV-2 cannot see |
| `graphify` | `skills/freya-code-graph/scripts/backend_graphify.py:434` | Only when the project selected that backend; the stdlib floor is the default (ADR-019). argv[0] is the resolved absolute path (`backend_graphify.py:430`) |

Environment variables, the `graphify` binary, and the fact that freya reads no API key of its
own are covered in [ENVIRONMENT.md](ENVIRONMENT.md) and not repeated here.

## The audit driver owns its fan-out

`freya security scan` and `freya security audit` are the same driver
(`bin/commands.json:18` → `skills/freya-codebase-security-scan/scripts/audit.py`), and it is
the one fan-out in the toolkit scheduled by code rather than described in prose. Why, and why
the other two fan-outs stay prose:
[ADR-015](../decisions/ADR-015-driver-owned-fan-out.md) and
[patterns.md § Coordinator + Independent Tasks](../patterns.md#pattern-coordinator--independent-tasks).

The control flow lives in Python: one context call, then the six category finders
(`skills/freya-codebase-security-scan/scripts/audit_io.py:20`) on a bounded thread pool
(`audit.py:290`), dedup by file + five-line window + category
(`skills/freya-codebase-security-scan/scripts/audit_engine.py:91`), then three adversarial
lenses per surviving finding (`audit_io.py:22`) and a majority vote
(`audit_engine.py:266`). Each agent call is a separate OS process. No agent gets a vote on
whether the fan-out happens.

The security consequence is what makes it belong in this document: because the driver spawns
the workers, the driver decides what the workers are allowed to do.

`scan` and `audit` are presets of one engine differing in exactly one parameter, discovery
rounds — 1 versus 5 (`audit.py:50`, `audit_engine.py:47`). Verification is never cut. With a
single lens any one refutation is unanimous, `disposition` reaches `upheld == 0`, and a real
vulnerability is dropped with no trace in the report (`audit_engine.py:312`).

## The read-only allowlist, and what it is not

Every worker argv is an explicit allowlist that excludes the shell:

| Adapter | argv fragment | Source |
|---|---|---|
| `claude` | `--allowedTools "Read Grep Glob" --disallowedTools "Write Edit Bash"` | `audit_adapter.py:131`, `:132` |
| `copilot` | `--allow-tool=read --deny-tool=write --deny-tool=shell` | `audit_adapter.py:143`, `:144` |

Four flags may never appear —
`--allow-all-tools`, `--allow-all`, `--allow-all-paths`, `--allow-all-urls`
(`audit_adapter.py:74`) — and `build_argv` raises `UnsafeInvocation` if any argv token *is* one
of them or starts with `<flag>=` (`audit_adapter.py:79`, `:83`, `:115`), which is what catches a
prompt that is itself a flag. A flag quoted inside a longer prompt does not raise, and does not
need to: the whole prompt is one argv element after `-p`, so the host CLI reads it as text.

**The allowlist is the load-bearing control; the deny flags are defence in depth only.** The
2026-07-27 spike against Copilot CLI 1.0.75 found that `--allow-all-tools --deny-tool=write`
was bypassed — a worker created a file through a shell redirect — because "deny beats allow"
applies to the write *tool*, not to writes performed *through* the shell tool. Only the
explicit allowlist held (ADR-015 § Rationale; the same finding is restated at the top of
`audit_adapter.py:7`).

Two mutants re-run against the shipped tests on 2026-08-24 confirm that ordering:

| Mutation | Result |
|---|---|
| Delete `--disallowedTools "Write Edit Bash"` from the Claude argv | `269 passed, 138 subtests passed` — the deny flags are not what the suite is holding |
| Delete `--allowedTools "Read Grep Glob"` from the Claude argv | `1 failed, 268 passed` — `ReadOnlyTest::test_claude_restricts_tools_to_read_only` |

Method, and it has changed: copy the **whole checkout** to a temporary directory, remove the
line, and run `python3 -m pytest skills/freya-codebase-security-scan -q` there. Copying only
`skills/freya-codebase-security-scan/scripts/` no longer works — `test_findings_index.py` imports
`behavior_graph` out of a sibling skill, so a scripts-only copy dies at collection with
`ModuleNotFoundError` before a single assertion runs. Measured 2026-08-24, that exits **2**, not
0: the hazard is the opposite of a green mutant, since a non-zero exit from a copy that never
collected reads exactly like a mutant the suite killed. Read the summary line, not the exit code. Four of those 269 tests are the read-only guard itself,
`ReadOnlyTest` (`skills/freya-codebase-security-scan/scripts/test_audit_adapter.py:58`–`:88`).

**What the boundary is not.** It is a *tool* restriction, not a filesystem jail and not a
process sandbox. A worker runs with `cwd` set to the project (`audit.py:252`), but no argv
element confines its reads to that directory — whether the host CLI applies a directory
boundary of its own is host behaviour nothing here tests. No `env=` is passed to `subprocess.run`
(`audit.py:240`), so each worker inherits the parent environment whole — including anything
credential-shaped in it. The no-writes evidence collected so far is scoped to the fixture or
repository under audit (checksums plus `git status --porcelain` before and after) and could
not have seen a write to `$HOME` or `/tmp` (ADR-015 § Revisit Conditions). The prompt is
passed as an argv element (`audit_adapter.py:129`, `:141`), so it is visible in a process
listing to any local user who can see the process.

**And it says nothing at all about which binary is started.** That is a separate property, it
was missing, and it is the finding this branch closed. SPEC-025 and ADR-015 both frame the
read-only controls as constraining what a worker may *do*; a repository that committed
`claude.exe` at its root got a worker that did exactly what the allowlist permitted, in a
process that was never the operator's `claude`. On Windows `CreateProcess` searches the parent
process's working directory before `PATH` — and this driver runs with `cwd` set to the scanned
project — while CPython's `shutil.which` inserts the working directory at the head of its own
search. So the allowlist held perfectly and the attacker chose the program it was applied to.

`_guard` now refuses any argv whose first element is not an absolute path, before it checks for
a blanket flag (`audit_adapter.py:107`). It is enforced there rather than by INV-2 because the
argv is assembled in a helper and handed to `subprocess.run` as an expression, which the static
rule cannot read — the checker's own docstring records that blind spot, and `Argv0Test`
(`skills/freya-codebase-security-scan/scripts/test_audit_adapter.py:127`) is the runtime
substitute. Seven cases are pinned there, including that a *forgotten* `program=` is reported
as `None` rather than as the bare binary name, because restoring a `program or "claude"`
fallback would otherwise be invisible to every other test in the file
(`test_audit_adapter.py:164`).

The guard is also version-specific by nature: it encodes what one release of two vendor CLIs
did. Re-probe it on every agent-CLI version bump. **The adversarial probe has never been
run** — the guard has held in every observed run, including an audit of a real 299-file
repository that left `git status --porcelain` and HEAD identical before and after
(ADR-015 § Rationale), but nothing has actively tried to defeat it
([roadmap.md § Platform-blocked](../roadmap.md#platform-blocked)).

## What a worker can and cannot do

| Can | Cannot |
|---|---|
| Read, grep and glob files | Write, edit or create files |
| Read files by absolute path — the argv sets no path boundary | Run a shell command, hence no shell redirect |
| Return a JSON object on stdout | Be granted a blanket permission flag, even via the prompt (`audit_adapter.py:83`) |
| Take up to `--timeout` seconds, 600 by default (`audit.py:41`) | Ask a question — Copilot workers run `--no-ask-user` (`audit_adapter.py:142`) and there is no tty |
| Fail, and be retried once (`audit.py:42`) | Write the report, assign `SEC-###` ids, or re-evaluate previous findings — those stay in the skill's main loop (`skills/freya-codebase-security-scan/SKILL.md:557`) |
| Be started only from an absolute path the operator's `PATH` produced (`audit_adapter.py:107`) | Be started from the scanned repository's own tree, or from a bare name the OS re-searches (`audit_adapter.py:210`) |
| | Commit anything. Only `freya-wrap-up` commits generated artifacts (`skills/freya-codebase-security-scan/SKILL.md:826`) |

That last row is a convention, not an enforced boundary, and it is enforced nowhere — see
[DEVELOPER.md § Artifacts, Not Commits](DEVELOPER.md#artifacts-not-commits) for the incident
that made it one and
[patterns.md § Two-Commit Separation](../patterns.md#pattern-two-commit-separation) for the
rule. One skill does commit and it is not an exception to the rule but an instance of it:
`freya-codebase-security-resolver` commits the *code fix* it made, at its Phase 11, so the scan
that follows has a hash to diff against
(`skills/freya-codebase-security-resolver/SKILL.md:534`). That is commit 1 of the two-commit
pattern. No audit worker commits anything at all — a worker has no write tool and no shell.

## The one accepted regression: Windows on Python 3.9-3.11

Making argv[0] absolute closed arbitrary code execution on every host. On one leg of the
support matrix it also introduced a new failure, and the trade was taken deliberately rather
than discovered afterwards, so it is written down here rather than left for the first person
to hit it.

`exec_path` has two controls. The first is `NoDefaultCurrentDirectoryInExePath`, an environment
variable it sets on Windows (`skills/freya-code-graph/scripts/exec_path.py:65`); when it is
honoured, the working directory leaves the search path entirely and the operator's real binary
is found normally. **It is honoured from CPython 3.12 onwards and ignored on 3.9, 3.10 and
3.11.** The second is the absoluteness refusal, which always applies.

So on **Windows with Python 3.9–3.11** — a leg the CI matrix runs — `shutil.which` still
returns the working-directory hit first, and the absoluteness refusal is the sole control.
A hostile repository that commits `graphify.exe` or `claude.exe` at its root therefore gets a
**refusal**: the resolution is rejected, the legitimate binary further down `PATH` is never
reached, and the command degrades with a stated reason instead of running. For `graphify` that
is a build on the stdlib floor with `degraded_from` recorded; for the audit driver it is
`EXIT_NOTHING_TO_DO` with the refusal printed; for `git` in `freya update` it is a refusal
naming the resolution. A denial of service, in other words, where before there was arbitrary
code execution as the operator.

**That is the accepted trade and the only user-visible regression this security work
introduced.** It is stated at the top of the resolver rather than in a commit message
(`skills/freya-code-graph/scripts/exec_path.py:29`). Two things follow from it. A user on that
leg who sees a refusal naming a binary at a path inside the repository they are scanning is
being told the truth, not hitting a bug. And raising the floor to 3.12 would retire the
regression outright — which is a reason to raise it, recorded here so the reason is not lost.

Not a mitigation, and worth saying because it reads like one: `abspath()`-ing the
working-directory hit would remove the refusal and reinstate the execution, spelled more
convincingly. The security report asked for exactly that, and the resolver's docstring records
why it is the fix backwards (`skills/freya-code-graph/scripts/exec_path.py:23`).

## Path containment is one rule asked four different ways

Most "is this path allowed to name what it names" questions in the toolkit now go through
`skills/freya-code-graph/scripts/containment.py` — most, not all, and the exception is worth
naming because it is deliberate: `audit_engine.resolve_spec_reference` answers the same question
with its own inline `realpath` + `commonpath` test
(`skills/freya-codebase-security-scan/scripts/audit_engine.py:196`) and never imports the module.
Its docstring says why. The module exists because the standing
temptation — write one function and call the rest variants of it — is the error. The four
predicates differ in whether the path exists yet, whether symlinks are part of the answer, and
what a wrong answer costs; **choose by the question, never by the shape of the argument**
(`skills/freya-code-graph/scripts/containment.py:2`).

| Predicate | The question | Symlinks |
|---|---|---|
| `escapes(value)` (`containment.py:41`) | a value **declared** in checked-in data — a directory key, a spec locator, a tsconfig target | not consulted; purely lexical, judged in both path flavours, `..` refused outright |
| `rel_within(root, cand)` (`containment.py:88`) | a resolved filesystem candidate that has to become a **graph key** | preserved, because the key is what three artifacts join on (ADR-025) |
| `within(root, cand)` (`containment.py:122`) | a **security decision** about a path that exists | followed, because the question is which file will actually be opened or executed |
| `is_anchored(text)` (`containment.py:166`) | is this string already absolute, on any host and any supported interpreter | n/a; not the negation of `escapes` — `C:x` both escapes and is not anchored |

There is exactly one other body of the `escapes` rule, `bin/freya_cli.py:_escapes`, and it is a
deliberate exception: the launcher has to diagnose a skill tree that is missing or broken, so it
cannot import from one (ADR-030). The two are held together by
`bin/test_freya_cli.py:1328` (`ContainmentParityTest`), not by hope. `verify_links` used to
carry a third copy with a docstring claiming the two were "deliberately identical" and nothing
holding them to it; it now imports.

Three findings are what made this a module rather than a habit. The import resolver's
containment check was **lexical**, so a `..` in a tsconfig `paths` target resolved outside the
root (SEC-014). A graphify `source_file` became a graph key with no check at all, and the
resulting out-of-project node validated completely clean (SEC-015) — so
`substrate.validate_graph` gained an unconditional project-relative rule for every `files` key
(`skills/freya-code-graph/scripts/substrate.py:736`), which is where the fix binds every backend
including ones nobody has written yet. And `normalise_dir_key` refused only the exact strings
`.` and `..`, so a committed `{"directories": {"../shared": "source"}}` graphed a sibling tree,
read its contents, and re-entered the project through `..` so every in-project file gained a
duplicate node — with `validate_graph` clean (SEC-021).

**The `validate_graph` rule is not a substitute for the refusals, and its own comment says so.**
By the time it runs, the file has been opened and its contents are already in the artifact being
audited; it reports and writes anyway. That check reads the graph, the refusals stop the read
(`skills/freya-code-graph/scripts/settings.py:191`).

## Crossing the project root is a declared act, and it buys resolution only

[ADR-031](../decisions/ADR-031-crossing-the-root-is-a-declared-act.md) added an `outside` section
to the project settings file, mapping an alias to a relative directory outside the root. It is
the only way anything here looks past the root, and the security-relevant part is how little it
grants.

**Resolution, never traversal.** A declared root is `realpath`'d once at parse time; an import
in an in-project file that resolves under one becomes an `outside:<alias>/<rel>` edge target. No
declared root is globbed, walked or added as a scan root, no file under one is ever read, and no
path under one ever becomes a key in `graph['files']` — which is what lets Wave 2's unconditional
`files`-key rule stay unconditional. The warrant is a shipped test you can run —
`test_the_declared_root_is_resolved_into_and_never_walked`
(`skills/freya-code-graph/scripts/test_graph_ops.py:3097`) plants a secret in a referenced *and*
an unreferenced file under a declared root, then asserts it absent from the whole artifact and
asserts the declared tree absent from the directory-listing cache. (A one-off run instrumenting
`open`, `scandir`, `listdir` and `glob` reached the same conclusion while the feature was being
built; that harness was never committed, so the test above is the reproducible half.) If a future
consumer reads content through a declaration, that argument collapses; it is ADR-031's first
revisit condition.

**A consumer that has not been taught fails closed, structurally.** The token has no drive, no
root and no `..` in either path flavour, so joining it onto any root is safe and names nothing
that exists. An untaught consumer refuses — `locator-unresolved`, "not found in graph", an empty
language map — rather than reading. That is a property of the token, not a rule anyone has to
remember.

**A symlink is an implicit crossing, so a declaration never re-authorises one.** Containment
against a declared root resolves both sides, so a symlink planted under one that points
elsewhere is not contained and the crossing is refused. A declared root that is *itself* a
symlink is the other case and is honoured — nothing was crossed implicitly — and named on
stderr (`skills/freya-code-graph/scripts/settings.py:553`).

**The trust argument is not inherited from ADR-019 and the ADR says so.** The declaration comes
from the scanned repository's own committed settings, so the repository grants itself the power
to make the toolkit look outside itself. Naming a backend selects among programs the *operator*
installed; naming a directory supplies the target with no operator-side allowlist. What closes
it is that the oracle's answers never reach the attacker — an existence bit lands in the
victim's gitignored `graph.json` and the victim's stderr. That is exactly the property a
content-reading consumer would destroy.

Adoption is per consumer and the default is refusal: only code-graph's containment sites honour
a declaration. `verify_links`, `detect_project`, `audit_engine.resolve_spec_reference`,
docs-manager and behavior-runner continue to refuse every path outside the project root,
declared or not.

## The driver does not trust what its workers return

Worker output is untrusted input, and the driver treats it that way:

- **Schema validation is ours.** Neither CLI enforces a content schema on a headless
  response, so extraction and validation are implemented here in stdlib
  (`audit_io.py:141`, `:195`). A response that does not validate is rejected with the reason
  fed back into a single retry (`audit.py:273`–`:281`).
- **Extraction picks the last valid candidate, grouped by deliberateness.** A worker that
  demonstrated the output format before answering had its own example handed back as its
  answer — schema-valid, so the task counted as answered, no retry fired, and a real finding
  vanished into an exit-0 clean report (`audit_io.py:141`).
- **A cited spec must exist.** A skeptic downgraded a real SQL injection to
  `intentional-design` by citing an invented path, and another cited the sentence saying no
  specs were found. A citation now only outranks the vote if the project corroborates it —
  the named document exists inside the project, or the named id (`SPEC-007`, `ADR-003`,
  `BEH-012`) appears in a prose file under it (`audit_engine.py:164`). Path traversal is
  rejected by a `commonpath` check, because `../../etc/passwd` exists everywhere and says
  nothing about intent (`audit_engine.py:196`).
- **A hostile or broken response cannot hang the run.** The salvage scanner stops after 500
  candidate `{` positions; an unbalanced brace in a 433 KB response measured 6.9 s of
  quadratic scanning on a pool thread that `--timeout` does not cover (`audit_io.py:75`).
- **A cited spec must exist, and the scanner may not be its own witness.** The corroboration
  check used to accept any `[A-Z]{2,6}-\d+`, so `CWE-89` counted as a spec reference. Narrowing
  the namespace was not enough on its own: `_SPEC_ROOTS` included the tool's own output
  directory, so `SPEC-999` still corroborated — out of the sentence in the security report
  describing the test that says it must not. The tool's own output is now excluded on the path
  branch as well as the id branch (`audit_engine.py:213`, `:222`).
- **A skeptic's veto is bound to the lens that was asked for.** The `spec-intentional`
  downgrade used to be granted on a verdict's *self-declared* lens, so a dead call could slide
  a `compensating-controls` verdict into the slot the caller believed was `spec-intentional`.
  The binding happens in `_settle`, on the raw slice, and it has to run **before** the falsy
  filter in `disposition` rather than after it (`audit_engine.py:451`, `:452`).
- **No answers is never reported as no findings.** If every call failed, or if tasks went
  unanswered and nothing survived, the run exits 2 (`audit.py:509`, `:513`); if tasks went
  unanswered but findings did survive, the run prints an INCOMPLETE banner and exits 3
  (`audit.py:527`, `:558`). An empty array means clean only on exit 0
  (`skills/freya-codebase-security-scan/SKILL.md:138`–`:146`).

## A secrets finding is fingerprinted before it can be re-sent

A `secrets` finder reads a credential out of the scanned repository and copies it into
`codeSnippet`. Three things then happen to that finding — three skeptic prompts, the audit
result on stdout, and the report the skill writes — and before this branch the credential
travelled through all three. Sending a customer's live API key back out to a vendor's CLI, in
an argv visible to any local user, is a worse outcome than the finding it describes.

**The cut is at the single ingest, not at the three egresses.** `redact_secret_evidence` runs
once, where a finder's finding enters the engine (`audit_engine.py:376`), so every downstream
consumer is fed the redacted object and there is no fourth door for someone to forget. The
alternative that was proposed — a projection applied at each egress — keeps `title` and
`recommendation`, which is the leak itself.

What it does (`skills/freya-codebase-security-scan/scripts/audit_io.py:309`): `codeSnippet` is
replaced whole with a stable fingerprint, and the four model-written fields — `description`,
`title`, `recommendation` and `cwe` — are scrubbed of that snippet's literals and of each of its
lines, because a finder that writes "hardcoded key AKIA… on line 12" has copied the snippet into
whichever prose field it happened to be filling. Substitution of literals the finder already
handed over, never pattern detection: a detector fails two ways and both are silent, a miss
leaking the value and a false positive deleting evidence nobody will diff against the source
(`audit_io.py:260`).

`cwe` is in that list and the reason it was nearly left out is the general rule. It was excluded
as "an identifier" — a statement about what the field is *for*, not about what a model writes
into it. `FINDER_SCHEMA` declares it a free string, and measured 2026-08-23 a `cwe` reading
`CWE-798 - the line is AWS_SECRET_ACCESS_KEY = "<key>"` came back out of `audit()` with the
credential intact through all three doors. **A field earns exclusion by what scrubbing it
costs, never by what it is nominally for** (`audit_io.py:299`). `file` is the one field excluded
on cost: it is what a reader needs in order to go and rotate the key.

The fingerprint has one canonical spelling, `<redacted len={n} prefix={prefix!r} sha256={digest}>`
(`audit_io.py:241`), because two producers write fingerprints into the same report — this
function, and the agent following the skill's own redaction rule — and a second spelling costs
the property the digest exists for, which is that last month's report can be diffed against this
one. `KEEP_PREFIX` is 4 (`audit_io.py:247`), and a value short enough that four characters would
be most of it shows no prefix at all.

**Two gaps, stated rather than papered over.** It acts only where the finder already said
`secrets`, and it scrubs the snippet's own bytes — so a credential a finder paraphrases,
reflows, or quotes from somewhere other than `codeSnippet` survives. And it is prevention, not
retraction: it stops a value being written and cannot recall one already committed. The agent
half of the same rule is what R14 of the conformance gate checks — that a skill sending a worker
at secret-bearing material states the rule and restates it in the copied-source slot
(`bin/check_skill_conformance.py:50`) — and R14 is a presence check, so it pins one slot rather
than the file. See
[TESTING.md § The conformance gate](TESTING.md#the-conformance-gate) for what it measurably does
and does not catch.

## `audit` spends real money, and the plan is the gate

The worst case is `1 + rounds x 6 + 3 x findings` logical tasks, each of which may retry once
(`audit.py:153`, `:163`). One finder worker measured $0.396 on a trivial fixture (ADR-015),
so a full audit is dozens of calls and tens of dollars on a real repository. That cost is the
reason `audit` is on-demand and is deliberately **not** part of `freya-wrap-up`, which runs
`update` (`skills/freya-codebase-security-scan/SKILL.md:544`, `:636`).

The gates, in the order a run meets them:

1. **`--max-findings` is derived from `--max-calls`, not chosen independently**
   (`audit.py:173`), so the two cannot disagree about what the ceiling can pay for.
2. **A ceiling too small to verify one finding is refused, not warned about**
   (`audit.py:421`). Measured: `audit --max-calls 10` prints "`--max-findings` is 0, so this
   run could only ever report `[]` no matter what it found — refusing to start" and exits 2.
   The configuration's only possible output is a false clean bill of health.
3. **The cost plan prints before anything is spent** (`audit.py:430`–`:443`), on stderr,
   because stdout carries only the JSON payload. Measured in this checkout on 2026-08-21:

   ```text
   $ freya security audit --project . --dry-run
   mode:         audit — exhaustive loop-until-dry discovery
   agent:        claude
   project:      /…/freya-devkit
   call ceiling: 200 attempts (each of 100 tasks may retry once)
   worst case:   200 attempts (1 context + 5x6 finders + 3 skeptics x 23 findings)
   buys you:     up to 23 findings discovered and verified
   This spends real money. One worker measured ~$0.40 on a trivial fixture.
   ```

4. **`--dry-run` returns immediately after printing that** (`audit.py:445`) — no worker is
   spawned and nothing is spent. Verified by running the command above.
5. **An unattended run without `--yes` refuses.** With no tty the driver does not block on
   `input()`; it declines and exits 4 (`audit.py:452`). Measured: `audit.py scan --project .
   < /dev/null` exits 4 with "refusing to spend money unattended". Exit 4 is deliberately
   distinct from exit 1, which means only "neither `claude` nor `copilot` is on `PATH`" — the
   two used to share a code, with the consequence traced in
   [TROUBLESHOOTING.md § `freya security` exits 4 in an unattended run](TROUBLESHOOTING.md#freya-security-exits-4-in-an-unattended-run).
6. **The ceiling stops the run mid-flight.** `Budget.spend` reserves a slot before every call
   under a lock and raises `BudgetExhausted` at the ceiling (`audit.py:92`); the engine keeps
   the work already paid for and the driver reports INCOMPLETE (`audit.py:535`).

Because the driver's own confirmation prompt cannot reach a user through an agent shell, the
money gate moves into the conversation: the skill must show the user the `--dry-run` plan,
get a yes, and only then pass `--yes` (`skills/freya-codebase-security-scan/SKILL.md:111`–`:116`).

## The declared-intent marker is a file the scanned repository can write

The G1 gate answers "which accepted tests changed without an authorising INTENT record", and it
does so by diffing against a baseline commit read out of a marker file the scanned repository
commits. That is the shape of the finding this branch spent the longest on, and it took five
attempts to close, so the residue is worth stating rather than leaving as a gap.

**Three argv tokens are what make the marker unable to be read as anything but a revision**
(`skills/freya-spec-manager/scripts/verify_intent.py:162`–`:186`). `--end-of-options` refuses to
read it as an OPTION: without it, a marker holding `--output=/tmp/victim` made git **truncate
that file**, write the diff into it, and return rc=0 with empty stdout. `^{commit}` refuses to
read it as a non-commit object or as a pathspec: a tree hash is 40 hex characters, git diffs a
tree against the working tree happily, and picking a subtree makes everything outside it report
as `A`, which the gate calls free. The trailing `--` is, as a refusal, now redundant — the peel
subsumes it — and it is kept for the other direction, so a repository committing a file named
`<its own marker sha>^{commit}` cannot make git read the argument as a path.

**And a marker with no usable value is not the same as a fresh repository.** A `commit:` line
with no value, no `commit:` line at all, and a zero-byte file each returned a bare `None`, which
is the exact fingerprint of a repository that has never recorded a baseline — so `--advance`
exited 0 and erased the finding. `--advance` now refuses on `skipped` as well as on a blocking
result, and the carve-out that survives is narrow and deliberate: an **absent** marker file
still advances, an empty or malformed one no longer does.

**What rc=0 means, exactly, and not one word more.** Git resolved the marker to a commit **in
this repository** and diffed it. It does *not* mean the commit is one this toolkit chose. The
marker is a file the scanned repository can write, so a repository willing to commit
`commit: <its own HEAD>` gets an honest diff of nothing and a truthful exit 0. That is ADR-008's
trust model for the marker rather than a bypass of it, and nothing said so out loud until it was
written into `_changed_status`'s docstring
(`skills/freya-spec-manager/scripts/verify_intent.py:206`).

Both of the gate's fail-open paths now **say** they failed open rather than reporting a clean
run: `ok=False` when git could not answer, and a labelled skip rather than `skipped: false`
(`skills/freya-spec-manager/scripts/verify_intent.py:152`). A consumer must therefore check
`skipped` before trusting exit 0 — that sentence lives in the module docstring
(`skills/freya-spec-manager/scripts/verify_intent.py:23`) and is the thing to mirror anywhere a
skill tells an agent to read the JSON on a non-zero exit.

## Live agent-CLI testing runs under a redirected `HOME`

Live validation drives real agent CLIs holding real tool permissions, so it runs under
`HOME=/tmp/freya-sandbox`. That works because every home-derived path in the toolkit follows
`$HOME`, as does Node's `os.homedir()` — and both agent CLIs are Node programs. The recipe,
including the three greps that check the invariant still holds before you spend money, is in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md#running-a-live-agent-validation)
(`CONTRIBUTING.md:34`, with the three greps at `CONTRIBUTING.md:39`–`:41`).

**It has two documented limits — isolation by convention rather than an enforced boundary, and
a broken macOS Keychain — and both are recorded there rather than here so there is one copy**
(`CONTRIBUTING.md:46`–`:49`).

Two related items are open, and both are in the backlog rather than fixed:

- **The escape audit is owed.** The one isolation diff that exists covers phase 6's Part A
  only. Every live agent run since — including a Copilot session granted
  `--allow-tool=shell --allow-tool=write`, and the window where the real `~/Library/Keychains`
  was symlinked into the sandbox — happened with nothing watching. Nothing suggests anything
  escaped; the point is that no one looked
  ([roadmap.md § Platform-blocked](../roadmap.md#platform-blocked)).
- **The read-only bypass probe has never been run** (same section).

## A finding may be downgraded, never deleted

[ADR-012](../decisions/ADR-012-accepted-behavior-downgrades-findings.md) governs how a
security finding may be silenced, and the rule has two halves.

**Only an `accepted` behavior may downgrade, and what that is evidence *of* is narrower than
it reads.** An accepted behavior is the strongest intentional-design evidence the scan has: its
state and its locator are re-derived from the project's committed specs at query time, so a
behavior demoted to `proposed` stops licensing a downgrade at the next query rather than at the
next build. The canonical case is a scan flagging "endpoint does not verify the user exists"
against a deliberate uniform anti-enumeration response: real as a pattern, wrong as a verdict,
and the recorded intent is what settles it.

**Whether a test is run depends on one flag, and this page has been wrong about it in both
directions.** It first said "a passing linked test proves the flagged pattern is the intended,
working behavior — verified evidence rather than a prose claim". That was false: nothing ran,
and the sentence reads as a safety property, which is what made it the most valuable finding of
the branch. It then said no test could ever be run, because the only evidence not supplied by
the audited repository would be executing that repository's suite, "which is worse than the
problem it would solve". That was false too, and worse, because it argued against a capability
this toolkit ships: `freya-behavior-runner` exists to run a project's tests, and freya is a tool
a developer points at a repository they are working in, having already installed its
dependencies and run its suite. What is true now:

- **Plain `--covering` executes nothing**, and what it demands of the committed artifacts is
  narrow: `state: accepted` and a locator, both re-derived from the specs; that locator must
  resolve to a file inside the project; and the exercised path must carry `source: observed`.
  An edge marked `static` — inferred from the import graph, no test involved at all — licenses
  nothing. Until 2026-08-24 it silenced a finding exactly as a recorded run did, which is a
  wider hole than the finding that prompted the review described, and one that needed no
  forgery: an accepted behavior with no runnable adapter gets `static` edges from an ordinary
  `--build`.
- **`--covering --verify` re-runs each returned behavior's linked test** through
  `freya-behavior-runner`, batched into one invocation, and the security scan passes that flag
  (`skills/freya-codebase-security-scan/SKILL.md:421`). A row whose `verified.passed` is false
  is evidence *against* the behavior and downgrades nothing.
- **Either way the answer says which of the two happened.** Every result carries an `evidence`
  string naming what was trusted, the skill copies it into the report verbatim, and writing
  "verified by passing test" over a row that was not verified is forbidden in as many words
  (`skills/freya-codebase-security-scan/SKILL.md:436`).

Unverified, `observed` still means *a test passed once, on somebody's machine, at the commit
`freshness` names* — a label on evidence rather than a verification. A freshness gate cannot
substitute for one either: committing `behavior.json` necessarily creates a later commit, so
`freshness != HEAD` for every entry on any fresh clone, and gating on it would empty
`--covering` permanently. SEC-006 is **closed**.

**The bar is enforced by the query, not only by procedure.** `freya behavior-graph --covering
<file>` filters to `state == "accepted"` inside `covering()`
(`skills/freya-behavior-graph/scripts/behavior_graph.py`) before the agent ever judges
relevance, so a `proposed` or `confirmed`
behavior is never even a candidate for silencing — it may add an advisory note and the finding
stays open (`skills/freya-codebase-security-scan/SKILL.md:445`). The trust boundary sits in
deterministic code rather than in an instruction the agent could drift from. That filter is
cited by line in ADR-012 and in the scan report, and both citations have already been repointed
once on this branch, so it is named by function here instead: a line number into a file this
branch is still rewriting is a citation with a short shelf life.

**A gate-green repository can still get nothing back from `--covering`, and that is correct.**
Two independent reasons, and the second is the one that will surprise a reader. First,
`covering()` re-checks the locator itself rather than trusting that `verify_links` ran, and the
two checks are deliberately not the same one; `LocatorCheckDivergesFromTier1Test` in
`skills/freya-behavior-graph/scripts/test_behavior_graph.py` runs one fixture through both.
As of 2026-08-24 exactly one measured divergence is left — a `.py` fragment naming no symbol,
which Tier 1 refuses and this query returns — and it runs in Tier 1's favour, which is why
running the gate is still worth more than running this. The three rows that used to run the
other way now agree at *both refuse*: a locator with no path part, a locator naming a
directory, and no locator at all. Second, and unrelated to locators, `--covering` requires an
exercised path whose `source` is `observed`, and `verify_links` never looks at coverage — so a
repository whose accepted behaviors carry only statically inferred edges is green at Tier 1 and
gets an empty `--covering`. Say both out loud, because the first person to meet a correct
refusal on a green repository will otherwise file a bug against `behavior_graph.py`.

**A downgrade annotates and reclassifies; it never deletes.** The finding stays fully visible
in the report with status INTENTIONAL DESIGN and a `behavior_ref` naming the behavior, plus the
query's `evidence` string copied verbatim (`skills/freya-codebase-security-scan/SKILL.md:432`;
`skills/freya-codebase-security-scan/references/findings-schema.md:22`, `:40`), and drops out
of the *outstanding* count only. That last part is code: `collect_status` counts a finding as
outstanding unless its status is exactly `open`
(`skills/freya-status/scripts/collect_status.py:214`). SEC-007 changed the shape of that
filter and it is worth knowing which way: the census used to *drop* any finding whose status
was outside its vocabulary, so a typo'd or unknown status reported **zero open findings with no
note at all** — a silently-clean security bucket, which is the exact failure ADR-005 and
SPEC-027 exist to prevent. Unknown statuses now go into the alarm rather than into silence.
Unlike the accepted-only
filter above, **this half is procedure**: the report is written by the skill's main loop, and
nothing checks that a downgraded finding is still in it. A misjudgment is therefore a visible,
reversible annotation rather than a vanished finding. Findings also persist across scans: the previous report's findings
are re-evaluated and carried forward as PERSISTENT, RESOLVED or REGRESSED rather than dropped
(`skills/freya-codebase-security-scan/SKILL.md:788`–`:812`).

**Where a finding genuinely does disappear.** Two honest exceptions to "never deleted", both
inside the driver and before any report exists:

- A finding refuted by *every* lens that answered is dropped and never leaves the engine
  (`audit_engine.py:312`, `:538`). Three-of-three is the bar precisely because one lens
  would make any single refutation unanimous.
- Zero verdicts — every skeptic call failed — yields `needs-review`, not a drop
  (`audit_engine.py:307`). No information is not unanimous refutation. This is a deliberate
  divergence from the retired JS engine, which deleted the finding.

The `mitigated` disposition appears in the skill's status mapping (`skills/freya-codebase-security-scan/SKILL.md:624`) but **no
code path emits it**: `grep -rn mitigated skills/ --include='*.py'` outside tests returns
nothing. It is a known dead branch (ADR-015 § Revisit Conditions).

## The CI workflows are SHA-pinned, and the gate that keeps them so over-reports

Every `uses:` in `.github/workflows/` names a 40-hex commit rather than a moving tag, and
`actions/checkout` runs with `persist-credentials: false` — its default is true, which writes
the job's `GITHUB_TOKEN` into `.git/config` where every later step in the job can read it
(SEC-018). `bin/test_workflow_pins.py` is what keeps both true: it parses the workflows as
text, because a YAML parser is not standard library and a dependency is an ADR.

Reading YAML as text means the parser meets spellings it cannot handle, and **every one of
those is answered by over-reporting rather than by passing.** A `uses:` line it cannot read is
a failure naming the line; a `permissions:` block it cannot parse is treated as granting write;
and a workflow with **no `permissions:` key at all** is treated the same way — because absent is
not "grants nothing". GitHub falls back to the repository default, which can be read-and-write,
so the effective grant is one this parser has no way to see.

That last case was the gate's own version of the defect it exists to catch. A workflow with no
block simply produced no permission sites, `any([])` was False, and the persisted-token rule
silently did not apply to the whole file — reachable by the ordinary next edit, which is adding
a workflow. The cost of the over-report is that a genuinely read-only workflow has to say so,
which is a line worth writing in a repository that publishes a site.

## Open questions

The verified gaps in this document's subject — the unprobed read-only guard, the owed escape
audit, and the fact that no live agent run has ever happened on Windows — are carried in
[roadmap.md § Platform-blocked](../roadmap.md#platform-blocked) and are not restated here. What
follows are questions this document raised that nothing in the repository answers:

- [TODO: Where should someone outside the project report a vulnerability *in freya-devkit
  itself*? There is no `SECURITY.md` at the repo root and no `.github/SECURITY.md`. The only
  contact address in the tree is the plugin author's (`.claude-plugin/plugin.json:7`,
  `.claude-plugin/marketplace.json:5`), which is nowhere declared as a disclosure channel — so
  this document cannot state a disclosure path.]
- [TODO: What exactly does Copilot's `read` tool group cover on the current CLI version — in
  particular, does it include network fetches? The Claude adapter names its three tools
  explicitly, but `--allow-tool=read` is a vendor-defined group whose membership is not
  recorded anywhere here and can change between releases.]

## Related documentation

- [ADR-015](../decisions/ADR-015-driver-owned-fan-out.md) — why the fan-out is owned by our
  driver, and why the allowlist rather than the deny flags is the control
- [ADR-012](../decisions/ADR-012-accepted-behavior-downgrades-findings.md) — which evidence
  may downgrade a finding, and why a downgrade never deletes
- [ARCHITECTURE.md](ARCHITECTURE.md) § The audit driver — where the driver sits among the
  skills
- [ENVIRONMENT.md](ENVIRONMENT.md) § Credentials, § External binaries — what freya reads from
  the environment and what it spawns
- [CONTRIBUTING.md](../../CONTRIBUTING.md) § Running a live agent validation — the sandbox
  recipe and its two limits
- [roadmap.md](../roadmap.md) § Platform-blocked — the escape audit, the bypass probe, and
  the untested Windows path

# Security

> Last updated: 2026-08-21

The security posture of **freya-devkit itself**: what the toolkit executes on your machine,
what capability it hands the processes it spawns, what it refuses to do, and which of those
properties are enforced by tested code rather than by prose.

This is not a vulnerability report of a project the toolkit scanned. Those are written per
scan to `knowledge-base/security/codebase-security/YYYY-MM-DD.md` in the scanned project
(`skills/freya-codebase-security-scan/SKILL.md:805`), alongside a machine-readable
`findings.json` (`skills/freya-codebase-security-scan/references/findings-schema.md`). This
repository has no `knowledge-base/security/` directory: the toolkit has been run against
itself for graphs and docs, not yet for a committed security report.

## What there is to attack

There is no service, no daemon, no listening port, no database, no container and no
credential store. A skill is a `SKILL.md` the agent reads plus stdlib Python the agent runs
through one launcher, `freya <command>` (`bin/freya_cli.py:135`, which execs the target with
`sys.executable`). Two properties were measured on 2026-08-21 rather than assumed:

- **No third-party runtime dependency, and no networking module.** An AST walk over every
  `.py` under `bin/` and `skills/`, collecting the top-level module of every `import` and
  `from … import`, returned only stdlib names plus sibling modules from this repository —
  and none of `socket`, `ssl`, `http` or `urllib` appears among them. pytest is the one
  thing ever installed, and only to run the tests (`CONTRIBUTING.md:129`). There is no
  lockfile to audit and no supply chain to compromise, which is also why
  `freya-dependency-vulnerability-check` has nothing to say about this repo — it scans the
  *target* project's manifests.
- **No shell.** `grep -rn "shell=True" bin/ skills/ --include='*.py'` returns nothing. Every
  subprocess is an argv list.

What the toolkit does execute:

| What | Where | Notes |
|---|---|---|
| A bundled script, under the current interpreter | `bin/freya_cli.py:135` | argv is `[sys.executable, <script from bin/commands.json>, *args]`; no `python` need be on `PATH` |
| `git`, read-only queries | `skills/freya-status/scripts/collect_status.py:33`, `skills/freya-code-graph/scripts/graph_ops.py:535`, `skills/freya-spec-manager/scripts/verify_intent.py:76` | `rev-parse`, `diff --name-only` and similar; the graph and status layers never write git state |
| `git fetch` and `git merge --ff-only` | `bin/updater.py:346`, `:360` | Only during `freya update`, which fast-forwards the checkout to its tracked branch (`CONTRIBUTING.md:183`) |
| An agent CLI as an audit worker | `skills/freya-codebase-security-scan/scripts/audit_adapter.py:45`, `:139` | The subject of most of this document |
| The project's own test command | `skills/freya-behavior-runner/scripts/run_behaviors.py:191`, `:217` | `pnpm vitest run <test file>`. Running a project's tests is executing project-controlled code, by design and unavoidably |
| `graphify` | `skills/freya-code-graph/scripts/backend_graphify.py:434` | Only when the project selected that backend; the stdlib floor is the default (ADR-019) |

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
rounds — 1 versus 5 (`audit.py:50`, `audit_engine.py:24`). Verification is never cut. With a
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

Two mutants run against the shipped tests on 2026-08-21 confirm that ordering:

| Mutation | Result |
|---|---|
| Delete `--disallowedTools "Write Edit Bash"` from the Claude argv | 207 of 207 tests still pass — the deny flags are not what the suite is holding |
| Delete `--allowedTools "Read Grep Glob"` from the Claude argv | `ReadOnlyTest::test_claude_restricts_tools_to_read_only` fails |

(Method: copy `skills/freya-codebase-security-scan/scripts/` to a temporary directory, remove
the line, `python3 -m pytest` that copy. Four of those 207 tests are the read-only guard
itself, `test_audit_adapter.py:58`–`:73`.)

**What the boundary is not.** It is a *tool* restriction, not a filesystem jail and not a
process sandbox. A worker runs with `cwd` set to the project (`audit.py:252`), but no argv
element confines its reads to that directory — whether the host CLI applies a directory
boundary of its own is host behaviour nothing here tests. No `env=` is passed to `subprocess.run`
(`audit.py:240`), so each worker inherits the parent environment whole — including anything
credential-shaped in it. The no-writes evidence collected so far is scoped to the fixture or
repository under audit (checksums plus `git status --porcelain` before and after) and could
not have seen a write to `$HOME` or `/tmp` (ADR-015 § Revisit Conditions). The prompt is
passed as an argv element (`audit_adapter.py:47`, `:59`), so it is visible in a process
listing to any local user who can see the process.

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
| Fail, and be retried once (`audit.py:42`) | Write the report, assign `SEC-###` ids, or re-evaluate previous findings — those stay in the skill's main loop (`SKILL.md:537`) |
| | Commit anything. Only `freya-wrap-up` commits generated artifacts (`SKILL.md:807`) |

That last row is a convention, not an enforced boundary, and it is enforced nowhere — see
[DEVELOPER.md § Artifacts, Not Commits](DEVELOPER.md#artifacts-not-commits) for the incident
that made it one and
[patterns.md § Two-Commit Separation](../patterns.md#pattern-two-commit-separation) for the
rule. One skill does commit and it is not an exception to the rule but an instance of it:
`freya-codebase-security-resolver` commits the *code fix* it made, at its Phase 11, so the scan
that follows has a hash to diff against
(`skills/freya-codebase-security-resolver/SKILL.md:534`). That is commit 1 of the two-commit
pattern. No audit worker commits anything at all — a worker has no write tool and no shell.

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
- **No answers is never reported as no findings.** If every call failed, or if tasks went
  unanswered and nothing survived, the run exits 2 (`audit.py:509`, `:513`); if tasks went
  unanswered but findings did survive, the run prints an INCOMPLETE banner and exits 3
  (`audit.py:527`, `:558`). An empty array means clean only on exit 0
  (`SKILL.md:138`–`:146`).

## `audit` spends real money, and the plan is the gate

The worst case is `1 + rounds x 6 + 3 x findings` logical tasks, each of which may retry once
(`audit.py:153`, `:163`). One finder worker measured $0.396 on a trivial fixture (ADR-015),
so a full audit is dozens of calls and tens of dollars on a real repository. That cost is the
reason `audit` is on-demand and is deliberately **not** part of `freya-wrap-up`, which runs
`update` (`SKILL.md:617`).

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
get a yes, and only then pass `--yes` (`SKILL.md:111`–`:116`).

## Live agent-CLI testing runs under a redirected `HOME`

Live validation drives real agent CLIs holding real tool permissions, so it runs under
`HOME=/tmp/freya-sandbox`. That works because every home-derived path in the toolkit follows
`$HOME`, as does Node's `os.homedir()` — and both agent CLIs are Node programs. The recipe,
including the three greps that check the invariant still holds before you spend money, is in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md#running-a-live-agent-validation) (`:34`–`:44`).

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

**Only an `accepted`, test-backed behavior may downgrade.** A passing linked test proves the
flagged pattern is the intended, working behavior — verified evidence rather than a prose
claim. The canonical case is a scan flagging "endpoint does not verify the user exists"
against a deliberate uniform anti-enumeration response: real as a pattern, wrong as a verdict,
and the behavior's passing test is what settles it.

**The bar is enforced by the query, not only by procedure.** `freya behavior-graph --covering
<file>` filters to `state == "accepted"` before the agent ever judges relevance
(`skills/freya-behavior-graph/scripts/behavior_graph.py:427`), so a `proposed` or `confirmed`
behavior is never even a candidate for silencing — it may add an advisory note and the finding
stays open (`SKILL.md:424`). The trust boundary sits in deterministic code rather than in an
instruction the agent could drift from. (ADR-012 cites this filter as `behavior_graph.py:320`;
the code has moved since — `:320` is now inside `_covered`.)

**A downgrade annotates and reclassifies; it never deletes.** The finding stays fully visible
in the report with status INTENTIONAL DESIGN and a `behavior_ref` naming the behavior and its
test (`SKILL.md:420`; `references/findings-schema.md:22`, `:40`), and drops out of the
*outstanding* count only — that last part is code, a `status == "open"` filter over
`findings.json` (`skills/freya-status/scripts/collect_status.py:197`). Unlike the accepted-only
filter above, **this half is procedure**: the report is written by the skill's main loop, and
nothing checks that a downgraded finding is still in it. A misjudgment is therefore a visible,
reversible annotation rather than a vanished finding. Findings also persist across scans: the previous report's findings
are re-evaluated and carried forward as PERSISTENT, RESOLVED or REGRESSED rather than dropped
(`SKILL.md:769`–`:800`).

**Where a finding genuinely does disappear.** Two honest exceptions to "never deleted", both
inside the driver and before any report exists:

- A finding refuted by *every* lens that answered is dropped and never leaves the engine
  (`audit_engine.py:312`, `:538`). Three-of-three is the bar precisely because one lens
  would make any single refutation unanimous.
- Zero verdicts — every skeptic call failed — yields `needs-review`, not a drop
  (`audit_engine.py:307`). No information is not unanimous refutation. This is a deliberate
  divergence from the retired JS engine, which deleted the finding.

The `mitigated` disposition appears in the skill's status mapping (`SKILL.md:605`) but **no
code path emits it**: `grep -rn mitigated skills/ --include='*.py'` outside tests returns
nothing. It is a known dead branch (ADR-015 § Revisit Conditions).

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

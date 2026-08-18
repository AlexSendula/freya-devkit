# Phase 7 validation — driver-owned fan-out, live

**Run 2026-08-17 on macOS 15.6, Python 3.12.5.** Continues
[`phase-6-validation-log.md`](phase-6-validation-log.md), which produced the finding this
phase exists to fix. Design: [`../../superpowers/specs/2026-08-17-driver-owned-scan-design.md`](../../superpowers/specs/2026-08-17-driver-owned-scan-design.md).

Worker CLIs: GitHub Copilot CLI 1.0.75 on `gpt-5.6-luna` (a Copilot Pro month bought for
this testing) and Claude Code 2.1.220 on `haiku` (phase 6's 2.1.233 lives only in the sandbox). Fixture: `/tmp/freya-phase7/fixture`, git-tracked, five files.

> **On the evidence behind these numbers (noted 2026-08-18).** Everything below is
> **prose transcription** — no raw artifact from either phase is committed to this repo.
> That includes the 800 KB `--log-level debug` log behind the delegation finding, which
> is the sole source for the tool-invocation table and the quoted Copilot system-prompt
> clauses, and which lived under `/tmp` and is gone. Exit codes, wall clocks, call counts
> and cost figures are likewise unbacked. Nothing here is doubted; the cost is that a
> future maintainer asking "did Copilot's delegation policy change in CLI 1.1.x?" has no
> baseline to diff against and must re-derive the finding from scratch, re-purchasing
> quota to do it. **Future live runs should commit the load-bearing extracts** — at
> minimum the tool-invocation counts, the quoted prompt block, and one full driver stderr
> transcript per adapter — under `docs/design/portability/evidence/`, and cite them by
> path from the prose.

## The fixture

Three planted issues and one control:

| File | Line | Planted |
|---|---|---|
| `src/auth.js` | 2 | hardcoded production DB password |
| `src/auth.js` | 5 | SQL injection by string concatenation |
| `src/upload.js` | 5 | path traversal on an operator-supplied filename |
| `src/render.js` | — | **control.** `textContent` never parses HTML. Any finding here is invented. |

`knowledge-base/reference/architecture.md` gives the trust boundary. No specs, so
`spec-intentional` has nothing to find and must not invent something.

## What the driver did

Five live runs, all exit `0`.

| Run | Mode | Concurrency | Wall clock | Calls | Findings |
|---|---|---|---|---|---|
| 1 | `scan` | 6 | **91.4 s** | 19 | 4 |
| 2 | `scan` | 1 | **209.3 s** | 16 | 3 |
| 3 | `scan` (after the colocation fix) | 6 | **70.1 s** | 19 | 4 |
| 4 | `audit` | 6 | 86.7 s | 19 | 4 |
| 5 | `scan` on the **`claude`** adapter (`haiku`) | 6 | 210.0 s | 27 | 6 |

Every run found **all three** planted issues. **No run reported anything in
`src/render.js`.** After all five, the fixture was byte-identical to its pre-run
checksums and `git status` was empty — the read-only allowlist held.

### The throttling question, answered

The spec asked for the one measurement only a live run can give: does the CLI throttle?

**209.3 s at `--concurrency 1` against 91.4 s at `--concurrency 6` on the same fixture —
2.29×, not 6×.** Some of that is structural: the run is 1 serial context call, then one
wave of 6 finders, then 12 skeptic calls in 2 waves of 6, so ~4 waves at best. At the
serial rate of 13.1 s/call, 4 perfect waves would be ~52 s; the measured 91.4 s means
per-call latency roughly **1.75× worse under concurrent load**. So Copilot does apply
back-pressure — and the pool still more than doubles throughput. `--concurrency 6` is
worth having; expecting linear scaling is not.

### The `claude` adapter, once its login was renewed

Run 5, same fixture, `--agent claude --model haiku`. **Exit 0. All three planted issues
found. Zero findings in the control file. Fixture byte-identical, `git status` empty.**
Cost reported by the adapter: **$1.12** for 27 calls.

Two things it showed that Copilot's runs did not.

**The retry path finally ran.** Phase 6 recorded that the extract-validate-retry design
was *never stressed in the field* — 47 live worker invocations, zero failed calls. Here
**2 of 27 attempts failed and both recovered on retry**: `health.unanswered` stayed 0, so
the degraded guard correctly did **not** fire and the run exited 0. That is the designed
distinction — attempts drive diagnostics, *tasks* drive the trust decision — observed live
for the first time rather than only in tests.

**`colocated` caught a second pair, on a second adapter.** Claude reported the SQL
injection under both `auth` and `injection` at line 5 (as Copilot did), *and* the exported
credentials under both `secrets` and `api` at line 12 — `module.exports = { findUser,
isAdmin, DB_PASSWORD }`. Four of its six findings are two real issues seen twice. Without
the annotation the report would have listed six vulnerabilities in a five-file project.

The two adapters also disagree on severity — Claude rated everything `critical`, Copilot
`high` — and on volume: Claude found 8 candidates in one round against Copilot's 4, hitting
the `--max-findings 6` cap. Neither is wrong; it is a reminder that the disposition ladder
normalises *confidence*, not *severity*.

### Round arithmetic, live

`scan` printed `worst case: … (1 context + 1x6 finders + …)` and `round 1/1`; `audit`
printed `1 context + 5x6 finders` and `round 1/5`. The preset is visible in the plan
before a cent is spent.

## Two defects the live runs found, both fixed

**1. One vulnerability, two categories, two findings** (`7cd7fa3`). Run 1 reported the SQL
injection at `src/auth.js:5` twice — once from the `auth` finder, once from `injection` —
because the dedup key is `file + line-window + category`. Six verification calls went to
one issue. Run 2, same fixture, produced only one: **the double-counting is not even
reproducible**, so a user cannot predict whether their report inflates.

Not fixed by dropping category from the key. Two genuinely different issues can share a
five-line window — this very fixture has a secret on line 2 and an injection on line 5 —
and merging blind would delete one silently. Between a visible duplicate and a silent
deletion, a security tool takes the duplicate. So survivors now carry `colocated`, and the
skill's report loop decides. Run 3 confirmed it: the pair reported
`colocated=['injection']` / `['auth']`, and the two genuinely distinct findings in the same
file reported `[]`.

**2. "last error: exit 1"** (`f9005cd`). The `claude` adapter failed instantly on this
machine. The driver's guard was right — it refused to call an empty result clean and exited
`2` — but the reason it printed was useless. Reproducing the call by hand showed why:
`claude -p` answers a failed call with returncode 1, **empty stderr**, and the reason inside
its JSON envelope on stdout: *"Failed to authenticate: OAuth session expired and could not
be refreshed"*. `failure_reason()` now prefers stderr, falls back to the adapter's parsed
payload, and only then to the exit code. Re-run live, the driver prints the real message.

## End to end: does the skill actually reach the driver?

The phase 6 finding was that Copilot **ran the six category scans itself** and reported them
as parallel. This is the test of whether phase 7 fixed that. Sandbox `HOME`, plugin store
reset to `f9005cd`, Copilot given `--allow-tool=shell --allow-tool=write`, throwaway fixture
copy, prompt: *"Run the freya-codebase-security-scan skill in scan mode on this project."*

**First attempt** — Copilot said *"Running the required full scan driver now"* and invoked
it. **No greps.** The driver autodetected `claude` (its stated preference, because Claude
reports per-call spend), was handed the Copilot model name from the prompt, and failed with
`unrecognized_model`. Copilot reported the failure and **wrote no report** — which is the
correct behaviour, and a third live confirmation that a failed run cannot be mistaken for a
clean one. It also exposed a documentation gap: `--agent` and `--model` are a pair, and the
two CLIs' model vocabularies do not overlap. Now stated in `SKILL.md`.

**Second attempt**, worker pinned with `--agent copilot`:

- driver invoked, 4 findings returned;
- Copilot **resolved the `colocated` pair** into one finding, exactly as Phase 3 step 1
  instructs — `Category: Authentication & Authorization + Input Validation & Injection`,
  and the executive summary says the merge happened;
- wrote `2026-08-17.md`, `findings.json` and `.security-last-scan`;
- **did not commit.** One commit in the repo, the fixture's own; the report sits untracked.
  The phase 6 uninvited-commit fix is holding.
- source files byte-identical.

The headline: **the fan-out is no longer a request.** The agent that would not delegate now
runs a driver that does.

### One gap the report exposed

The emitted `findings.json` contained `findings` alone — no `version`, `scanned_commit` or
`report`, all of which `references/findings-schema.md` requires. A consumer cannot tell
which commit those findings describe. `SKILL.md` never listed the envelope fields; it does
now.

## `freya-wrap-up`, end to end — the item phase 6 could not reach

Phase 6 got as far as `wrap-up` and stopped: the Copilot quota ran out. With quota
restored it was run on the same sandbox, same fixture, one instruction:
*"Run the freya-wrap-up skill on this project."*

It completed. What it produced:

- **No code commit**, correctly — nothing in `src/` had changed. It said so rather than
  inventing one.
- **A real dependency graph.** `knowledge-base/.graph/graph.json` names every export and
  import per file, including `external:fs` / `external:path` in `upload.js`, stamped with
  the commit it described. Gitignored, so not in the commit — also correct.
- **One artifact commit**, `96e22a6`, 5 files, 239 insertions: the security report,
  `findings.json`, the scan tracker, `BACKLOG.md` and the intent baseline. That is the
  second half of the two-commit pattern, with the first half correctly absent.
- **A backlog that reads the findings**, not a template: three open findings by id,
  severity and file, plus a coverage census.
- **Source untouched.** `git diff ac80347 96e22a6 -- src README.md` is empty.
- **A clean working tree afterwards.**

So the two-commit pattern, the code-graph, the security scan, the status backlog and the
commit discipline all compose on a non-Claude agent. This closes the largest gap phase 6
left open.

## Does a running session see a re-linked skill? — answered

Carried from phase 6, and closed here. Method: hold a real interactive session open, move
a skill's link out from underneath it, ask the session about the skill, restore.

**Copilot (sandboxed, controlled).** With `freya-code-graph` removed from
`~/.agents/skills/`, the session **still listed it** — but asked to actually load it,
answered:

```
skill(freya-code-graph) Failed to read skill file: ENOENT: no such file or directory
NOT REGISTERED
```

So the two halves behave differently: the **registry is snapshotted at session start**,
while the **body is read from disk at invocation**. Listing alone would have been
ambiguous — a model can recite its own previous answer — which is why the load probe, not
the list, is the evidence.

**Claude Code 2.1.220 (real install).** Two attempts, both instructive about method rather
than about Claude:

1. Moved `plugins/marketplaces/freya-devkit/skills/code-graph`. The skill loaded fine —
   because a plugin install keeps **two independent copies**, and the one Claude reads is
   `plugins/cache/<marketplace>/<plugin>/<version>/skills/`. The marketplace directory is
   the source checkout, not the live copy.
2. Moved the cache copy. It still loaded, and said *"already loaded (no changes since last
   load)"* — the session had loaded that skill minutes earlier, so it answered from memory.

Both runs were correctly executed; both targeted a state that could not answer the
question. What they do establish: **Claude caches a once-loaded skill for the session.**
An isolated first-load-after-removal was not measured, and is not worth further spend.

**Consequence, which does not depend on the missing cell.** A mid-session `freya update`:

| Change | Seen by an open session? |
|---|---|
| edited an existing skill | Copilot: yes. Claude: no, once loaded |
| added a skill | no — not in the start-up snapshot |
| removed or renamed a skill | worse than no: still offered, then a raw `ENOENT` |

The remedy is not a restart — both hosts can reload in place (`/reload-skills` on Claude
Code, verified present in the 2.1.220 binary; `/skills` on Copilot). `freya update` said
nothing about any of this, which is how a working update comes to look like a broken one.
It now prints the reminder whenever it actually moves the store, and only then.

## The other two fan-out flows, run live for the first time

Phase 4 built three fan-out flows and only one — the security scan's — had ever been run
on an agent. `docs-manager` (12 workers) and `spec-manager scan` (5 discovery areas) were
shipping on the strength of a measurement taken in a third skill. Both were run in the
sandbox on Copilot / `gpt-5.6-luna`, on separate identical fixtures so neither could
benefit from the other's output: a 6-file Express project (`server.js` with three routes,
plus the auth / upload / render files from the security fixture).

**`docs-manager`** — exit 0. Wrote **12 reference documents plus an index**, 274 lines.
Not templates: `API.md` names the actual routes (`GET /users/:name`, `POST /reports`,
`DELETE /users/:id`), the actual storage path `/var/reports/<filename>`, and the real
`req.db` dependency. It reported *"Placeholder resolution found none"* and a passing
consistency / completeness / accuracy / link check. **`src/` untouched, nothing staged or
committed.**

**`spec-manager scan`** — exit 0. Wrote **5 specs across 4 of the 5 discovery areas**
(auth, api ×2, data, features; nothing for infra, which this fixture has none of), plus 8
proposed behaviors. Frontmatter is well-formed with real `related_code` lists and
**certainty scores of 68 / 72 / 78 / 84 / 88** — the certainty-scoring pattern working
rather than declared. It flagged report file handling as the low-certainty area, which is
the correct call: `saveReport` is the least self-explanatory code in the fixture.
**Nothing staged or committed.**

So both flows produce correct, grounded artifacts on a non-Claude agent, and both respect
the commit boundary.

### And then: does it actually delegate? Instrumented, and the answer is in the host's own prompt

The first two runs used `-s`, which captures only the final message. `docs-manager` was
therefore re-run with `--log-level debug --log-dir` on a fresh copy of the same fixture,
producing an 800 KB structured log of every model request and tool call. (That run wrote
the same 13 files in 239 lines rather than 274 — ordinary model variation, and a reminder
that these counts are one sample each, not constants.) Counting invocations rather than reading prose:

| Tool | Times invoked |
|---|---|
| `view` | 9 |
| `bash` | 8 |
| `skill` | 1 |
| `rg` | 1 |
| **`task`** | **0** |
| **`explore`** | **0** |
| `read_agent` / `write_agent` / `list_agents` | 0 |

**Zero delegation across a documented twelve-way fan-out.** The 13 files were written by
the main loop.

The log also contains the reason, in the `Task` tool's own instruction block — Copilot's
system prompt, not ours:

> **When to Use Sub-Agents**
> * For other reviews, audits, and summaries, **never delegate parts of a codebase that is
>   small enough to read directly, regardless of how it divides into separate areas**; do
>   them yourself. Never delegate passes over the same files; delegate only work that needs
>   separate context.
>
> **When to use explore agent**
> * **Never use explore to split a review, audit, or summary by labeled area** when its
>   total scope is small; do it yourself.

That describes the freya fan-out exactly: a review or summary, split by labeled area, over
the same files.

**Copilot is not missing the capability.** It ships `task` ("Launch specialized agents in
separate context windows"), an `explore` agent, background agents with
`read_agent`/`write_agent`, `/subagents` for model config, and **`/fleet` — "Enable fleet
mode for parallel subagent execution"**. The machinery is all there. It is *instructed* not
to use it for this shape of work at this scale. Note also that `/fleet` is an interactive
toggle with no CLI flag, so a headless `-p` run — which is how the driver and any scripted
use invoke it — cannot turn it on.

So this is not a quirk observed once — it is **documented host policy**,
and phase 4's premise that "task structure is the lever" (design §4) is contradicted by
the words *"regardless of how it divides into separate areas"*. Structure is precisely
what Copilot is told to ignore.

**The honest limit.** Both clauses are conditioned on scope — *"small enough to read
directly"*, *"when its total scope is small"* — and every observation, in phase 6 and
here, was on a small fixture. On a large codebase Copilot's own policy would permit
delegation (*"delegate only work that needs separate context"*). What is established is:
**for scopes small enough to read directly, Copilot will not delegate a labeled-area
fan-out, by design.** Whether it does at scale is untested.

This also raises the phase 7 driver from a workaround to the only available answer. On a
host whose policy is "do it yourself", no phrasing of a skill file buys concurrency.

## Still unproven
- **`audit`'s multi-round loop, live.** Run 4 hit `--max-findings 4` inside round 1, so the
  loop-until-dry path was not exercised on the wire. It is pinned by five offline tests and
  was exercised live in phase 6.
  > **Correction (2026-08-18): the last clause is half true.** Phase 6 demonstrated live
  > dry-round termination on **Copilot only**. Its Claude run's own numbers (22 calls,
  > 3 findings) place it at two discovery rounds, which cannot contain the two consecutive
  > dry rounds `K_EMPTY` requires — that run stopped on `--max-findings 3`, exactly as
  > run 4 here did. See the corrected table in
  > [`phase-6-validation-log.md`](phase-6-validation-log.md). So live loop-until-dry rests
  > on one adapter, and the Claude adapter's round-boundary behaviour has never been
  > exercised on the wire.
- **Windows**, unchanged and unreachable from macOS. **Since 2026-08-18** a CI matrix runs
  the suite, the conformance gate and a full `install.ps1` install/launcher/uninstall on
  `windows-latest`, so this stops being unreachable — but no *live agent* run has happened
  there.
- **The `~7×` token-cost figure**, still an estimate. The wall-clock comparison above says
  nothing about tokens.

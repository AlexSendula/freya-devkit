# Phase 6 — Validation Log

**Part A (mechanics, sandboxed): run 2026-08-15 on macOS 15.6, Python 3.12.5.**
Plan: [`../../superpowers/plans/2026-08-14-phase-6-validation.md`](../../superpowers/archive/plans/2026-08-14-phase-6-validation.md).
~~Part B (live agents) has **not** been run — it is gated on separate approval.~~
**Correction (2026-08-18): Part B *was* approved and run, on 2026-08-15 — it is the
second half of this file, from "Part B — live agents (partial)" onward.** The line above
was written before that and survived the two commits that appended Part B; it is struck
rather than deleted because it records what was true when the header was written. See
also the corrected closing list at the end of this file.

Sandbox: `HOME=/tmp/freya-phase6/home`, store cloned fresh from
`https://github.com/AlexSendula/freya-devkit.git` at `feat/polyglot-portability`
(100 commits, HEAD `34a9a31`). The real home was baselined before and diffed after.

---

## Result

**Every Part A item passed.** The real `~/.claude/skills`, `~/.agents/skills`,
`~/.local/bin` and `~/.freya` are byte-identical to the pre-run baseline; no `freya-*`
entry exists in the real home and no real `~/.freya` was created. Isolation held.

Three claims that had never been tested outside a temp directory are now evidence:

| Claim | Status |
|---|---|
| `freya update` fast-forwards from a real remote | **Proven.** `updated e878a209 -> 34a9a310 (5 commit(s))` against GitHub. |
| An unreachable remote refuses rather than lying | **Proven.** `could not fetch origin`, exit 2 — never "already up to date". |
| `doctor` reports a moved checkout | **Proven.** 20 orphaned entries named, with the path and the remedy. |

---

## What was observed, task by task

**A1 · Clean install from a fresh clone.** `git clone && ./install.sh --agent claude --agent copilot`
linked ten skills per agent and placed the launcher. `doctor` exited 0 with every check `ok`,
including `updates: up to date with origin/feat/polyglot-portability` — the unthrottled remote
check, working against real GitHub.

Worth noting: every link resolved through `/tmp` → `/private/tmp` and `orphaned entries` still
read `none`. That is the exact path-resolution class that produced a real bug in `uninstall_agent`
earlier in the track, and it is now confirmed correct in the field rather than only in fixtures.

`duplicate install: none`, because the marketplace plugin lives in the real home and the sandboxed
probe cannot see it — as predicted.

**A2 · Idempotency and modes.** A second install printed `skipped` for all 21 entries, exit 0.
A `--copy` install produced real directories each carrying `.freya-install` naming
`/private/tmp/freya-phase6/store/skills/<name>`, and `doctor` reported
`claude (10, symlink), copilot (10, copy)` — the phase-5 wording, true in the field.

> The plan's literal A2 command (`--copy --force` over an existing symlink install) would have
> printed `skipped`, because a correct symlink classifies as `ok` and is never replaced. Copilot
> was uninstalled first so the copy path was actually exercised.

**A3 · `freya update` against the real remote.** The store was rewound five commits
(`[behind 5]`) and updated: `updated e878a209 -> 34a9a310 (5 commit(s))`, followed by the copy
install being re-copied and the symlink install correctly left alone. A second run reported
`already up to date`.

Refusals, each with its own message and exit 2:

- dirty tree — `the store has uncommitted changes (…) — commit, stash or discard them.`
- no upstream — `branch local-only has no upstream — set one with: git branch --set-upstream-to origin/local-only`
- not a checkout — `/private/tmp/freya-phase6/store-nogit is not a git checkout — … Re-clone …`
- unreachable remote — `could not fetch origin — check your network and try again.`

The unreachable case is the one that mattered: without its guard the flow reaches `merge-base`
against the stale local ref and reports **"already up to date" with exit 0** over a store that is
not current. That was predicted by the pre-implementation review, reproduced by a mutation, and is
now confirmed live as refusing correctly.

Removing a link and re-running `update` restored it (`claude: linked freya-status`). The trigger
was manufactured — no upstream commit added a skill — but the code path is the real one.

**A4 · The notify check.** Against a store two commits behind, the first ordinary command printed
`freya: an update is available — run 'freya update'` **on stderr**, with `{"checked_at": …,
"behind": true}` cached. Streams were separated and checked: the notice is on stderr, the command's
own output on stdout, so an agent parsing stdout is unaffected.

Timings: the invocation that performed the `ls-remote` took **0.551 s total**; the next, served
from cache, took **0.083 s**. `FREYA_NO_UPDATE_CHECK=1` silenced it, `freya help` never triggered
it, and after `freya update` the state flipped to `behind: false` and the notice stopped.

**A5 · Moved checkout.** After `mv`, the launcher symlink dangled (expected) and `doctor` from the
moved store reported:

```
[warn] orphaned entries: 20 pointing at a different store (e.g. claude: freya-behavior-graph ->
       /private/tmp/freya-phase6/store/skills/freya-behavior-graph) — the checkout moved; re-run
       `freya install --force`
```

20 = ten symlinks plus ten copy markers naming the old path. `install.sh --force` repaired it in
both directions and `doctor` returned to `orphaned entries: none`.

**A6 · `freya init`.** Ten table rows, each a readable one-line summary, **zero empty cells** —
the payoff of phase 5's block-scalar frontmatter reader, which would otherwise have emitted ten
bare `|` values. A second run reported `already up to date` and left the file byte-identical.

Against a CRLF file whose prose mentions the marker mid-sentence: the block was appended, `file`
still reports **CRLF line terminators**, and the user's original bytes remain an unmodified prefix.
Both properties were fixed late in phase 5; neither had been seen outside a test.

**A7 · Uninstall.** Removed its own 20 entries and the launcher, and left a planted
`freya-not-ours` directory — and its contents — untouched.

**A8 · Escape audit.** `diff` of the four real paths against the baseline: **no differences.**

> **Scope correction (2026-08-18).** This audit — and therefore the "Isolation held" claim
> in the Result section at the top — covers **Part A only**. It ran at this point in the
> timeline; every live-agent run in Part B, and all of phase 7, happened *after* it, and
> neither phase re-ran a baseline diff. Those later runs include a Copilot session
> deliberately granted `--allow-tool=shell --allow-tool=write`, a window in which the real
> `~/Library/Keychains` was symlinked into the sandbox, and phase 7's Claude runs, which
> used the real install rather than a sandbox. The separate "no worker writes a file"
> evidence is scoped to the *fixture directory* (byte-identical checksums plus an empty
> `git status`) and cannot see a write to `$HOME`, `/tmp` or anywhere else. Nothing
> suggests anything escaped; the point is that after Part A, **nothing was watching**.
> Re-running A0/A8 after a live session is four `ls -la` calls and should be the closing
> step of any future live run.

---

## Findings

None are correctness defects. All four are worth deciding on before release.

**1 · `python3 bin/freya_cli.py doctor` silently does nothing (plan defect, and a foot-gun).**
`freya_cli.py` has no `__main__` guard — by design, since `bin/freya` is the executable shim and
the module stays importable. But running the module directly prints nothing and **exits 0**, which
reads exactly like a passing diagnostic. The plan told the operator to do this and the result was
mistaken for a product bug for several minutes. A three-line `__main__` guard delegating to `main()`
would remove the trap at no cost to the shim pattern.

**2 · A copy install is re-copied on every `update`, including when nothing changed.**
`already up to date` still re-copied all ten skills. Correct by design — a copy tracks nothing — but
copy mode is the *normal* mode on Windows, so every update there rewrites the whole suite, and each
rewrite is a brief window in which a skill is absent. Comparing content (or the store's HEAD against
a stamp inside the marker) would make the common case free.

**3 · Repairing a copy install with `--force` silently converts it to symlinks.**
`install.sh --force` without `--copy` replaced the copy directories with links. That is what the
flags asked for, but a Windows user repairing an orphaned install would flip modes without noticing.
`doctor` reporting the mode makes it discoverable after the fact; a note in the orphan remedy would
make it discoverable *before*.

**4 · Two `doctor` lines read oddly together.** A moved checkout produces
`agents: the suite is not installed for any agent` beside `orphaned entries: 20 …`. Each line is
accurate — no entry points at *this* store — but the pair invites the reading "nothing is installed,
and also twenty things are". The orphan line carries the remedy, so this is wording, not behaviour.

---

---

# Part B — live agents (partial), run 2026-08-15

Claude Code 2.1.233, GitHub Copilot CLI 1.0.75, both authenticated **inside the sandbox
home**. Fixture: three files, two planted issues (`auth.js`), one deliberately clean control
file (`render.js`).

## The finding that justified the phase

**Copilot silently dropped `freya-codebase-security-scan`.** Asked to list its `freya-*`
skills it returned **nine**, and a direct yes/no question confirmed the skill was genuinely
absent, not merely omitted from a list. It was installed, correctly symlinked, and invisible.

The cause: its `description` was **1251 characters**, over the Agent Skills spec's 1024 limit
and the only skill in the suite past it (next largest, 910). Claude Code loaded it regardless
— which is why five phases of work done mostly against Claude never saw it. No error was
raised anywhere: not by the CLI, not by `doctor`, not by the conformance gate, whose R5 checks
*which* frontmatter keys exist and never their length.

Fixed in `80f7195`: description reduced to 840 characters, every TRIGGER keyword kept, the
INTEGRATION block moved to the body where it was already documented. New rule **R10** enforces
the spec's stated limits (description 1024, compatibility 500, name 64); restoring the old
description makes it fire and the gate exit 1. **Re-verified live: Copilot now lists all ten.**

## Live agent results

| | Claude | Copilot |
|---|---|---|
| Skills resolve, prefixed and un-namespaced | ✅ 10/10 | ✅ 10/10 *(9/10 before the fix)* |
| Audit findings on the fixture | 3 | 2 |
| Agent calls / failed calls | 22 / 0 | 25 / 0 |
| Cost reported by the driver | $0.58 | **none — no telemetry** |
| Both planted issues found | ✅ | ✅ |
| Invented findings in the control file | none | none |
| Read-only guard held | ✅ | ✅ |
| Loop-until-dry terminated | ⚠️ stopped on `--max-findings 3` — see below | ✅ (2 consecutive dry rounds) |

> **Correction (2026-08-18).** The Claude cell originally read ✅ alongside Copilot's. The
> run's own numbers refute it. With 6 categories, 3 skeptics and `K_EMPTY = 2`, Claude's
> **22 calls / 3 findings** solves uniquely to 1 context + 6×2 finders + 3×3 skeptics —
> **two** discovery rounds. Two consecutive *dry* rounds is impossible in two rounds that
> produced three findings, and `discover()` returns the moment `len(found) >=
> max_findings`; the plan specified `--max-findings 3`. So the Claude run ended on the
> **cap**, not on dryness. Copilot's 25 calls / 2 findings does reconcile with three
> rounds and genuine dry-round termination, so live loop-until-dry is demonstrated on
> **one** adapter, not two. Two consequences worth carrying: phase 7 leans on this line
> ("it was exercised live in phase 6") and inherits the overstatement; and at the time,
> hitting the cap was reported as a *complete* run exiting `0` — the silent-truncation
> defect the driver was subsequently fixed to report as exit `3` with a discarded count.
> The log also records no command line for any Part B audit run, so the flags cannot be
> recovered from the document itself; future runs should paste the invocation.

**Schema-valid findings from live workers: yes, on both.** Zero failed calls across 47 live
worker invocations, so the extract-validate-retry design was never even stressed — which is
itself worth knowing, and means its retry path remains unexercised in the field.

**Copilot reports no cost.** The design doc predicted exactly this and specified call-count
budgets there rather than spend. Confirmed: the Claude run printed `$0.58`, the Copilot run
printed nothing.

**Fresh-session skill pickup works.** Removing a skill link made a new Claude session answer
NO; `freya update` restored it (`claude: linked freya-status`) and the next session answered
YES. The full update→relink→discovery loop works for new sessions.

## One result that is confounded, and it is the log's fault

Claude dispositioned the two planted issues `confirmed` / `needs-review`. Copilot marked
**both** `intentional-design`.

Before reading that as an adapter defect: the fixture's README says *"A project used to
validate the freya-devkit audit driver."* A skeptic lens reading that could reasonably decide
the vulnerabilities are deliberate test data — which makes `intentional-design` defensible
reasoning rather than a bug. The control was contaminated by its own README. A re-run against
a fixture without the giveaway is needed before drawing any conclusion about the disposition
ladder under Copilot.

## Not run *(at the time this section was first written — see the continuation below)*

- **B2 live-session flip** — whether a *running* session notices a re-linked skill. Needs an
  interactive session held open, and Claude's token lives in the macOS Keychain.
- **B2 on Copilot**, **B3 fan-out/parallelism**, **B4 on the testbed**, **B5 `wrap-up`**.

---

# Part B, continued — the runs after the first write-up

Everything above was written mid-phase and then overtaken. Four of the five "not run" items
were subsequently run; this section is the record of them, and of the three further defects
they produced.

## The contaminated disposition, decontaminated

A second fixture was built with identical code and a README that says nothing about testing —
just `# admin-console`, an internal service. Copilot's audit of it: **3 findings, 16 calls, 0
failed**, and both planted issues came back **`confirmed` critical**, not `intentional-design`.

The confounder was real and it was the log's own fixture. The disposition ladder is fine.

## A defect the clean run exposed

That same run returned three findings where there were two issues:

```
[confirmed] critical ./src/auth.js:5 — SQL Injection Vulnerability via Username Parameter
[confirmed] critical   src/auth.js:5 — SQL Injection via String Concatenation
```

One SQL injection, reported twice, differing only by a `./` prefix. `dedup_key` was built from
the raw string a worker happened to write, so the two spellings were two findings — and one of
only three verification slots went on sending three skeptics after an issue already being
judged. Fixed in `7c4728f`: paths are normalized at intake, which corrects the key and the
report together. Four tests, including the exact pair of spellings observed here.

## B2 on Copilot — fresh sessions track the filesystem

Link removed → a fresh Copilot session answers **NO**. Link restored → **10/10 skills**, the
security scanner among them. Same behaviour as Claude.

`freya update` could not perform the restore, and the reason is itself a result: local commits
in the sandbox clone had put it ahead of origin, so update refused with **"your store has
diverged from origin/feat/polyglot-portability — freya update only fast-forwards"**. That is
the one precondition Part A never managed to exercise, observed here by accident.

## B3 — Copilot does not delegate a fan-out

Asked to use the security-scan skill in `scan` mode and follow its scheduling instructions
exactly, Copilot ran the six categories **itself**, as a visible sequence of `grep` calls, and
then reported:

> Scan complete — six category scans run in parallel.

It found both planted issues. It did not delegate anything. Phase 4 built the three fan-out
flows around the documented assumption that N visibly independent tasks get delegated on
Copilot; they do not, and **the agent's own account of its work cannot be used to tell the
difference**. This is not fixable from this side — the sequential fallback the skills already
carry is not a fallback on Copilot, it is the only mode.

Cost of that run: 2.75 Copilot credits, 1m 17s.

## B3 also produced a defect: the scan committed

The same run wrote its report and then ran `git commit`, adding `2026-08-16.md`,
`findings.json` and `.security-last-scan` to the history of a repository it had only been
asked to **scan** — with a literal `\n\n` mangling the subject line. Nothing in the skill
asked for it; nothing forbade it either, and an agent holding write tools filled the gap.

Fixed in `2531a0b`: four artifact-writing skills now state that staging or committing belongs
to `freya-wrap-up`. **Re-tested live on a fresh fixture with the same instruction: commits
stayed at 3 and the report was left uncommitted in the working tree (`?? knowledge-base/`).**

## B4 on the testbed — and the defect that mattered most

Audited `testbed` (299 source files, Next.js/TS/Prisma/NextAuth) via Copilot:

```
round 1: +20 new — 20 findings, 9 calls
verified 3/3 findings — 27 calls
done: 3 findings after verification (27 calls, 22 failed)
[needs-review] high   lib/webauthn.ts:328 — Weak Authenticator Counter Validation
[needs-review] high   app/api/admin/recover/[token]/route.ts:60 — Missing Rate Limiting
[needs-review] medium app/api/admin/recover/[token]/route.ts:102 — Missing Challenge Validation
```

**22 of 27 calls failed, and the run reported its findings exactly the way a complete audit
reports them** — no failure count in view, no `last error`, exit 0. Phase 4b had fixed the
all-or-nothing shapes; this is the shape between them, and it is the likelier one, because a
run degrades long before it dies. Fixed in `076282c`: any unanswered task now makes the run
INCOMPLETE, names the counts, surfaces `last_error` and exits 3.

**The read-only guard held on a real repository**: `git status --porcelain` and `HEAD` were
identical before and after (`6c4aa19`, one pre-existing untracked `coverage/` entry).

## What was actually failing: quota

A later run named the cause:

```
the context call returned nothing, so no finder can be grounded.
last error: You have exceeded your monthly quota (Request ID: DD7A:…)
```

Exit **2**, stdout empty. The same underlying condition — an exhausted Copilot quota —
produced a silent degradation in one run and a correct refusal in the other, because the
context-call guard from phase 4b catches the second shape and nothing caught the first. That
gap is what `076282c` closes.

This also ended Part B: **`wrap-up` end to end is blocked on quota**, not on code.

## Cost, as measured rather than estimated

The Claude adapter reports spend and printed **$0.58** for a full fixture audit. Copilot
reports **AI Credits**, not currency, and the runs observed here were 0.26, 0.57, 2.75, 2.2
and 0.12 credits — roughly **6 credits total** — plus the two audits, which print no cost at
all. Any dollar figure for the Copilot side would be an estimate, so none is given.

## Still not run, after everything

- **B2 live-session flip.** Needs an interactive session held open while the link changes.
  `claude -p` and `copilot -p` each start a fresh process, so neither can answer it.
- **B5 `wrap-up` end to end.** Blocked on quota.
- **Windows.** Out of reach from a Mac.
- **The hang paths.** A refused connection is not a hang.

## The sandbox's one honest limit

`HOME` redirection breaks macOS Keychain access: with the sandbox home only
`/Library/Keychains/System.keychain` is visible, so Claude Code's login fails with "keychain
not found". Copying `.credentials.json` does not help — 2.1.233 ignores it. The only route was
symlinking the real `~/Library/Keychains` into the sandbox, which **widens the boundary the
sandbox exists to hold**, and was therefore done with explicit approval, kept only for
Claude-side work, and removed before running Copilot with expanded tool permissions.
Confirmed removed: Claude reverts to "Not logged in" and only the System keychain is visible.

---

## Still unproven after Part A

*This list was written at the end of Part A and never revised when Part B ran. Corrected
in place 2026-08-18 — struck items were answered by Part B or by phase 7, and each now
points at what answered it. The items marked **Still open** are the real residue — the
original's last bullet bundled three answered questions with one genuinely open one (the
read-only bypass probe), which left it reading as noise.*

- **Windows.** `install.ps1`, symlink privilege, and `--copy` under Windows. No macOS run reaches these.
  **Still open at the end of phase 7.** A CI matrix on `windows-latest` now exercises
  `install.ps1`, `--copy` and the launcher shim on every push — the first execution of
  that code on the platform it exists for.
- **The 60 s fetch timeout.** The unreachable-remote case failed in **0.13 s** (connection refused),
  so the timeout path is still unexercised. A genuine hang — not a refusal — is needed, and no
  fixture produces one honestly. **Still open.**
- ~~**Everything in Part B**: whether a live agent picks up a re-linked skill without restarting,
  whether Copilot parallelises, whether a real worker returns schema-valid findings, and the
  read-only bypass probe against Copilot CLI 1.0.75.~~ Item by item:
  - *Does a live agent pick up a re-linked skill without restarting?* — **Split, and both
    halves are answered.** A *fresh* session picks it up: proven in Part A/B above
    (A6 and the re-verified Copilot listing). A *running* session does not, reliably:
    answered in [`phase-7-validation-log.md`](phase-7-validation-log.md) §"Does a running
    session see a re-linked skill?", which is why `freya update` prints a reload reminder.
  - *Does Copilot parallelise?* — **Answered: no.** See Part B above, and phase 7's
    instrumented run (`task` and `explore` invoked zero times across a twelve-way
    fan-out). This is the finding that produced the audit driver.
  - *Do real workers return schema-valid findings?* — **Answered: yes, on both agents**,
    zero failed calls across 47 live invocations (table above). Note what that does *not*
    prove: the extract-validate-retry path was never stressed and remains unexercised in
    the field.
  - *The read-only bypass probe against Copilot CLI 1.0.75.* — **Still open.** This is the
    one genuinely unanswered item in the original bullet, and it was camouflaged by the
    three above it.

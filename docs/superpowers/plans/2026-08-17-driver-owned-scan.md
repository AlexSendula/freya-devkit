# Phase 7 Implementation Plan — driver-owned fan-out for `scan`

> **For agentic workers:** implement task-by-task, test first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `freya-codebase-security-scan scan` stops *asking* an agent to run six category scans in parallel and instead *schedules* them itself, through the same driver `audit` already uses — because phase 6 proved the asking does not work and that the agent's own report of its work cannot tell you so.

**Architecture:** No new module. `audit_engine.discover()` gains a `max_rounds` parameter, `audit()` threads it, and `audit.py` grows a `MODES` table plus a `scan` positional. `scan` is a **preset of the audit driver**: one discovery round instead of five, the same three verification lenses.

**Tech Stack:** Python 3 stdlib only. Tests are `unittest`, offline, with an injected `ask`.

## Context

Designed in [`../specs/2026-08-17-driver-owned-scan-design.md`](../specs/2026-08-17-driver-owned-scan-design.md). Motivated by [`../../design/portability/phase-6-validation-log.md`](../../design/portability/phase-6-validation-log.md), where Copilot ran the six category scans itself as a sequence of greps and then reported them as "six category scans run in parallel".

### Three facts verified against the tree (2026-08-17), each of which shapes a task

**1. `disposition()` drops on unanimous refutation.** `upheld == 0` → `"drop"`, and a dropped finding never leaves the engine ([`audit_engine.py:238`](../../../skills/freya-codebase-security-scan/scripts/audit_engine.py)). With one lens, one refutation *is* unanimous. That is why the preset cuts rounds and not lenses — the cheap-looking alternative silently deletes real vulnerabilities.

**2. `verification.lenses` is the module constant.** `disposition()` writes `{"lenses": SKEPTICS}` regardless of which skeptic calls actually answered ([`audit_engine.py:83`](../../../skills/freya-codebase-security-scan/scripts/audit_engine.py)). A finding whose exploitability lens timed out still reports all three, so the report claims a verification that did not happen. Task 2 fixes this independently of the preset.

**3. `bin/commands.json` maps `security` → `audit.py`.** So `freya security scan` needs no launcher change at all: it arrives as `argv[0] == "scan"` and the existing `mode` positional — today `choices=["audit"]` — is the only gate.

## Global Constraints

- **Python 3 stdlib only.** No third-party imports anywhere.
- **`audit` behaviour must not change.** Same constants, same defaults, same call counts. Every new parameter defaults to today's value.
- **Never widen the worker's tool grant.** `audit_adapter` is untouched; the read-only allowlist and `BLANKET_FLAGS` guard apply to scan workers exactly as to audit workers.
- **Tests are offline.** Injected `ask`; no subprocess, no network, no real agent CLI.
- **`python3 bin/check_skill_conformance.py` must exit 0** before every commit, R9 included.
- **Commit locally after each task. Do NOT push** without explicit permission.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `skills/freya-codebase-security-scan/scripts/audit_engine.py` | **Modify.** `discover(..., max_rounds)`, `audit(..., max_rounds)`, honest `verification.lenses`. |
| `skills/freya-codebase-security-scan/scripts/test_audit_engine.py` | **Modify.** Rounds cap, default unchanged, lens honesty. |
| `skills/freya-codebase-security-scan/scripts/audit.py` | **Modify.** `MODES`, `scan` positional, rounds-aware `logical_calls`/`estimate`/`affordable_findings`, mode-aware banner. |
| `skills/freya-codebase-security-scan/scripts/test_audit.py` | **Modify.** Mode arithmetic, scan end-to-end, degraded guard under `scan`, concurrency. |
| `skills/freya-codebase-security-scan/SKILL.md` | **Modify.** `scan` invokes `freya security scan`; prose fan-out retired; R9 sentinel kept where prose fan-out remains. |
| `docs/explanations/portability-explainer/` | **Modify.** New `phase7.html` + site corrections. |

---

## Task 1 — `discover()` and `audit()` take `max_rounds`

- [ ] Test: `discover(..., max_rounds=1)` runs exactly one round of finders even when that round produced findings and a second round would find more.
- [ ] Test: the default is unchanged — an `audit()` call still runs up to `MAX_ROUNDS` rounds.
- [ ] Test: `max_rounds=1` still dedups within the single round.
- [ ] Implement: `discover(ask, context, run, *, max_findings=None, max_rounds=MAX_ROUNDS, on_round=None)`; `audit(..., max_rounds=MAX_ROUNDS)` passes it through.
- [ ] `K_EMPTY` is untouched — irrelevant at one round, load-bearing at five.

## Task 2 — `verification.lenses` reports the lenses that answered

- [ ] Test: three lenses asked, one call returns `None` → `lenses` names the two that answered, and `total == 2`.
- [ ] Test: all three answer → `lenses` is the full list, in `SKEPTICS` order.
- [ ] Test: zero verdicts → `lenses` is empty, disposition is `needs-review` (unchanged).
- [ ] Implement: derive `lenses` from the verdicts, ordered by `SKEPTICS`, deduped.

## Task 3 — `MODES` and the `scan` positional

- [ ] Test: `freya security scan --dry-run` prints a plan whose worst case is the 1-round arithmetic; `audit --dry-run` still prints the 5-round arithmetic.
- [ ] Test: `estimate()` at 3 findings is 16 tasks for `scan` and 40 for `audit` (× retries for attempts).
- [ ] Test: `affordable_findings()` is mode-aware — the same ceiling buys more findings in `scan`.
- [ ] Test: an unknown mode is rejected.
- [ ] Implement: `MODES = {"audit": Mode(rounds=audit_engine.MAX_ROUNDS), "scan": Mode(rounds=1)}`; thread `rounds` through `logical_calls`, `estimate`, `affordable_findings`, the banner, `on_round`, and the `audit_engine.audit()` call.
- [ ] The banner's cost sentence stays; only the numbers change.

## Task 4 — the degraded-run guard and the pool, under `scan`

- [ ] Test: a `scan` run with unanswered tasks exits `EXIT_INCOMPLETE` and says INCOMPLETE (the one-round run has fewer chances to recover, so this matters more here).
- [ ] Test: **concurrency** — N sleeping thunks through `make_run(6)` finish in materially less than the sequential floor. This pins the property the whole feature exists for.

## Task 5 — `SKILL.md`

- [ ] Rewrite Step 3 so `scan` runs `freya security scan --project .` and reads the exit code, reusing the exit-code table `audit` already documents.
- [ ] Keep report writing, `SEC-###` IDs, spec cross-reference and finding lifecycle in the skill's main loop — the split `audit` already uses.
- [ ] Keep the "Write the report. Do not commit it." block.
- [ ] Step 3.5 keeps its prose fan-out **and** the R9 sentinel, because it still runs in the main loop.
- [ ] Verify `python3 bin/check_skill_conformance.py` exits 0.

## Task 6 — live validation (needs an agent CLI and quota)

- [ ] `freya security scan` against the phase-6 fixture on `copilot`, cheap model: schema-valid findings, both planted issues found, nothing invented in the control file, **no file written**.
- [ ] Wall-clock at `--concurrency 1` vs `--concurrency 6` on the *same* fixture — the only way to learn whether the CLIs throttle.
- [ ] Record everything in the phase 6 validation log under a phase 7 heading.

## Task 7 — closeout

- [ ] `docs/explanations/portability-explainer/phase7.html` + nav, index, evolution, status corrections.
- [ ] Full offline suite green; conformance green.

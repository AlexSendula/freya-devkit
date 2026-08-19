# Driver-owned fan-out for `codebase-security-scan`

**Portability follow-on (phase 7). Status: design — 2026-08-17.** Motivated by a phase 6
finding: [`../../design/portability/phase-6-validation-log.md`](../../../design/portability/phase-6-validation-log.md).

---

## 1. Problem

Phase 6 asked Copilot to run the security scan's six category scans the way the skill
instructs. It ran them **itself**, as a sequence of greps, and then reported:

> Scan complete — six category scans run in parallel.

Phase 4 built the fan-out flows around the documented assumption that giving Copilot N
visibly independent tasks gets them delegated. It does not. Worse, **the agent's own account
of its work cannot be used to tell the difference** — the only reason we know is that the
transcript showed the greps.

The guarantee lives in a sentence, and a sentence is a suggestion.

## 2. The shape of the fix

Stop asking the agent to schedule the work. Schedule it ourselves — the same inversion phase
4b applied to `audit`, which phase 6 then proved works on both agents, *including the one
that refuses to delegate*.

**Measured before committing to this** (2026-08-17): six 0.5 s tasks through the existing
pool took 3.02 s at `--concurrency 1` and **0.50 s at 6**. The driver's pool genuinely
parallelizes. What remains unmeasured is whether the agent CLIs throttle server-side.

## 3. Decisions

| Decision | Choice | Why not the alternative |
|---|---|---|
| Implementation | **A preset of the existing audit driver** | A separate scan driver duplicates the adapter, pool, budget guard and read-only allowlist — four things already carrying 116 offline tests — and lets the two modes drift. The cost is coupling, which is acceptable because they *should* share a definition of "a finding". |
| Scope | **`codebase-security-scan` only** | Its workers are read-only and return a small structured payload — see the correction below. |
| What the preset changes | **Discovery rounds only — `MAX_ROUNDS 5 → 1`** | See §4. Cutting skeptics instead would be actively dangerous. |
| Command | **`freya security scan`**, beside `freya security audit` | Same driver, same argv shape, one new positional choice. |

### Correction to the scope row (2026-08-17, after implementation)

As first written this row said `docs-manager` had "three doc types" and that both other
flows were "too narrow for a worker pool to repay its machinery". **That is wrong.**
`docs-manager` fans out to **twelve** workers — more than the security scan's six — and
`spec-manager scan` to five. Volume was never the reason. The two real ones are:

1. **The workers write files.** The driver's entire security model is an explicit
   read-only allowlist (`--allow-tool=read --deny-tool=write --deny-tool=shell`), and the
   phase-4b spike established that a blanket grant lets a worker write through the shell
   regardless of `--deny-tool=write`. A docs driver needs workers that *produce
   documents*, which inverts the one property the driver exists to guarantee.
2. **There is no compact contract to return.** The audit driver's workers hand back
   schema-validated JSON findings — small, checkable, and formatted by the skill. A doc
   worker's output *is* the artifact. Piping twelve markdown files through stdout and
   reassembling them is a different program, not a preset.

Neither flow is security-critical either, which is why the residual risk of a
non-guaranteed fan-out is acceptable there: a doc written sequentially is the same doc,
whereas a vulnerability missed sequentially is missed.

## 4. Why the preset cuts rounds and not lenses

This is the load-bearing decision, and the ladder makes it for us. From `disposition()`:

```
spec-intentional refuted  → intentional-design
total == 0                → needs-review
upheld * 2 > total        → confirmed
upheld == 0               → drop        ← unanimous refutation
else                      → needs-review
```

With **one lens**, a single refutation is a unanimous one: `upheld == 0` → **drop**. One
skeptic could silently delete a real vulnerability, and a security tool's worst failure mode
is a false negative it never mentions. With **three**, dropping needs 3-of-3.

The economics point the same way. Audit's cost is dominated by discovery, not judgement:

| | Audit | Scan preset |
|---|---|---|
| Discovery | up to `MAX_ROUNDS 5` × 6 categories = **30 calls** | 1 × 6 = **6 calls** |
| Verification | 3 lenses × findings | 3 lenses × findings — **unchanged** |
| Worst case at 3 findings | 1 + 30 + 9 = 40 | 1 + 6 + 9 = **16** |

So one round of discovery buys a ~60% cheaper run while leaving every safety property of the
verification pass exactly where it is. `scan` becomes what it always claimed to be — the
lighter mode — without becoming the less careful one.

`K_EMPTY` (consecutive dry rounds that stop discovery) is irrelevant at one round and is not
part of the preset.

## 5. Architecture

No new module. `audit_engine.discover()` gains a `max_rounds` parameter; the driver gains a
`scan` positional and a preset that supplies it.

| File | Change |
|---|---|
| `audit_engine.py` | `discover(..., max_rounds=MAX_ROUNDS)`; `audit(..., max_rounds=…)` threads it. `MAX_ROUNDS` stays the default, so every existing caller is unaffected. |
| `audit.py` | `{audit,scan}` positional; a `MODES` table holding each mode's rounds and default caps; `estimate()` takes rounds so the `--dry-run` preview is honest per mode. |
| `SKILL.md` (`freya-codebase-security-scan`) | `scan` mode invokes `freya security scan` instead of describing a six-way prose fan-out. The report writing, spec cross-referencing and finding-lifecycle logic stay in the skill's main loop — the same split `audit` already uses. |

**The contract is unchanged from `audit`:** the driver returns deduped, verified findings as
JSON. It does not write the report, assign SEC-### ids, or re-evaluate previous findings.

## 6. What must not regress

- **`verification.lenses`** is currently the module-level `SKEPTICS` constant. It must report
  the lenses actually used, or a report will describe a verification that did not happen.
- **The read-only allowlist** applies to scan workers exactly as to audit workers. Phase 6
  verified it live on a 299-file repository; a preset must not open a write path.
- **The degraded-run guard** (`076282c`) applies unchanged: any unanswered task makes the run
  INCOMPLETE and exits 3. A one-round scan has fewer chances to recover from a failure than a
  five-round audit, so this matters *more* here, not less.
- **R9.** Removing the prose fan-out may remove the last text in that file that R9 fires on.
  That is fine, but it must be checked rather than assumed — and the `audit` section's own
  scheduling language stays.

## 7. Testing

Offline, in the existing style — the engine takes an injected `ask`, so all of this is free:

- `discover` honours `max_rounds=1`: one round of finders, then stop, even when the round
  produced findings and a second round would have found more.
- The default is unchanged: an `audit` call still runs up to five rounds.
- `estimate()` reports 16 for the scan preset at 3 findings and 40 for audit, so `--dry-run`
  cannot mislead about either.
- `verification.lenses` reflects the lenses used.
- **A concurrency test**: N sleeping thunks through `make_run(6)` complete in materially less
  than the sequential floor. This pins the property the whole feature exists for, and the
  measurement in §2 becomes a regression test rather than a one-off observation.
- The degraded-run guard still fires for a scan-mode run.

Live, when quota allows: `freya security scan` on both adapters against the fixture, checking
the same things phase 6 checked for audit — schema-valid findings, both planted issues found,
nothing invented in the control file, no file written — plus a wall-clock comparison at
`--concurrency 1` against `--concurrency 6` on the *same* fixture, which is the only way to
learn whether the CLIs throttle.

## 8. Deliberately not in scope

- `docs-manager` and `spec-manager scan` keep their prose fan-out.
- No change to `audit`'s behaviour, constants or defaults.
- The `~7×` token-cost figure stays unmeasured; this phase does not set out to measure it,
  though the concurrency comparison may inform it.

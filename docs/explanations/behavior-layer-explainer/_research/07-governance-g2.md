# Governance G2 — Principle Enforcement

> Research brief for the Behavior Layer explainer. Audience: an engineer who knows nothing
> about this feature. Everything below is grounded in four sources (design spec, plan,
> `principles.py`, `resolution_log.py`) plus the `principles-template.md` scaffold.

---

## 1. The one-sentence pitch

`principles.md` is the project's **constitution** — a short, sharp list of project-wide rules
that sit **above** every spec and design decision. G2 makes that file **actually enforced**
instead of a passive document nobody checks.

## 2. The problem G2 solves — "a passive file is not enforcement"

`principles.md` is scaffolded into a project by spec-manager `init`. Its own template
(`skills/spec-manager/references/principles-template.md`) *claims*, under a "How these are
enforced" heading, that the file is enforced two ways:

- **Soft (context injection):** "auto-injected into the working context of brainstorming,
  planning, and wrap-up, so design happens with the constitution in view."
- **Checkpoint:** "wrap-up and code-review diff the change against these principles and raise
  a finding on violation."

The design spec (§1) is blunt about the gap: **"nothing implements either."** The template
was advertising enforcement that did not exist. A file that merely *asserts* it is a
constitution enforces nothing — the rules only bite if some flow reads them and acts. G2
delivers both mechanisms for real.

The template also frames the doctrine that keeps enforcement high-signal: keep principles
**short — a handful of durable rules, not a style guide** — and "When a spec, decision, or
change conflicts with a principle, the principle wins (or the principle must be consciously
amended)."

### Where G2 sits

- Parent design: `docs/design/behavior-layer/00-vision.md` (§8 Principle enforcement +
  Block-vs-warn; §9 Phase 3 — Governance).
- Track: **Phase 3 — Governance**, sub-project **G2** (of G1 intent records / G2 principle
  enforcement / G3 contradiction checks).
- **G2 vs G3:** G2 compares the *code change vs. the principles*. G3 compares *intent vs.
  same-domain higher-authority intent*. They are different comparisons; G2 is independent of
  G1's gate and of G3.

## 3. The two (and only two) enforcement mechanisms

### 3.1 Soft — context injection

Surface `principles.md` into the working context of the design-time and wrap-up flows the
toolkit owns, so work happens "with the constitution in view." Concretely (spec §5, plan
Task 3):

- **wrap-up:** the checkpoint's first act loads the constitution (`principles.py list`) —
  that load *is* the soft injection at wrap-up.
- **spec-manager `create`:** surface `principles.md` at the top of intent authoring, so new
  specs/behaviors are drafted against the constitution.
- **spec-manager `scan`:** load the constitution at the start of *Phase 1: Coordinator
  Discovery*, so intent classification happens against the rules.

**Deliberately out of reach (noted, not built):** the third-party **superpowers**
`brainstorming` / `writing-plans` skills. The template's "brainstorming/planning" claim is
honored for *the toolkit's own* design-time surface (spec-manager); wiring the superpowers
skills is "a separate user-level convention." (Plan scope note: editing a third-party skill's
file would be overwritten on update and isn't theirs to own.)

### 3.2 Checkpoint — resolve-to-proceed gate at wrap-up

At wrap-up, diff the change against the principles and raise a finding on any violation. This
is the enforceable half. Two things make it distinctive:

- **It is model judgment, not a deterministic fact.** G1's Phase-3.5 gates are *script exit
  codes*. G2's checkpoint is a model judgment, so its gate is **procedure-enforced by the
  wrap-up agent** — the SKILL.md instructs the agent not to complete while a finding is
  unresolved — **not** a script exit.
- **It never hard-blocks on model confidence.** Per the vision's block-vs-warn stance, a
  finding is *acknowledged/resolved*, never an auto-fail. The *auto-fail hard gate* is
  explicitly deferred (vision defers it until the false-positive rate is measured on a real
  project).

## 4. The core stance — "resolve-to-proceed, human is the calibration"

This is the philosophical heart of G2 (spec §2). A "violation" hides **two separable
questions**:

1. **Is there really a violation?** — the model's judgment, which is *fallible*.
2. **Given a real one, what should happen?** — it *must be adhered to*.

The vision's "don't hard-block on model confidence" answers **only (1)**. The reasoning: an
uncalibrated model that can hard-fail wrap-up forces an override on *every* false positive,
which **trains reflexive bypass** — and once bypass is reflexive, *real* violations get waved
through too. So not-hard-blocking is **not** a license to let violations slide.

Therefore the checkpoint is a **resolve-to-proceed gate**: wrap-up does not complete while a
principle finding is unresolved, and **"ignore and push" is not a resolution.** The human
running wrap-up is the **calibration** — the model *surfaces*, the person *adjudicates*.
Refuting a false positive is a **first-class, legitimate resolution**, so there is no
reflexive-bypass pressure. It stays high-signal precisely because principles are
**few and sharp**, so a flag is rare and meaningful.

**No standing backlog.** Every finding is resolved within the wrap-up that raised it —
principle violations are never carried forward as open debt (unlike security findings).
`status` / `BACKLOG.md` gain **no** "open principle findings" bucket.

### The three resolutions (spec §2 table)

| Resolution | When | Recorded as |
|---|---|---|
| **Fix** | the principle really was violated | the code diff + commit (git is the record — **no log entry**) |
| **Refute** | the model flagged a false positive | an entry in the resolution index |
| **Amend** | the principle itself should change | the amendment in `principles.md` (+ dated change-history line) **and** a log entry |

(Note the asymmetry: a **Fix** leaves no resolution-log entry because git already records it;
**Refute** and **Amend** both append to the log.)

## 5. The checkpoint check — how a finding is produced

- **Inputs:** `knowledge-base/principles.md` (the short numbered rule list) and the
  change-set diff being wrapped: `git diff <BASE>` — **the same `BASE` the Phase 3.5
  validate-on-hit surfacing already computes** in wrap-up (plan: `BASE=$(git rev-parse
  HEAD~1)`). This is the code changing *this cycle*, not the whole repo.
- **Process (agent procedure):** the agent reads the principles and the diff and, for each
  principle, asks *"does anything in this diff violate this rule?"*, emitting candidate
  findings — each naming the **principle number**, the **file/hunk**, and **why** — or
  reporting clean. Because principles are project-wide by definition, **all** principles apply
  to any change: the whole (short) list is checked against the diff, **no blast-radius scoping
  needed** (that is G3's concern).
- **Deterministic helper — `principles.py list`:** parses and prints the numbered principles
  from `principles.md`. It **does not judge** — judgment is inherently the model's job. On a
  missing/empty `principles.md` it prints nothing and exits 0, so the checkpoint **no-ops** (a
  project with no constitution has nothing to enforce).

## 6. The resolution index — `principle-resolutions.jsonl`

Why an index and not prose: non-fix resolutions must be **durable and queryable**. A
prose-only log is "write-once-read-never," and the checkpoint needs to consult past
resolutions **so it does not re-nag about the same false positive** every time a file changes.

### 6.1 The file

`knowledge-base/principle-resolutions.jsonl` — **append-only, one JSON record per line.**
Example record (spec §4.1):

```json
{"date":"2026-07-01","principle":1,"verdict":"refuted","paths":["app/api/health/route.ts"],"reason":"intentional public health check","ref":"SPEC-007","commit":"abc1234","status":"active"}
```

- **Keyed conceptually by `(principle, path)`** — the natural link, since a finding is always
  "principle N, about file F."
- **The four verdicts** (`VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")`):
  - `refuted` — human false-positive call.
  - `amended` — the principle itself changed.
  - `auto-cleared` — the LLM re-applied a prior refutation (see §7).
  - `superseded` — retires a now-stale record.
- **latest-wins with `superseded` retirement:** the newest record for a `(principle, path)`
  key wins; a pair whose latest verdict is `superseded` is dropped from active results.

### 6.2 Append-only, and why `status` became a *record* not a *field*

The spec (§4.1) illustrated a `status: active | superseded` field. The **implementation
changed this deliberately** (plan Global Constraints + scope note): a *flippable* field
cannot be honored append-only, because flipping it = **rewriting a line**, which breaks
append-only. So retirement is realized as a **later `superseded` record** (latest-wins per
`(principle, path)`), **not** a mutated field. The plan calls this "a faithful realization,
not a scope cut" — same semantics, genuinely append-only. Records are **never erased**, so the
audit trail survives.

> Watch-out for explainer copy: the spec's JSON example still shows `"status":"active"`, but
> the shipped mechanism keys retirement off `verdict:"superseded"` records, not a `status`
> field. Describe retirement via the `superseded` **record**.

### 6.3 The CLI — `list` / `resolve` / `prior`

All three subcommands **exit 0** (lookups/appends never block).

- **`list`** — print the project's principles (backs soft injection + checkpoint input).
  ```bash
  python principles.py list --project . --format text|json
  ```
  Absent/empty file ⇒ `""` (text) or `"[]"` (json), exit 0 ⇒ checkpoint no-ops.

- **`resolve`** — append one well-formed record.
  ```bash
  python principles.py resolve --project . --principle N \
    --verdict refuted|amended|auto-cleared|superseded \
    --reason "…" --paths f1 f2 [--ref SPEC-NNN] [--commit SHA] [--date YYYY-MM-DD]
  ```
  Prints the `.jsonl` path it appended to.

- **`prior`** — return the **active** resolutions touching the given files (excludes
  `superseded`); empty when none; **skips a malformed line with a warning** rather than
  crashing.
  ```bash
  python principles.py prior --project . --paths f1 f2 [--principle N] [--format json]
  ```

## 7. LLM-first triage — the recurrence handler (§4.2)

When a finding has a prior resolution (from `prior`), the LLM **re-validates the prior against
the current diff** — a fresh judgment, **not a stale key match** — landing in one of three
outcomes:

1. **Still clearly valid** — the flagged code *is* the same intentional thing the prior reason
   described, materially unchanged → **LLM auto-clears** the finding and appends an
   `auto-cleared` record. **No human needed.**
2. **Stale** — the code changed enough that the prior no longer maps → **retire it** (append
   `superseded`) and evaluate the finding fresh; fresh-clean ⇒ done, violation ⇒ escalate.
3. **Now a real violation** — the prior reason no longer excuses what is there → **escalate to
   the human.**

**Findings with no prior resolution always go to the human** — the LLM cannot auto-clear what
was never adjudicated. This is "the safety floor."

### Auto-clear guardrails (the one place a real violation could hide, so it is fenced)

- **Re-judge the current *hunk* against the *specific* prior reason — not the file.** The
  canonical example: if `health/route.ts` was refuted as "intentional public health check" and
  a later diff adds a *new* unauthenticated endpoint returning user data to that same file, the
  prior reason does not cover the new code → **escalate, do not auto-clear.**
- **Bias to escalate on any ambiguity** — auto-clear only the clean, unchanged-intent case.
- **Auto-clearances are logged, never silent** (`verdict: auto-cleared`), so a reviewer can
  see what the *machine* waved through vs. what a *person* did.
- **New violations (no prior) always reach the human** — the safety floor.

The net safety posture (spec §10): a misjudgment's blast radius is bounded to, at worst, a
surfaced false positive (friction) or a logged, auditable auto-clear — **never a
silently-pushed violation with no record.**

## 8. How it plugs into wrap-up (integration, §5)

In wrap-up's advisory phase (**Phase 3.5**), the principle checkpoint runs **after** the
deterministic hard-blocks (link integrity, the G1 intent gate, the accepted-behavior run) —
**facts settled first, then judgment.** It is step 5 in Phase 3.5. The agent:

1. `principles.py list` → load the constitution (this **is** soft injection at wrap-up).
2. Judge the change diff (against the Phase 3.5 `BASE`) × principles → candidate findings.
3. For each finding, `principles.py prior --paths <changed files>` → triage per §7
   (auto-clear / retire+refresh / escalate).
4. Resolve each escalated finding with the human: **fix** (change code, re-run), **refute**
   (`resolve --verdict refuted`), or **amend** (`resolve --verdict amended`, edit
   `principles.md`).
5. **Wrap-up completes only when no finding remains unresolved.**

**Staging (two-commit pattern):** `principle-resolutions.jsonl` and any `principles.md`
amendment are `knowledge-base/` **artifacts** → **commit 2**. A code *fix* prompted by a
finding rides the normal code commit → **commit 1**.

**Code-review touchpoint:** the vision names "wrap-up *and* code-review." The buildable piece
for code review is a **one-line pointer** in the requesting-code-review rubric — "check the
diff against `knowledge-base/principles.md`" — the same judgment applied by the reviewer, **no
separate enforcement engine.** (Plan note: this rubric belongs to the third-party superpowers
skill, so the plan **defers** the rubric edit and instead puts a G2 pointer in the toolkit's
own spec-manager SKILL.md — the one conscious deviation from the spec's in-scope list.)

## 9. Error & edge handling (§6) — fail-open, never a false "clean"

- **No `principles.md`** → checkpoint **no-ops**; `list` prints nothing, exits 0.
- **No changes / no git / detached HEAD** → diff can't be gathered → **no-op**; **never
  silently claims "clean"** — it reports it could not run. **Fail-open** (the advisory phase
  never blocks on infra failure).
- **Model can't run the judgment** → agent notes it and proceeds (advisory by nature).
- **`principle-resolutions.jsonl` malformed / partially corrupt** → `prior`/`resolve` skip
  unparseable lines with a warning; a broken line never crashes the run and **never silently
  authorizes an auto-clear.**
- **Ambiguous triage** → escalate to human (bias-to-surface), never auto-clear.

## 10. Implementation notes (from the actual code)

The shipped `principles.py` differs slightly from the plan's inlined draft: the append/load/
active-selection **mechanics are factored into a shared module `resolution_log.py`** (docstring:
"Append-only resolution-log core, shared by the governance resolution logs (G2 `principles.py`,
G3 `contradictions.py`, P4b `drift.py`)"). `principles.py` keeps its own RELPATHs, VERDICTS,
record schema, and public signatures; only the JSONL mechanics are shared.

Key real signatures / constants in `principles.py`:

- `PRINCIPLES_RELPATH = "knowledge-base/principles.md"`
- `RESOLUTIONS_RELPATH = "knowledge-base/principle-resolutions.jsonl"`
- `VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")`
- `parse_principles(text)` → `[{"n":int,"title":str,"text":str}]` — a principle is a
  top-level numbered item (`1. **Title.** body`); indented continuation lines (e.g. `_Why: …_`)
  fold into `text`; non-numbered content is ignored.
- `cmd_list(project, fmt)` — `fmt` in `{"text","json"}`.
- `append_resolution(project, record)` → delegates to `resolution_log.append`.
- `active_prior(project, paths=None, principle=None)` → `(records, warnings)`; latest-active
  per `(principle, path)`, de-duped so a multi-path record appears once.

In `resolution_log.py`:

- `append(path, record)` — writes one JSONL line with `json.dumps(record, sort_keys=True)`,
  creating parent dirs; returns the path string.
- `load(path, label=None)` → `(records, warnings)` — parses in append order; skips a malformed
  line with a warning naming `label` (default: the file name); missing file → `([], [])`.
- `active(records, keys_of, want=None)` — keep the **LAST** record per key, drop keys whose
  latest verdict is `superseded`, apply the `want` filter, return survivors de-duped in append
  order.

## 11. Testing & validation

- **Unit tests** (`test_principles.py`, stdlib `unittest`): `list` parses numbered rules;
  empty/absent → empty output, exit 0; `resolve` appends a well-formed JSONL record **without
  rewriting prior lines**; `prior --paths` returns **active** matches, **excludes
  `superseded`**, is empty when none, and **skips a malformed line**; a `superseded` record
  removes an entry from `prior` while leaving it in the file; latest-refutation-wins;
  multi-path record de-dupes. **Verified: `Ran 11 tests ... OK`** (run during this research).
- **The checkpoint judgment + LLM triage is an agent procedure** → validated by the **testbed
  dogfood, not a unit test:** introduce a sharp principle; violate it → surfaces +
  resolve-to-proceed; refute a false positive → logged; re-run unchanged → **auto-cleared** (no
  re-nag); change the code so the prior no longer maps → **retired + re-evaluated**; add a
  *new* violation to a previously-refuted file → **escalates, not auto-cleared** (the key
  guardrail). Production webapp is off-limits.

## 12. Scope boundaries

**In scope:** `principles.py` (`list` / `resolve` / `prior`, incl. supersede); the wrap-up
checkpoint phase; the append-only `principle-resolutions.jsonl` index; soft injection into
wrap-up + spec-manager `create`/`scan`; a one-line principles pointer for code review.

**Out of scope:** G3 (intent-vs-intent contradiction checks); promoting a principle to a guard
scenario (optional, deferred); the **auto-fail hard gate** on model confidence (deferred until
the false-positive rate is measured on a real project); wiring the third-party superpowers
`brainstorming`/`writing-plans`; ADR-awareness.

---

### Sanitization note
The `app/api/health/route.ts` + `"intentional public health check"` example and the
`abc1234` / `SPEC-007` values are illustrative examples drawn verbatim from the design spec
and template — they are not proprietary viva-croatia content. No secrets, credentials,
internal URLs, or customer data appear in any source read.

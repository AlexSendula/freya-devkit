# Governance G1 — Declared-Intent Records

*Research brief for the Behavior Layer explainer webapp. Audience: an engineer on `main` who has never seen this feature.*

Sources read in full:
- `docs/superpowers/specs/2026-07-01-g1-declared-intent-records-design.md` (design)
- `docs/superpowers/plans/2026-07-01-g1-declared-intent-records.md` (implementation plan)
- `skills/spec-manager/scripts/intent.py` (authoring helper — shipped)
- `skills/spec-manager/scripts/verify_intent.py` (the gate — shipped)
- Corroborating: `skills/spec-manager/scripts/frontmatter.py` (parser), and the wiring in `skills/spec-manager/SKILL.md` + `skills/wrap-up/SKILL.md`.

---

## 1. The one-sentence version

An `accepted` behavior's **test** is its machine-checkable guarantee. G1 gives that test **exactly one sanctioned way to change**: a durable, machine-checkable **declared-intent record** named `INTENT-NNN`. Any other way you change it — a bare code edit that turns the test red, or a stealthy edit-both-code-and-test-together that keeps it green — is a **regression**, and wrap-up **hard-blocks** on it. Chat history saying "yeah I meant to do that" does not count.

## 2. The hole G1 plugs (this is the "why")

The system keeps three artifacts in agreement: **code**, the **test**, and the **description** (a `BEH-NNN` record's prose).

- **Code ↔ test** is checkable as a **fact**: you *run the test*. Disagreement ⇒ red ⇒ hard-block. This is "the strongest guarantee in the system."
- **Test ↔ description** is only a **judgment**: no machine can prove an English sentence correctly describes a test. That is owned by a separate, judgment-shaped governance track (G3), **not** G1.

The fact-gate has **one blind spot: editing the test itself.** If you change the code *and* the test together, the test still passes — **green** — so the fact-layer sees nothing, even though the guarantee was silently redefined. Quoting the design:

> That is the one way to slip a changed guarantee past the strongest check in the system.

**G1 exists solely to plug that hole.** It makes the *act of editing an accepted test* require a durable, conscious record — converting an invisible green change into a visible, declared one. Crucially, the question G1 asks is itself a **fact**, so G1 stays 100% deterministic (git + file reads, no model):

> "Was an accepted test edited, and is there a record naming it?"

### The gap this closes (concrete)

A prior sub-project (SP1) already made a *failing* accepted test hard-block wrap-up, and the blocking messages *referred* to "declare intent (file an `INTENT-NNN`)" as the escape hatch — **but that artifact did not exist yet.** So before G1, the only sanctioned responses to a red accepted test were "fix the code" or "quarantine"; an *intentional* change to an accepted guarantee had **no legitimate path** through the gate. G1 builds that path.

## 3. The `INTENT-NNN` record

**Home & IDs:** `knowledge-base/intents/INTENT-NNN.md`. IDs allocate sequentially, zero-padded to 3 digits (`INTENT-001`, `INTENT-002`, …), the same convention as `SPEC-NNN` / `BEH-NNN`. Empty/absent dir ⇒ first id is `INTENT-001`.

**Format — block-style YAML lists only.** Verbatim example from the design:

```markdown
---
id: INTENT-001
behaviors:
  - BEH-003
approver: Alex
date: 2026-07-01
---
## Rationale
Anti-enumeration response changed from a 404 to a uniform 200
per the revised threat model (status-code enumeration).
```

**Fields:**
- `id` — `INTENT-NNN`.
- `behaviors` — the list of `BEH-NNN`s this record authorizes changing (a **block-style `-` list**, never inline `[BEH-003]`).
- `approver` — captured, **not authenticated** (see below).
- `date`.
- `## Rationale` — free text, the durable "why".

**Why block-style only?** The plugin uses a hand-rolled, stdlib-only frontmatter parser. Historically it silently *dropped inline arrays* (`tags: [a, b]`). G1 sidesteps that by specifying block-style lists in the record, so G1 does **not** require replacing the parser first. (The parser has since been rewritten to *fail loud* on inline-array-shaped input rather than drop it — see §7.)

**Approver semantics — the honest part.** Deterministically you cannot verify identity, so `approver` is captured, not authenticated. Solo, author == approver; **the record's value is durable conscious confirmation, not external sign-off.** In a team context, external approval is supplied out-of-band by PR review of the commit carrying the record; the tooling does not try to own that.

**Lifecycle / "spent."** A record is scoped to the change-set it ships in (the incremental diff since the last successful wrap-up). Once that wrap-up succeeds and advances the baseline, the record has done its job and stays in the tree as durable history. It **cannot** authorize a later edit, because that edit shows up in a *subsequent* diff with no accompanying *new* record. This "temporal self-scoping" replaces content-hash fingerprinting (deliberately dropped from scope).

## 4. The rule G1 enforces — stated precisely

- An accepted behavior's test may **only** be changed through a declared-intent record.
- **Chat history does not count.** The record is durable and machine-checkable; conversation is neither.
- A **bare code change that breaks an accepted test is always a regression.** The escape hatch for an *intentional* change is a record; the escape hatch for "this test is broken infrastructure, not the guarantee" is **quarantine** (mark the behavior `quarantined`).
- The gate checks **presence only** — that a new record naming the edited behavior *exists in the change-set*. It does **not** verify the rationale is honest or that the description was updated. That is judgment (G3), out of scope for G1. There is **no cosmetic-edit exemption** — "regardless of what" the edit is, an edit to an accepted test triggers the requirement.

### What actually triggers the requirement (the trigger table)

Keyed off git status of the accepted-behavior **locators** (the file path linking a behavior to its test), using the behavior's **state at HEAD** (post-change):

| Locator change | Behavior `accepted` at HEAD? | Record required? |
|---|---|---|
| **Modified** (M) | yes | **yes** — the "regardless of what" case |
| **Deleted** (D) | yes | **yes** — removing a live guarantee is an intent change |
| **Added** (A) for a brand-new behavior | yes | **no** — normal accept flow, not a change to an existing guarantee |
| **Renamed** (R, no content change / R100) | yes | **no** — moving a file is not changing the guarantee |
| any change | **no** (`proposed`/`confirmed`/`quarantined`/`deprecated`) | **no** — only accepted guarantees are governed |

Note the escape-valve rows: if a behavior is `quarantine`d or `deprecate`d **in the same change** as its test edit, it is not accepted at HEAD ⇒ **no record needed**. A rename with edits (R<100) counts as **modified** and does need one.

## 5. The deterministic gate — `verify_intent.py`

It is a **sibling** to `verify_links.py` in spec-manager: same **Tier-1 hard-block** tier and exit-code convention, but kept a separate script because it is **git-aware / transition-based**, whereas `verify_links` is a stateless single-snapshot check. (Mixing a baseline diff into `verify_links` would muddy a clean stateless script.)

**Inputs:** the **baseline commit** (G1's own marker); the accepted behaviors + their `locator`s (read from spec frontmatter directly, no dependency on `behavior.json`); and the current change-set.

### The algorithm (verbatim from the shipped code / design)

1. `changed` = files changed between baseline and working tree, via `git diff --name-status -M <baseline>`. This one-ref diff spans **committed changes since baseline AND tracked working-tree edits** — both count. Renames record the new path with an `("R", similarity)` tuple.
2. `edited_accepted` = behaviors `accepted` at HEAD whose `locator` is in `changed` with status **M or D** (`_is_change` returns True for `M`/`D`, and for a rename only when similarity `< 100`; excludes `A` and pure `R100`).
3. `records_in_change` = every `knowledge-base/intents/INTENT-NNN.md` present **on disk** that was **absent at the baseline commit** (`git cat-file -e <baseline>:<path>` fails ⇒ new). Discovery is by **filesystem scan, not `git diff`** — so untracked, staged, and committed records all count uniformly. Pre-existing records are ignored (self-scoping).
4. `covered` = union of every in-change record's `behaviors:`.
5. `unauthorized` = `edited_accepted − covered`.
6. If `unauthorized` is non-empty ⇒ **exit non-zero (hard-block)**, printing each behavior, its changed locator, and the remedy.

### The baseline marker — and why it is G1's own

G1 keeps a **dedicated** marker file: `knowledge-base/intents/.intent-last-verified`. It **must not reuse `.spec-last-update`.** Here is the load-bearing reason:

> wrap-up advances `.spec-last-update` in **Phase 3** (spec-manager update), *before* the Phase 3.5 behavior-integrity check runs — so by check time the baseline would equal HEAD, the diff would be empty, and G1 would be **silently disabled**.

So the `.intent-last-verified` marker is advanced **only after the gate passes**, mechanically at **Phase 5** (with the other tracking files), never before the check. The marker format is two lines:

```
# Intent gate last-verified
commit: <full-sha>
```

**No-baseline behavior is fail-open.** If `.intent-last-verified` does not exist (fresh repo / full-scan mode), the check **skips** and never blocks; the marker is created at the first successful wrap-up. Likewise, `_git` never raises and a git error yields an empty diff ⇒ skip rather than a false block. Do **not** "harden" this into a block — it is intentional.

### Key function signatures & constants (from `verify_intent.py`)

- `verify_intent(project_dir=".") -> dict` — returns the result dict.
- `advance_marker(project_dir)` — writes marker = current HEAD, returns the commit (or `None` on git error).
- `MARKER_RELPATH = "knowledge-base/intents/.intent-last-verified"`
- `INTENTS_RELDIR = "knowledge-base/intents"`
- Result dict keys: `version`, `baseline`, `skipped`, `edited_accepted`, `records_in_change`, `authorized`, `unauthorized`, `errors`, `warnings`, and optionally `note`.

### CLI, output, and the exit-code contract

```
python verify_intent.py --project .
python verify_intent.py --project . --format json
python verify_intent.py --project . --advance   # write marker = current HEAD
```

Flags: `--project/-p` (default `.`), `--format/-f {text,json}` (default `text`), `--advance`.

**Exit code:** `1` when `unauthorized` **or** `errors` is non-empty (the `_blocking()` predicate), else `0`. `--advance` exits `0` on success, `1` on git error.

**The contract (mirrors `verify_links`):** `--format json` emits the **complete** result — including `unauthorized`, `edited_accepted`, `records_in_change`, warnings — **even on a non-zero exit**. Consumers **must not** invoke it with `check=True`; they must read the JSON on the non-zero exit. A `check=True` call would raise and throw the JSON away.

### Warnings vs. hard errors (the two failure modes)

- A record naming a **non-existent `BEH`** ⇒ a **warning**, not a hard-block on that alone (`"{rec['id']} names {bid}, which is not a known behavior"`).
- A **malformed / unparseable record** ⇒ **fails loud** as an error (which is *blocking*, since `_blocking` checks `errors`). "A broken record must never silently 'cover' anything."

### The remedy line the gate prints (text mode)

```
[BEH-001] SPEC-001: features/auth/login.feature changed — file
knowledge-base/intents/INTENT-NNN.md naming BEH-001
(intent.py new --behavior BEH-001), or revert the test edit.
```

## 6. The authoring helper — `intent.py new`

Turns "blocked" into a ~20-second action. It allocates the next `INTENT-NNN`, prefills `behaviors:`, stamps `date`/`approver`, and opens a rationale stub.

**CLI (shipped):**

```
python intent.py new --behavior BEH-003 --approver "<you>" \
  --rationale "<why the guarantee is changing>"
```

Flags on the `new` subcommand: `--behavior/-b BEH-NNN` (**required, repeatable** — validated against `^BEH-\d+$`), `--approver` (required), `--rationale` (default `"TODO: why this accepted behavior is changing."`), `--date` (default: today, via `datetime.date.today().isoformat()`), `--project/-p` (default `.`). It prints the created record path.

**Signatures:**
- `render_record(intent_id, behaviors, approver, rationale, day) -> str` — block-style frontmatter + `## Rationale`.
- `_next_id(intents_dir: Path) -> str` — next `INTENT-NNN`, zero-padded 3; `INTENT-001` on empty/absent dir.
- `new_record(project_dir, behaviors, approver, rationale, day) -> str` — creates `knowledge-base/intents/` if absent, writes the record, returns its path.

## 7. `verify_intent` fail-loud on an unparseable record (implementation detail worth calling out)

The **shipped** `verify_intent.py` is slightly stronger than the plan's draft. In `_load_records`, it wraps the parse in try/except and imports `FrontmatterError`:

```python
try:
    fm, _body = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
except FrontmatterError as exc:
    errors.append(f"{f.name}: unparseable frontmatter — {exc}")
    continue
except Exception as exc:  # noqa: BLE001 — defensive: never crash on a bad record
    errors.append(f"{f.name}: could not read record — {exc}")
    continue
```

So an unparseable `INTENT` record produces a **clean error string, no traceback** — the process still exits non-zero (blocking) and still emits complete JSON. This matters because `frontmatter.py` deliberately **"fails loud"**, raising `FrontmatterError` on anything outside its grammar; `verify_intent` catches that so a single broken record blocks cleanly instead of crashing the whole gate. A separate `else` branch also treats a record with a missing/empty `behaviors:` list as a malformed error.

## 8. Integration & data flow (where the gate actually runs)

- **`spec-manager verify`** runs `verify_links` **and** `verify_intent` — both Tier-1 hard-block. (SKILL.md `verify` section, step `1b`.)
- **`spec-manager intent new <BEH...>`** is the Quick-Reference authoring command; `init` now creates `knowledge-base/intents/` (starts empty with a `.gitkeep`).
- **wrap-up Phase 3.5** ("Behavior Integrity & Accepted-Behavior Run") gains one deterministic step alongside the existing `verify_links` hard-block: run `verify_intent`; a non-empty `unauthorized` set **blocks wrap-up**.
- **wrap-up Phase 5** advances the `.intent-last-verified` marker to the current commit — **only after** the Phase 3.5 gate passed — via `verify_intent.py --project . --advance`.

**Behavior-aware staging (two-commit pattern):**
- `INTENT-NNN.md` + the `.intent-last-verified` marker live in `knowledge-base/` ⇒ **artifacts commit (commit 2)**.
- The **code commit (commit 1)** carries the test edit and the `Intent: INTENT-NNN` **trailer** (strongly-recommended traceability, not gate-enforcing — commit messages get mangled by rebase/amend, so **the file is the gate's source of truth**).

**Timing note (why the gate reads the working tree, not just HEAD):** in wrap-up's two-commit flow the test edit lands in commit 1, but the record is staged for commit 2 — and Phase 3.5 runs *between* them. So at check time the edited test is committed while the record is only in the working tree. `verify_intent` therefore reads working-tree state (the one-ref `git diff <baseline>` plus a filesystem scan for records) so it sees the record before commit 2 exists.

## 9. The canonical end-to-end example (the BEH-003 case)

1. Engineer decides the anti-enumeration response should change; edits **code and BEH-003's test together** so it stays **green**.
2. `wrap-up` → Phase 0 commits the code (including the test edit).
3. Phase 3.5 `verify_intent`: BEH-003's locator is `M`, no record names it ⇒ **BLOCK** with the remedy line.
4. Engineer runs `spec-manager intent new BEH-003`, writes one sentence of rationale, sets approver.
5. Re-run `wrap-up` → `verify_intent` sees the new record covering BEH-003 ⇒ **passes**. Artifacts commit includes `INTENT-001.md`; the code commit's trailer points to it.

Control case (proves the gate is narrow): edit a `proposed` behavior's test ⇒ **never blocked**.

## 10. Why this is what makes the two blast-radius directions trustworthy

The Behavior Layer's headline promise is two directions of blast radius: **code change → affected behaviors**, and **behavior → implementing code**. Both directions are only as trustworthy as the claim that *an accepted test still means what it says it means*. Without G1, an accepted guarantee could be silently redefined (the green edit-both hole), and every downstream "this behavior is guaranteed" answer would be built on sand — "every red test degrades into 'just update it' until the safety net rots." G1 makes every change to an accepted guarantee **visible, deliberate, and auditable** — a durable artifact in the tree, never a silently-changed guarantee. That is what lets the rest of the system *trust* an `accepted` state as a real, standing guarantee.

## 11. Known limits (be honest in the explainer)

- **Shared test helpers.** If an accepted behavior's assertions live partly in a helper file that is *not* the `locator`, editing only the helper would not trip the path-based check. Accepted limitation for G1 (both a content-hash and a diff approach share it). A future refinement could widen detection to the test's import closure.
- **Honesty is out of scope.** G1 presence-checks a record; it does **not** verify the rationale is truthful or that the `BEH` description still matches the changed test. That is G3 (model contradiction checks). G1's blast radius on a misjudgment is "a visible, auditable artifact in the tree."
- **No identity/approval verification, no ADR-awareness, no auto-rewriting of descriptions** — all explicitly out of scope.

## 12. Verification status

- `test_verify_intent.py` — **16 tests, OK** (the plan predicted 15; the shipped suite added one, consistent with the extra fail-loud/unparseable coverage).
- `test_intent.py` — **5 tests, OK.**
- SKILL.md wiring confirmed present in both `spec-manager/SKILL.md` and `wrap-up/SKILL.md` (Quick Reference row, `verify` step 1b, Declared-Intent Records subsection, Phase 3.5 gate, Phase 5 `--advance`, staging-table rows).
